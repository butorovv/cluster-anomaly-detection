// Package model adapts raw telemetry to host-centered context scores.
package model

import (
	"encoding/hex"
	"fmt"
	"sort"

	"cluster-anomaly-detection/internal/analysis"
	"cluster-anomaly-detection/internal/modules/telemetry/domain"
)

const Version = "context-profile-v1"

// ContextProfile is fitted exclusively from complete D1 records. GlobalScale
// is the frozen Stage A scale used by the existing IsolationForest.Score.
type ContextProfile struct {
	Version             string                     `json:"version"`
	TrainingWindow      analysis.Window            `json:"training_window"`
	SourceSHA256        string                     `json:"source_sha256"`
	GlobalProfileSHA256 string                     `json:"global_profile_sha256"`
	Hosts               []string                   `json:"hosts"`
	HostMedians         map[string]analysis.Vector `json:"host_medians"`
	GlobalMedian        analysis.Vector            `json:"global_median"`
	GlobalScale         analysis.Vector            `json:"global_scale"`
}

// FitContextProfile computes exact coordinate medians. Host order is retained
// from the source manifest, which also defines stable binary host IDs.
func FitContextProfile(records []domain.TelemetryRecord, hosts []string, global *analysis.StatisticalProfile) (*ContextProfile, error) {
	if global == nil || global.Validate() != nil {
		return nil, fmt.Errorf("invalid global D1 profile")
	}
	if len(hosts) == 0 {
		return nil, fmt.Errorf("empty host list")
	}
	p := &ContextProfile{Version: Version, TrainingWindow: analysis.NIRWindows()[0], Hosts: append([]string(nil), hosts...), HostMedians: map[string]analysis.Vector{}, GlobalMedian: global.Median, GlobalScale: global.Scale}
	cols := make(map[string]*[analysis.Dimensions][]float64, len(hosts))
	for _, h := range hosts {
		if h == "" || cols[h] != nil {
			return nil, fmt.Errorf("invalid or duplicate host")
		}
		cols[h] = &[analysis.Dimensions][]float64{}
	}
	w := analysis.NIRWindows()[0]
	for _, r := range records {
		if !w.Contains(r.Timestamp) {
			return nil, fmt.Errorf("context fitting accepts D1 only")
		}
		c := cols[r.Hostname]
		if c == nil {
			return nil, fmt.Errorf("unknown host %q", r.Hostname)
		}
		v := r.Features()
		if !r.Valid || r.AvailabilityMask != domain.FullAvailabilityMask || !analysis.FiniteVector(v) {
			return nil, fmt.Errorf("D1 context fitting requires complete finite F18")
		}
		for j, x := range v {
			(*c)[j] = append((*c)[j], x)
		}
	}
	for _, h := range hosts {
		if len((*cols[h])[0]) == 0 {
			return nil, fmt.Errorf("host %q has no D1 records", h)
		}
		var med analysis.Vector
		for j := range med {
			xs := (*cols[h])[j]
			sort.Float64s(xs)
			n := len(xs)
			if n%2 == 1 {
				med[j] = xs[n/2]
			} else {
				med[j] = xs[n/2-1]/2 + xs[n/2]/2
			}
		}
		p.HostMedians[h] = med
	}
	return p, p.Validate()
}

func (p *ContextProfile) Validate() error {
	if p == nil || p.Version != Version || p.TrainingWindow != analysis.NIRWindows()[0] || len(p.Hosts) == 0 || len(p.HostMedians) != len(p.Hosts) {
		return fmt.Errorf("invalid context profile metadata")
	}
	if (p.SourceSHA256 == "") != (p.GlobalProfileSHA256 == "") {
		return fmt.Errorf("incomplete context source linkage")
	}
	if p.SourceSHA256 != "" {
		if b, e := hex.DecodeString(p.SourceSHA256); e != nil || len(b) != 32 {
			return fmt.Errorf("invalid context source checksum")
		}
		if b, e := hex.DecodeString(p.GlobalProfileSHA256); e != nil || len(b) != 32 {
			return fmt.Errorf("invalid global profile checksum")
		}
	}
	seen := map[string]bool{}
	for _, h := range p.Hosts {
		m, ok := p.HostMedians[h]
		if h == "" || seen[h] || !ok || !analysis.FiniteVector(m) {
			return fmt.Errorf("invalid context host median")
		}
		seen[h] = true
	}
	for j := 0; j < analysis.Dimensions; j++ {
		if !analysis.Finite(p.GlobalMedian[j]) || !analysis.Finite(p.GlobalScale[j]) || p.GlobalScale[j] <= 0 {
			return fmt.Errorf("invalid global profile coordinate %d", j)
		}
	}
	return nil
}

// ValidateLink binds a loaded context profile to its prepared source and Stage A file.
func (p *ContextProfile) ValidateLink(sourceSHA256, globalProfileSHA256 string) error {
	if err := p.Validate(); err != nil {
		return err
	}
	if p.SourceSHA256 == "" || p.GlobalProfileSHA256 == "" || p.SourceSHA256 != sourceSHA256 || p.GlobalProfileSHA256 != globalProfileSHA256 {
		return fmt.Errorf("context source/global profile linkage mismatch")
	}
	return nil
}

// Adapt returns x - hostMedian + globalMedian. The forest then performs its
// normal single global scale division.
func (p *ContextProfile) Adapt(host string, raw analysis.Vector) (analysis.Vector, error) {
	var out analysis.Vector
	if p == nil || p.Version != Version || p.TrainingWindow != analysis.NIRWindows()[0] {
		return out, fmt.Errorf("invalid context profile metadata")
	}
	m, ok := p.HostMedians[host]
	if !ok {
		return out, fmt.Errorf("unknown context host %q", host)
	}
	if !analysis.FiniteVector(raw) {
		return out, fmt.Errorf("context score requires complete finite F18")
	}
	for j := range out {
		if !analysis.Finite(m[j]) || !analysis.Finite(p.GlobalMedian[j]) || !analysis.Finite(p.GlobalScale[j]) || p.GlobalScale[j] <= 0 {
			return analysis.Vector{}, fmt.Errorf("invalid context profile coordinate %d", j)
		}
		out[j] = raw[j] - m[j] + p.GlobalMedian[j]
		if !analysis.Finite(out[j]) {
			return analysis.Vector{}, fmt.Errorf("context transform overflow")
		}
	}
	return out, nil
}
