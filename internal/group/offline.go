package group

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"fmt"
	"io"
	"os"
	"time"

	"cluster-anomaly-detection/internal/analysis"
	"cluster-anomaly-detection/internal/experiment"
	"cluster-anomaly-detection/internal/local"
	"cluster-anomaly-detection/internal/modules/telemetry/domain"
)

func FileSHA(path string) (string, error) {
	f, e := os.Open(path)
	if e != nil {
		return "", e
	}
	defer f.Close()
	h := sha256.New()
	if _, e = io.Copy(h, f); e != nil {
		return "", e
	}
	return hex.EncodeToString(h.Sum(nil)), nil
}

// WalkTicks emits every tick, including wholly absent ticks. Duplicate and
// unordered rows are rejected before they can affect a fixed-composition group.
func WalkTicks(ctx context.Context, source *experiment.Source, w analysis.Window, visit func(Tick) error) error {
	next := w.Start
	records := map[string]domain.TelemetryRecord{}
	emit := func() error {
		if e := visit(Tick{Timestamp: next, Records: records}); e != nil {
			return e
		}
		next = next.Add(analysis.Step)
		records = map[string]domain.TelemetryRecord{}
		return nil
	}
	_, err := source.Scan(ctx, w, func(r domain.TelemetryRecord) error {
		if r.Timestamp.Before(next) {
			return fmt.Errorf("unordered tick")
		}
		for next.Before(r.Timestamp) {
			if e := emit(); e != nil {
				return e
			}
		}
		if _, ok := records[r.Hostname]; ok {
			return fmt.Errorf("duplicate host/timestamp")
		}
		records[r.Hostname] = r
		return nil
	})
	if err != nil {
		return err
	}
	for next.Before(w.End) {
		if err = emit(); err != nil {
			return err
		}
	}
	return nil
}
func Fit(ctx context.Context, m *local.Models, hashes map[string]string) (*Profile, error) {
	p := &Profile{Version: Version, Binding: m.Binding, InputSHA: hashes, TrainingWindow: analysis.NIRWindows()[0], Floor: Floor, RCond: RCond, DDOF: 1}
	var data [16][]Sample
	err := WalkTicks(ctx, m.Source, p.TrainingWindow, func(t Tick) error {
		for g := 0; g < 16; g++ {
			s := Sample{Timestamp: t.Timestamp}
			complete := true
			for h := 0; h < 18; h++ {
				r, ok := t.Records[m.Binding.Hosts[g*18+h]]
				if !ok {
					complete = false
					break
				}
				v, e := HostChannels(r)
				if e != nil {
					complete = false
					break
				}
				s.Values[h] = v
			}
			if complete {
				var e error
				s.Vector, e = GroupVector(s.Values)
				if e != nil {
					return e
				}
				data[g] = append(data[g], s)
			}
		}
		return nil
	})
	if err != nil {
		return nil, err
	}
	for g := 0; g < 16; g++ {
		v, e := FitGroup(fmt.Sprintf("a%02d", g+1), m.Binding.Hosts[g*18:g*18+18], data[g])
		if e != nil {
			return nil, e
		}
		p.Groups = append(p.Groups, v)
		data[g] = nil
	}
	return p, p.Validate()
}

type Timing struct {
	FeaturesSeconds float64 `json:"features_seconds"`
	RSeconds        float64 `json:"r_seconds"`
	BSeconds        float64 `json:"b_seconds"`
	YSeconds        float64 `json:"y_seconds"`
	IFSeconds       float64 `json:"if_seconds"`
	TemporalSeconds float64 `json:"temporal_seconds"`
}

func Evaluate(p *Profile, t Tick, hw *Hardware, ld *local.Detector, groups int, timing *Timing) ([]Raw, error) {
	if groups != 4 && groups != 8 && groups != 16 {
		return nil, fmt.Errorf("group count must be 4, 8, 16")
	}
	rows := make([]Raw, groups)
	for gi := 0; gi < groups; gi++ {
		g := &p.Groups[gi]
		r := Raw{Timestamp: t.Timestamp, Group: g.Group, HostValues: map[string]HostVector{}}
		var u [18]HostVector
		started := time.Now()
		for h, host := range g.Hosts {
			record, ok := t.Records[host]
			if !ok {
				r.Missing = append(r.Missing, host)
				continue
			}
			v, e := HostChannels(record)
			if e != nil {
				r.Missing = append(r.Missing, host)
				continue
			}
			u[h] = v
			r.HostValues[host] = v
			r.Complete++
		}
		if r.Complete == 18 {
			v, e := GroupVector(u)
			if e != nil {
				return nil, e
			}
			r.Vector = &v
		}
		timing.FeaturesSeconds += time.Since(started).Seconds()
		started = time.Now()
		if r.Vector == nil {
			r.R = RResult{Criterion: Criterion{State: Unknown, Reason: "incomplete_group"}, Channel: -1}
			if g.Observations > 0 {
				r.R.Threshold = ptr(g.RThreshold)
			}
		} else {
			r.R = g.R(u)
		}
		timing.RSeconds += time.Since(started).Seconds()
		started = time.Now()
		if r.Vector == nil {
			r.B = Criterion{State: Unknown, Reason: "incomplete_group"}
			if g.BThreshold != nil {
				r.B.Threshold = ptr(*g.BThreshold)
			}
		} else {
			r.B = g.B(*r.Vector)
		}
		timing.BSeconds += time.Since(started).Seconds()
		started = time.Now()
		r.Y = hw.Evaluate(g.Hosts, t.Records)
		timing.YSeconds += time.Since(started).Seconds()
		started = time.Now()
		for _, host := range g.Hosts {
			record, ok := t.Records[host]
			lr := local.LocalResult{Timestamp: t.Timestamp, Hostname: host, GroupID: g.Group, DiagnosticStatus: "missing_observation"}
			if ok {
				lr = ld.Evaluate(record)
			}
			if lr.DiagnosticStatus == local.StatusScoringError {
				return nil, fmt.Errorf("local score: %s", lr.Diagnostic)
			}
			r.Local = append(r.Local, lr)
			if lr.IsAvailable {
				r.IF.Available++
				if lr.IsAnomaly != nil && *lr.IsAnomaly {
					r.IF.Anomalous++
				}
			}
		}
		timing.IFSeconds += time.Since(started).Seconds()
		if r.IF.Available > 0 {
			r.IF.S = ptr(float64(r.IF.Anomalous) / float64(r.IF.Available))
		}
		rows[gi] = r
	}
	AnnotateOutside(rows)
	return rows, nil
}
func AnnotateOutside(rows []Raw) {
	for i := range rows {
		s := &rows[i].IF
		s.OutsideAvailable = 0
		s.OutsideAnomalous = 0
		s.OutsideGroups = nil
		s.OutsideS = nil
		s.E = nil
		for j := range rows {
			if i == j {
				continue
			}
			s.OutsideGroups = append(s.OutsideGroups, rows[j].Group)
			s.OutsideAvailable += rows[j].IF.Available
			s.OutsideAnomalous += rows[j].IF.Anomalous
		}
		if s.OutsideAvailable > 0 {
			s.OutsideS = ptr(float64(s.OutsideAnomalous) / float64(s.OutsideAvailable))
			if s.S != nil {
				s.E = ptr(*s.S - *s.OutsideS)
			}
		}
	}
}
