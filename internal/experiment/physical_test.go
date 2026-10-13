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
)

func testPhysicalProfile() *analysis.PhysicalProfile {
	r := 0.5
	return &analysis.PhysicalProfile{
		Version: "physical-v1", TrainingWindow: analysis.NIRWindows()[0], StepSeconds: 10, Config: analysis.PhysicalConfig{SVDRCond: 1e-12},
		CPU: analysis.ThermalModel{A: .9, B: .01, C: 2}, GPU: analysis.ThermalModel{A: .8, B: -.001, C: 3}, PSU: analysis.PSUModel{Beta0: 10, Beta1: 1.2},
		CPUFit: analysis.FitDiagnostics{Observations: 20, Rank: 3, Condition: 100}, GPUFit: analysis.FitDiagnostics{Observations: 60, Rank: 3, Condition: 200}, PSUFit: analysis.FitDiagnostics{Observations: 12, Rank: 2, Condition: 300},
		CPUCorrelation: analysis.Correlation{Observations: 24, R: &r, MeanPower: 10, MeanResponse: 30}, GPUCorrelation: analysis.Correlation{Observations: 72, R: &r, MeanPower: 20, MeanResponse: 40}, PSUCorrelation: analysis.Correlation{Observations: 12, R: &r, MeanPower: 140, MeanResponse: 178},
	}
}

func TestPhysicalProfilePersistenceAndSourceBinding(t *testing.T) {
	s := &Source{SHA256: "test-checksum", Hosts: []string{"a01n01"}, Groups: []string{"a01"}}
	p := testPhysicalProfile()
	path := filepath.Join(t.TempDir(), "physical.json")
	if err := SaveNew(path, PhysicalRun{Source: s, Profile: p}); err != nil {
		t.Fatal(err)
	}
	loaded, err := LoadPhysicalProfile(path, s)
	if err != nil || !reflect.DeepEqual(p, loaded) {
		t.Fatal("roundtrip", err)
	}
	v := analysis.Vector{2: 10, 3: 12, 10: 30, 11: 35, 4: 20, 12: 40}
	want, err := p.Forecasts(v)
	if err != nil {
		t.Fatal(err)
	}
	got, err := loaded.Forecasts(v)
	if err != nil || !reflect.DeepEqual(want, got) {
		t.Fatal("inference changed after loading", err)
	}
	if loaded.GPU.Stability().PhysicallyPlausible {
		t.Fatal("negative GPU slope was clamped")
	}
	other := *s
	other.SHA256 = "other"
	if _, err := LoadPhysicalProfile(path, &other); err == nil {
		t.Fatal("accepted different source")
	}
	other = *s
	other.Hosts = []string{"a01n02"}
	if _, err := LoadPhysicalProfile(path, &other); err == nil {
		t.Fatal("accepted different topology")
	}
	for _, bad := range []string{"{}", "{", `{"physical_profile":null}`} {
		if err := os.WriteFile(path, []byte(bad), 0600); err != nil {
			t.Fatal(err)
		}
		if _, err := LoadPhysicalProfile(path, s); err == nil {
			t.Fatal("accepted corrupt profile", bad)
		}
	}
	for _, mutate := range []func(*analysis.PhysicalProfile){
		func(p *analysis.PhysicalProfile) { p.Version = "physical-v2" },
		func(p *analysis.PhysicalProfile) { p.StepSeconds = 20 },
		func(p *analysis.PhysicalProfile) { p.TrainingWindow = analysis.NIRWindows()[1] },
		func(p *analysis.PhysicalProfile) { p.CPUFit.Rank = 2 },
		func(p *analysis.PhysicalProfile) { p.GPUFit.Condition = 1e13 },
		func(p *analysis.PhysicalProfile) { p.PSUFit.Observations = 13 },
		func(p *analysis.PhysicalProfile) { p.CPUCorrelation.R = new(float64); *p.CPUCorrelation.R = 1.01 },
	} {
		p := testPhysicalProfile()
		mutate(p)
		b, err := json.Marshal(PhysicalRun{Source: s, Profile: p})
		if err != nil {
			t.Fatal(err)
		}
		if err = os.WriteFile(path, b, 0600); err != nil {
			t.Fatal(err)
		}
		if _, err = LoadPhysicalProfile(path, s); err == nil {
			t.Fatal("accepted invalid metadata")
		}
	}
	p.CPU.A = math.NaN()
	if p.Validate() == nil {
		t.Fatal("accepted nonfinite coefficient")
	}
}

// Runs all D2 diagnostics after loading, with exact comparison against the
// original successful run. No fitting, no D3, no additional telemetry files.
func TestRealPhysicalProfileReloadD2(t *testing.T) {
	input, profile := os.Getenv("NIR_REAL_PARQUET"), os.Getenv("NIR_REAL_PHYSICAL_PROFILE")
	if input == "" || profile == "" {
		t.Skip("NIR_REAL_PARQUET/PHYSICAL_PROFILE not set: real physical reload not executed")
	}
	s, err := OpenSource(input, filepath.Join(filepath.Dir(input), "manifest.json"))
	if err != nil {
		t.Fatal(err)
	}
	p, err := LoadPhysicalProfile(profile, s)
	if err != nil {
		t.Fatal(err)
	}
	b, err := os.ReadFile(profile)
	if err != nil {
		t.Fatal(err)
	}
	var original PhysicalRun
	if err = json.Unmarshal(b, &original); err != nil {
		t.Fatal(err)
	}
	before, err := json.Marshal(p)
	if err != nil {
		t.Fatal(err)
	}
	var interval *analysis.JInterval
	if original.D2.J != nil {
		interval = &original.D2.J.Interval
	}
	e, err := EvaluatePhysical(context.Background(), s, p, analysis.NIRWindows()[1], interval)
	if err != nil {
		t.Fatal(err)
	}
	if !reflect.DeepEqual(*e, original.D2) {
		t.Fatal("D2 diagnostics changed after load")
	}
	after, err := json.Marshal(p)
	if err != nil || string(before) != string(after) {
		t.Fatal("profile changed during evaluation", err)
	}
	if e.Audit.States != 829440 || e.CPUCount != 1658304 || e.GPUCount != 4974912 || e.PSU.Count != 829440 {
		t.Fatal("real D2 count mismatch", e.Audit)
	}
	if p.CPUFit.Observations != 1658304 || p.GPUFit.Observations != 4974912 || p.PSUFit.Observations != 829440 {
		t.Fatal("real D1 count mismatch")
	}
	if _, err = EvaluatePhysical(context.Background(), s, p, analysis.NIRWindows()[2], nil); err == nil {
		t.Fatal("accepted D3 for this experiment")
	}
	t.Logf("all D2 residual summaries/MAEs/J identical after reload; CPU=%d GPU=%d PSU=%d", e.CPUCount, e.GPUCount, e.PSU.Count)
}
