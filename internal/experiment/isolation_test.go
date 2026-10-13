package experiment

import (
	"context"
	"encoding/json"
	"math"
	"os"
	"path/filepath"
	"reflect"
	"testing"

	"cluster-anomaly-detection/internal/analysis"
	"cluster-anomaly-detection/internal/modules/telemetry/domain"
)

func isolationFixture(t *testing.T) (*Source, string, *IsolationRun) {
	t.Helper()
	s := &Source{SHA256: "synthetic-dataset-sha", Hosts: []string{"a01n01"}, Groups: []string{"a01"}, AssumedTimezone: "UTC"}
	data := func(ctx context.Context, visit func(analysis.Observation) error) error {
		for _, v := range []analysis.Vector{{-2}, {-1}, {1}, {2}} {
			if err := visit(analysis.Observation{Timestamp: analysis.NIRWindows()[0].Start, Features: v}); err != nil {
				return err
			}
		}
		return ctx.Err()
	}
	p, err := analysis.FitStatistical(context.Background(), data, analysis.NIRWindows()[0], analysis.StatisticalConfig{SVDRCond: 1e-12, CovarianceDDOF: 1})
	if err != nil {
		t.Fatal(err)
	}
	stat := filepath.Join(t.TempDir(), "statistical.json")
	if err = SaveNew(stat, StatisticalRun{Source: s, Profile: p}); err != nil {
		t.Fatal(err)
	}
	_, ref, err := isolationNormalizer(stat, s)
	if err != nil {
		t.Fatal(err)
	}
	f, err := analysis.FitIsolation(context.Background(), data, p, analysis.NIRWindows()[0], analysis.IsolationConfig{Trees: 10, SampleSize: 4, MaxDepth: 3, Seed: 42})
	if err != nil {
		t.Fatal(err)
	}
	a := Audit{Window: analysis.NIRWindows()[0], States: 829440, Valid: 4, Timestamps: 2880, Hosts: 288, MinimumStatesPerTimestamp: 288}
	// This synthetic envelope tests binding and count consistency, not real-grid
	// scanning. Real training/evaluation is executed separately by cmd/isolation.
	r := &IsolationRun{Source: s, FeatureOrder: append([]string(nil), domain.FeatureNames[:]...), StatisticalReference: ref, Profile: f, TrainingAudit: a, D1: IsolationEvaluation{Audit: a, Scores: IsolationScores{Count: 4}}}
	return s, stat, r
}

func TestIsolationEnvelopeRoundTripAndBinding(t *testing.T) {
	s, stat, r := isolationFixture(t)
	path := filepath.Join(t.TempDir(), "isolation.json")
	if err := SaveNew(path, r); err != nil {
		t.Fatal(err)
	}
	loaded, err := LoadIsolationProfile(path, s, stat)
	if err != nil {
		t.Fatal(err)
	}
	before, _ := json.Marshal(r.Profile)
	after, _ := json.Marshal(loaded.Profile)
	if string(before) != string(after) {
		t.Fatal("persisted forest changed")
	}
	for _, v := range []analysis.Vector{{-10}, {0}, {10}} {
		want, e := r.Profile.Score(v)
		if e != nil {
			t.Fatal(e)
		}
		got, e := loaded.Profile.Score(v)
		if e != nil || got != want {
			t.Fatal("score changed on reload", got, want, e)
		}
	}
	for _, mutate := range []func(*Source){func(s *Source) { s.SHA256 = "other" }, func(s *Source) { s.Hosts = []string{"a01n02"} }, func(s *Source) { s.Groups = []string{"a02"} }, func(s *Source) { s.AssumedTimezone = "Europe/Moscow" }, func(s *Source) { s.TimezoneVerified = true }} {
		other := *s
		mutate(&other)
		if _, err = LoadIsolationProfile(path, &other, stat); err == nil {
			t.Fatal("accepted mismatched source")
		}
	}
	b, err := os.ReadFile(stat)
	if err != nil {
		t.Fatal(err)
	}
	// Even identical numeric parameters in a different file envelope have a new
	// file identity. Copies at different paths with identical bytes remain valid.
	copyPath := filepath.Join(t.TempDir(), "stat-copy.json")
	if err = os.WriteFile(copyPath, b, 0600); err != nil {
		t.Fatal(err)
	}
	if _, err = LoadIsolationProfile(path, s, copyPath); err != nil {
		t.Fatal(err)
	}
	if err = os.WriteFile(copyPath, append(b, ' '), 0600); err != nil {
		t.Fatal(err)
	}
	if _, err = LoadIsolationProfile(path, s, copyPath); err == nil {
		t.Fatal("accepted a different statistical file identity")
	}
}

func TestIsolationEnvelopeRejectsCorruption(t *testing.T) {
	s, stat, r := isolationFixture(t)
	path := filepath.Join(t.TempDir(), "isolation.json")
	for _, mutate := range []func(*IsolationRun){
		func(r *IsolationRun) { r.FeatureOrder[0], r.FeatureOrder[1] = r.FeatureOrder[1], r.FeatureOrder[0] },
		func(r *IsolationRun) { r.StatisticalReference.SHA256 = "other" },
		func(r *IsolationRun) { r.StatisticalReference.Version = "unknown" },
		func(r *IsolationRun) { r.Profile.Median[0] += 1 },
		func(r *IsolationRun) { r.Profile.TrainingWindow = analysis.NIRWindows()[1] },
		func(r *IsolationRun) { r.Profile.Trees[0].Size-- },
		func(r *IsolationRun) { r.TrainingAudit.Valid-- },
		func(r *IsolationRun) { r.TrainingAudit.States-- },
		func(r *IsolationRun) { r.D1.Scores.Count++ },
		func(r *IsolationRun) { r.Source = nil },
		func(r *IsolationRun) { r.Profile = nil },
	} {
		b, err := json.Marshal(r)
		if err != nil {
			t.Fatal(err)
		}
		var other IsolationRun
		if err = json.Unmarshal(b, &other); err != nil {
			t.Fatal(err)
		}
		mutate(&other)
		b, err = json.Marshal(other)
		if err != nil {
			t.Fatal(err)
		}
		if err = os.WriteFile(path, b, 0600); err != nil {
			t.Fatal(err)
		}
		if _, err = LoadIsolationProfile(path, s, stat); err == nil {
			t.Fatal("accepted corrupted envelope")
		}
	}
	for _, bad := range []string{"{}", "{", `{"isolation_forest":null}`} {
		if err := os.WriteFile(path, []byte(bad), 0600); err != nil {
			t.Fatal(err)
		}
		if _, err := LoadIsolationProfile(path, s, stat); err == nil {
			t.Fatal("accepted malformed envelope")
		}
	}
}

func TestIsolationDescriptiveScores(t *testing.T) {
	values := []float64{.8, .2, .4, .6}
	got, err := summarizeIsolation(values)
	if err != nil {
		t.Fatal(err)
	}
	if got.Count != 4 || got.Min != .2 || got.Max != .8 || math.Abs(got.Mean-.5) > 1e-15 || math.Abs(got.StdDev-math.Sqrt(.05)) > 1e-15 || got.Q01 != .2 || got.Q50 != .4 || got.Q95 != .8 || got.Q99 != .8 {
		t.Fatal(got)
	}
	for _, values := range [][]float64{nil, {math.NaN()}, {math.Inf(1)}, {-.1}, {0}, {1.1}} {
		if _, err := summarizeIsolation(values); err == nil {
			t.Fatal("invalid scores accepted")
		}
	}
}

func TestIsolationNormalizerRejectsDifferentSourceAndInvalidProfile(t *testing.T) {
	s, stat, _ := isolationFixture(t)
	other := *s
	other.SHA256 = "different"
	if _, _, err := isolationNormalizer(stat, &other); err == nil {
		t.Fatal("accepted other dataset")
	}
	b, err := os.ReadFile(stat)
	if err != nil {
		t.Fatal(err)
	}
	var run StatisticalRun
	if err = json.Unmarshal(b, &run); err != nil {
		t.Fatal(err)
	}
	run.Profile.TrainingWindow = analysis.NIRWindows()[1]
	b, err = json.Marshal(run)
	if err != nil {
		t.Fatal(err)
	}
	if err = os.WriteFile(stat, b, 0600); err != nil {
		t.Fatal(err)
	}
	if _, _, err = isolationNormalizer(stat, s); err == nil {
		t.Fatal("accepted non-D1 profile")
	}
	if _, err = StageC(context.Background(), nil, stat, analysis.DefaultIsolationConfig(), nil); err == nil {
		t.Fatal("nil source accepted")
	}
}

func TestRealIsolationProfileReloadD1(t *testing.T) {
	input, stat, path := os.Getenv("NIR_REAL_PARQUET"), os.Getenv("NIR_REAL_PROFILE"), os.Getenv("NIR_REAL_ISOLATION_PROFILE")
	if input == "" || stat == "" || path == "" {
		t.Skip("real D1 isolation inputs not configured")
	}
	s, err := OpenSource(input, filepath.Join(filepath.Dir(input), "manifest.json"))
	if err != nil {
		t.Fatal(err)
	}
	r, err := LoadIsolationProfile(path, s, stat)
	if err != nil {
		t.Fatal(err)
	}
	before, _ := json.Marshal(r.Profile)
	e, err := EvaluateIsolationD1(context.Background(), s, r.Profile)
	if err != nil {
		t.Fatal(err)
	}
	after, _ := json.Marshal(r.Profile)
	if !reflect.DeepEqual(e.Scores, r.D1.Scores) || e.Audit != r.D1.Audit || string(before) != string(after) {
		t.Fatal("D1 scores/audit/forest changed after reload")
	}
	t.Logf("D1 count=%d mean=%.16g range=[%.16g,%.16g] reloaded exactly", e.Scores.Count, e.Scores.Mean, e.Scores.Min, e.Scores.Max)
}
