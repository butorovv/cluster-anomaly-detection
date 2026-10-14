package model

import (
	"context"
	"encoding/json"
	"math"
	"reflect"
	"testing"
	"time"

	"cluster-anomaly-detection/internal/analysis"
	"cluster-anomaly-detection/internal/modules/telemetry/domain"
)

func fixtureProfile() *analysis.StatisticalProfile {
	p := &analysis.StatisticalProfile{Version: "statistical-v1", TrainingWindow: analysis.NIRWindows()[0], Observations: 2, Config: analysis.StatisticalConfig{SVDRCond: 1e-12, CovarianceDDOF: 1}}
	for i := range p.Scale {
		p.Scale[i] = .0001
	}
	return p
}
func record(host string, sec int, value float64) domain.TelemetryRecord {
	r := domain.TelemetryRecord{Hostname: host, GroupID: "a01", NodeIndex: 1, Timestamp: analysis.NIRWindows()[0].Start.Add(time.Duration(sec) * time.Second), Valid: true, AvailabilityMask: domain.FullAvailabilityMask}
	var v [domain.FeatureCount]float64
	for i := range v {
		v[i] = value
	}
	r.SetFeatures(v)
	return r
}
func TestContextMediansAndSingleNormalizationAlgebra(t *testing.T) {
	rs := []domain.TelemetryRecord{record("a01n01", 0, 1), record("a01n01", 10, 3)}
	p, err := FitContextProfile(rs, []string{"a01n01"}, fixtureProfile())
	if err != nil {
		t.Fatal(err)
	}
	if p.HostMedians["a01n01"][0] != 2 {
		t.Fatalf("median = %v", p.HostMedians["a01n01"][0])
	}
	adapted, err := p.Adapt("a01n01", rs[0].Features())
	if err != nil {
		t.Fatal(err)
	}
	want := (rs[0].Features()[0] - p.HostMedians["a01n01"][0]) / p.GlobalScale[0]
	if z := (adapted[0] - p.GlobalMedian[0]) / p.GlobalScale[0]; z != want {
		t.Fatalf("normalized result %v, want %v", z, want)
	}
	if _, err = p.Adapt("missing", rs[0].Features()); err == nil {
		t.Fatal("unknown host accepted")
	}
}
func TestD1OnlyAndFiniteValidation(t *testing.T) {
	r := record("a01n01", 0, 1)
	r.Timestamp = analysis.NIRWindows()[1].Start
	if _, err := FitContextProfile([]domain.TelemetryRecord{r}, []string{"a01n01"}, fixtureProfile()); err == nil {
		t.Fatal("D2 record accepted")
	}
	r = record("a01n01", 0, math.NaN())
	if _, err := FitContextProfile([]domain.TelemetryRecord{r}, []string{"a01n01"}, fixtureProfile()); err == nil {
		t.Fatal("nonfinite F18 accepted")
	}
}

func TestSeedDeterminismAndContextualForestJSONRoundTrip(t *testing.T) {
	rs := []domain.TelemetryRecord{record("a01n01", 0, 1), record("a01n01", 10, 2), record("a01n01", 20, 3), record("a01n01", 30, 4)}
	p, err := FitContextProfile(rs, []string{"a01n01"}, fixtureProfile())
	if err != nil {
		t.Fatal(err)
	}
	data := func(ctx context.Context, visit func(analysis.Observation) error) error {
		for _, r := range rs {
			v, e := p.Adapt(r.Hostname, r.Features())
			if e != nil {
				return e
			}
			if e = visit(analysis.Observation{Timestamp: r.Timestamp, Features: v}); e != nil {
				return e
			}
		}
		return nil
	}
	cfg := analysis.IsolationConfig{Trees: 5, SampleSize: 4, MaxDepth: 3, Seed: 42}
	first, err := analysis.FitIsolation(context.Background(), data, fixtureProfile(), analysis.NIRWindows()[0], cfg)
	if err != nil {
		t.Fatal(err)
	}
	second, err := analysis.FitIsolation(context.Background(), data, fixtureProfile(), analysis.NIRWindows()[0], cfg)
	if err != nil {
		t.Fatal(err)
	}
	if !reflect.DeepEqual(first.Trees, second.Trees) {
		t.Fatal("same seed produced different trees")
	}
	envelope := struct {
		Context *ContextProfile           `json:"context_profile"`
		Forest  *analysis.IsolationForest `json:"forest"`
	}{p, first}
	b, err := json.Marshal(envelope)
	if err != nil {
		t.Fatal(err)
	}
	var loaded struct {
		Context *ContextProfile           `json:"context_profile"`
		Forest  *analysis.IsolationForest `json:"forest"`
	}
	if err = json.Unmarshal(b, &loaded); err != nil {
		t.Fatal(err)
	}
	if err = loaded.Context.Validate(); err != nil {
		t.Fatal(err)
	}
	if err = loaded.Forest.Validate(); err != nil {
		t.Fatal(err)
	}
	raw := rs[0].Features()
	adapted, err := loaded.Context.Adapt("a01n01", raw)
	if err != nil {
		t.Fatal(err)
	}
	score, err := loaded.Forest.Score(adapted)
	if err != nil {
		t.Fatal(err)
	}
	want, err := first.Score(adapted)
	if err != nil || score != want {
		t.Fatalf("roundtrip score %v, want %v (err %v)", score, want, err)
	}
	d3 := record("a01n01", 0, 1)
	d3.Timestamp = analysis.NIRWindows()[2].Start
	if _, err = FitContextProfile([]domain.TelemetryRecord{d3}, []string{"a01n01"}, fixtureProfile()); err == nil {
		t.Fatal("D3 record accepted")
	}
}
