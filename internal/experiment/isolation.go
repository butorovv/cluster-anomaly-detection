package experiment

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"math"
	"os"
	"reflect"
	"runtime"
	"slices"
	"sort"
	"sync"
	"time"

	"cluster-anomaly-detection/internal/analysis"
	"cluster-anomaly-detection/internal/modules/telemetry/domain"
)

type StatisticalReference struct {
	Path    string `json:"path"`
	SHA256  string `json:"file_sha256"`
	Version string `json:"version"`
}

type IsolationScores struct {
	Count  int     `json:"count"`
	Min    float64 `json:"min"`
	Max    float64 `json:"max"`
	Mean   float64 `json:"mean"`
	StdDev float64 `json:"population_stddev"`
	Q01    float64 `json:"q01"`
	Q50    float64 `json:"q50"`
	Q95    float64 `json:"q95"`
	Q99    float64 `json:"q99"`
}

type IsolationEvaluation struct {
	Audit          Audit           `json:"audit"`
	Scores         IsolationScores `json:"scores"`
	ElapsedSeconds float64         `json:"scan_and_score_seconds"`
	ScoreSeconds   float64         `json:"score_compute_seconds"`
}

type IsolationResources struct {
	TrainingSeconds      float64 `json:"training_scan_and_build_seconds"`
	ElapsedSeconds       float64 `json:"elapsed_seconds"`
	PeakSampledHeapBytes uint64  `json:"peak_sampled_go_heap_bytes"`
	PeakSampledSysBytes  uint64  `json:"peak_sampled_go_sys_bytes"`
	SampleIntervalMS     int     `json:"memory_sample_interval_ms"`
}

type IsolationRun struct {
	Source               *Source                   `json:"source"`
	FeatureOrder         []string                  `json:"feature_order"`
	StatisticalReference StatisticalReference      `json:"statistical_reference"`
	Profile              *analysis.IsolationForest `json:"isolation_forest"`
	TrainingAudit        Audit                     `json:"training_audit"`
	D1                   IsolationEvaluation       `json:"d1_diagnostics"`
	Resources            IsolationResources        `json:"resources"`
}

func sameIsolationSource(a, b *Source) bool {
	return a != nil && b != nil && a.SHA256 != "" && a.SHA256 == b.SHA256 && slices.Equal(a.Hosts, b.Hosts) && slices.Equal(a.Groups, b.Groups) && a.AssumedTimezone == b.AssumedTimezone && a.TimezoneVerified == b.TimezoneVerified
}

// Bind the existing Stage A envelope to this immutable dataset before reusing
// its D1 normalization. The file checksum identifies the exact saved profile.
func isolationNormalizer(path string, s *Source) (*analysis.StatisticalProfile, StatisticalReference, error) {
	var ref StatisticalReference
	b, err := os.ReadFile(path)
	if err != nil {
		return nil, ref, err
	}
	var run StatisticalRun
	if err = json.Unmarshal(b, &run); err != nil {
		return nil, ref, err
	}
	if err = run.Profile.Validate(); err != nil {
		return nil, ref, err
	}
	if !sameIsolationSource(s, run.Source) {
		return nil, ref, fmt.Errorf("statistical profile source/topology mismatch")
	}
	h := sha256.Sum256(b)
	ref = StatisticalReference{path, hex.EncodeToString(h[:]), run.Profile.Version}
	return run.Profile, ref, nil
}

func summarizeIsolation(values []float64) (IsolationScores, error) {
	if len(values) == 0 {
		return IsolationScores{}, fmt.Errorf("no complete finite states to score")
	}
	r := IsolationScores{Count: len(values), Min: values[0], Max: values[0]}
	var m2 float64
	for i, v := range values {
		if !analysis.Finite(v) || v <= 0 || v > 1 {
			return r, fmt.Errorf("invalid IF score")
		}
		r.Min = math.Min(r.Min, v)
		r.Max = math.Max(r.Max, v)
		d := v - r.Mean
		r.Mean += d / float64(i+1)
		m2 += d * (v - r.Mean)
	}
	r.StdDev = math.Sqrt(math.Max(0, m2/float64(len(values))))
	// Only scalar scores (about 6.3 MiB on D1) are retained for exact descriptive
	// quantiles. No full F18 dataset or anomaly classification is materialized.
	sort.Float64s(values)
	q := func(p float64) float64 { return values[int(math.Ceil(p*float64(len(values))))-1] }
	r.Q01, r.Q50, r.Q95, r.Q99 = q(.01), q(.5), q(.95), q(.99)
	return r, nil
}

func EvaluateIsolationD1(ctx context.Context, s *Source, p *analysis.IsolationForest) (*IsolationEvaluation, error) {
	if s == nil {
		return nil, fmt.Errorf("missing isolation source")
	}
	if err := p.Validate(); err != nil {
		return nil, err
	}
	start := time.Now()
	e := &IsolationEvaluation{}
	values := make([]float64, 0, 829440)
	var compute time.Duration
	var err error
	e.Audit, err = s.Scan(ctx, analysis.NIRWindows()[0], func(v domain.TelemetryRecord) error {
		if !v.Valid {
			return nil
		}
		t := time.Now()
		score, err := p.Score(v.Features())
		compute += time.Since(t)
		if err != nil {
			return err
		}
		values = append(values, score)
		return nil
	})
	if err != nil {
		return nil, err
	}
	e.Scores, err = summarizeIsolation(values)
	if err != nil {
		return nil, err
	}
	e.ElapsedSeconds = time.Since(start).Seconds()
	e.ScoreSeconds = compute.Seconds()
	if err = completeIsolationD1(e.Audit); err != nil {
		return nil, err
	}
	return e, nil
}

func completeIsolationD1(a Audit) error {
	if a.Window != analysis.NIRWindows()[0] || a.States != 829440 || a.Timestamps != 2880 || a.Hosts != 288 || a.MinimumStatesPerTimestamp != 288 {
		return fmt.Errorf("incomplete D1 node/time grid: %+v", a)
	}
	return nil
}

// StageC fits one global forest and describes only D1. D2/D3 remain held out.
func StageC(ctx context.Context, s *Source, statisticalPath string, cfg analysis.IsolationConfig, progress func(string)) (*IsolationRun, error) {
	if s == nil {
		return nil, fmt.Errorf("missing isolation source")
	}
	if err := cfg.Validate(); err != nil {
		return nil, err
	}
	start := time.Now()
	r := &IsolationRun{Source: s, FeatureOrder: append([]string(nil), domain.FeatureNames[:]...)}
	p, ref, err := isolationNormalizer(statisticalPath, s)
	if err != nil {
		return nil, err
	}
	r.StatisticalReference = ref
	// Go allocator statistics are sampled independently; these are not process RSS.
	stop := make(chan struct{})
	var wg sync.WaitGroup
	wg.Add(1)
	go func() {
		defer wg.Done()
		ticker := time.NewTicker(20 * time.Millisecond)
		defer ticker.Stop()
		sample := func() {
			var m runtime.MemStats
			runtime.ReadMemStats(&m)
			r.Resources.PeakSampledHeapBytes = max(r.Resources.PeakSampledHeapBytes, m.HeapAlloc)
			r.Resources.PeakSampledSysBytes = max(r.Resources.PeakSampledSysBytes, m.Sys)
		}
		sample()
		for {
			select {
			case <-ticker.C:
				sample()
			case <-stop:
				sample()
				return
			}
		}
	}()
	defer func() { close(stop); wg.Wait() }()
	notify := func(msg string) {
		if progress != nil {
			progress(msg)
		}
	}
	notify("C: sampling only D1 and fitting one global Isolation Forest")
	data := func(ctx context.Context, visit func(analysis.Observation) error) error {
		a, err := s.Scan(ctx, analysis.NIRWindows()[0], func(v domain.TelemetryRecord) error {
			if !v.Valid {
				return nil
			}
			return visit(analysis.Observation{Timestamp: v.Timestamp, Features: v.Features()})
		})
		r.TrainingAudit = a
		return err
	}
	t := time.Now()
	r.Profile, err = analysis.FitIsolation(ctx, data, p, analysis.NIRWindows()[0], cfg)
	r.Resources.TrainingSeconds = time.Since(t).Seconds()
	if err != nil {
		return nil, err
	}
	if err = completeIsolationD1(r.TrainingAudit); err != nil {
		return nil, err
	}
	if r.TrainingAudit.Valid != p.Observations || r.TrainingAudit.Valid != r.Profile.Observations {
		return nil, fmt.Errorf("D1 differs from statistical training population")
	}
	notify("C: describing frozen forest scores on D1 (no threshold)")
	e, err := EvaluateIsolationD1(ctx, s, r.Profile)
	if err != nil {
		return nil, err
	}
	r.D1 = *e
	if r.TrainingAudit != r.D1.Audit {
		return nil, fmt.Errorf("D1 changed between isolation passes")
	}
	r.Resources.ElapsedSeconds = time.Since(start).Seconds()
	r.Resources.SampleIntervalMS = 20
	return r, nil
}

// Loading requires the actual source and original Stage A file, so a forest
// cannot silently reuse a different dataset, feature order or normalizer.
func LoadIsolationProfile(path string, s *Source, statisticalPath string) (*IsolationRun, error) {
	b, err := os.ReadFile(path)
	if err != nil {
		return nil, err
	}
	var run IsolationRun
	if err = json.Unmarshal(b, &run); err != nil {
		return nil, err
	}
	if err = run.Profile.Validate(); err != nil {
		return nil, err
	}
	if !sameIsolationSource(s, run.Source) || !slices.Equal(run.FeatureOrder, domain.FeatureNames[:]) {
		return nil, fmt.Errorf("isolation profile source/F18 mismatch")
	}
	p, ref, err := isolationNormalizer(statisticalPath, s)
	if err != nil {
		return nil, err
	}
	if ref.SHA256 != run.StatisticalReference.SHA256 || ref.Version != run.StatisticalReference.Version || !reflect.DeepEqual(p.Median, run.Profile.Median) || !reflect.DeepEqual(p.MAD, run.Profile.MAD) || !reflect.DeepEqual(p.Scale, run.Profile.Scale) || p.Observations != run.Profile.Observations {
		return nil, fmt.Errorf("isolation statistical reference/normalization mismatch")
	}
	if err = completeIsolationD1(run.TrainingAudit); err != nil {
		return nil, err
	}
	if run.TrainingAudit.Valid != run.Profile.Observations || run.TrainingAudit != run.D1.Audit || run.D1.Scores.Count != run.TrainingAudit.Valid {
		return nil, fmt.Errorf("isolation training/evaluation count mismatch")
	}
	return &run, nil
}
