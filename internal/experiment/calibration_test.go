package experiment

import (
	"context"
	"encoding/json"
	"os"
	"path/filepath"
	"reflect"
	"testing"

	"cluster-anomaly-detection/internal/analysis"
	"cluster-anomaly-detection/internal/modules/telemetry/domain"
)

func calibrationFixture(t *testing.T) (*Source, string, string, *CalibrationRun) {
	t.Helper()
	s, stat, forest := isolationFixture(t)
	ifPath := filepath.Join(t.TempDir(), "forest.json")
	if err := SaveNew(ifPath, forest); err != nil {
		t.Fatal(err)
	}
	_, p, ifRef, statRef, err := calibrationModels(s, ifPath, stat)
	if err != nil {
		t.Fatal(err)
	}
	c, err := analysis.ChooseIsolationThreshold(context.Background(), []analysis.ScoredControl{{Score: .1}, {Score: .5, ControlPositive: true}, {Score: .8, ControlPositive: true}, {Score: .9}})
	if err != nil {
		t.Fatal(err)
	}
	a := Audit{Window: analysis.NIRWindows()[1], States: 829440, Valid: 4, Timestamps: 2880, Hosts: 288, MinimumStatesPerTimestamp: 288}
	r := &CalibrationRun{Version: calibrationVersion, Selection: calibrationSelection, Comparison: calibrationComparison, Source: s, FeatureOrder: append([]string(nil), domain.FeatureNames[:]...), CalibrationWindow: analysis.NIRWindows()[1], IsolationReference: ifRef, StatisticalReference: statRef, MahalanobisThreshold: p.Threshold, Audit: a, Calibration: c, IFFirings: c.Confusion.TP + c.Confusion.FP}
	return s, stat, ifPath, r
}

func TestCalibrationPersistenceBindingAndFrozenThreshold(t *testing.T) {
	s, stat, forest, r := calibrationFixture(t)
	path := filepath.Join(t.TempDir(), "calibration.json")
	if err := SaveNew(path, r); err != nil {
		t.Fatal(err)
	}
	loaded, err := LoadIsolationCalibration(path, s, forest, stat)
	if err != nil || !reflect.DeepEqual(loaded, r) {
		t.Fatal("round trip", err)
	}
	for _, score := range []float64{.1, .5, .9} {
		want, err := r.Calibration.Label(score)
		if err != nil {
			t.Fatal(err)
		}
		got, err := loaded.Calibration.Label(score)
		if err != nil || got != want {
			t.Fatal("frozen classification changed", err)
		}
	}
	if err = SaveNew(path, r); err == nil {
		t.Fatal("overwrote existing calibration")
	}
	for _, mutate := range []func(*Source){func(s *Source) { s.SHA256 = "other" }, func(s *Source) { s.Hosts = []string{"a01n02"} }, func(s *Source) { s.Groups = []string{"a02"} }, func(s *Source) { s.AssumedTimezone = "other" }, func(s *Source) { s.TimezoneVerified = true }} {
		other := *s
		mutate(&other)
		if _, err = LoadIsolationCalibration(path, &other, forest, stat); err == nil {
			t.Fatal("different source accepted")
		}
	}
	for _, input := range []string{forest, stat} {
		b, err := os.ReadFile(input)
		if err != nil {
			t.Fatal(err)
		}
		copyPath := filepath.Join(t.TempDir(), "copy.json")
		if err = os.WriteFile(copyPath, b, 0600); err != nil {
			t.Fatal(err)
		}
		ifCopy, statCopy := forest, stat
		if input == forest {
			ifCopy = copyPath
		} else {
			statCopy = copyPath
		}
		if _, err = LoadIsolationCalibration(path, s, ifCopy, statCopy); err != nil {
			t.Fatal("identical model copied to new path rejected", err)
		}
		if err = os.WriteFile(copyPath, append(b, ' '), 0600); err != nil {
			t.Fatal(err)
		}
		if _, err = LoadIsolationCalibration(path, s, ifCopy, statCopy); err == nil {
			t.Fatal("different model file checksum accepted")
		}
	}
}

func TestCalibrationLoadRejectsInvalidMetadata(t *testing.T) {
	s, stat, forest, r := calibrationFixture(t)
	b, err := json.Marshal(r)
	if err != nil {
		t.Fatal(err)
	}
	path := filepath.Join(t.TempDir(), "calibration.json")
	for _, mutate := range []func(*CalibrationRun){
		func(r *CalibrationRun) { r.Version = "unknown" }, func(r *CalibrationRun) { r.Selection = "smallest_threshold" }, func(r *CalibrationRun) { r.Comparison = "score >= theta_if" },
		func(r *CalibrationRun) { r.CalibrationWindow = analysis.NIRWindows()[2] }, func(r *CalibrationRun) { r.Audit.Window = analysis.NIRWindows()[2] }, func(r *CalibrationRun) { r.Audit.States-- }, func(r *CalibrationRun) { r.Audit.Valid-- }, func(r *CalibrationRun) { r.IFFirings++ },
		func(r *CalibrationRun) { r.IsolationReference.SHA256 = "other" }, func(r *CalibrationRun) { r.IsolationReference.Version = "other" }, func(r *CalibrationRun) { r.StatisticalReference.SHA256 = "other" }, func(r *CalibrationRun) { r.StatisticalReference.Version = "other" }, func(r *CalibrationRun) { r.MahalanobisThreshold++ },
		func(r *CalibrationRun) { r.FeatureOrder[0], r.FeatureOrder[1] = r.FeatureOrder[1], r.FeatureOrder[0] }, func(r *CalibrationRun) { r.Calibration = nil }, func(r *CalibrationRun) { r.Source = nil }, func(r *CalibrationRun) { r.Calibration.Threshold = nil }, func(r *CalibrationRun) { r.Calibration.Metrics.F1 = new(float64) },
	} {
		var other CalibrationRun
		if err = json.Unmarshal(b, &other); err != nil {
			t.Fatal(err)
		}
		mutate(&other)
		out, err := json.Marshal(other)
		if err != nil {
			t.Fatal(err)
		}
		if err = os.WriteFile(path, out, 0600); err != nil {
			t.Fatal(err)
		}
		if _, err = LoadIsolationCalibration(path, s, forest, stat); err == nil {
			t.Fatal("invalid saved calibration accepted", other)
		}
	}
	for _, bad := range []string{"{}", "{", `{"calibration":null}`} {
		if err = os.WriteFile(path, []byte(bad), 0600); err != nil {
			t.Fatal(err)
		}
		if _, err = LoadIsolationCalibration(path, s, forest, stat); err == nil {
			t.Fatal("invalid JSON accepted")
		}
	}
}

func TestUndefinedCalibrationPersistsButCannotBeApplied(t *testing.T) {
	s, stat, forest, r := calibrationFixture(t)
	c, err := analysis.ChooseIsolationThreshold(context.Background(), []analysis.ScoredControl{{Score: .5}, {Score: .5}, {Score: .5}, {Score: .5}})
	if err != nil {
		t.Fatal(err)
	}
	r.Calibration = c
	r.IFFirings = 0
	path := filepath.Join(t.TempDir(), "undefined.json")
	if err = SaveNew(path, r); err != nil {
		t.Fatal(err)
	}
	loaded, err := LoadIsolationCalibration(path, s, forest, stat)
	if err != nil {
		t.Fatal(err)
	}
	if loaded.Calibration.Status != "undefined_f1" || loaded.Calibration.Threshold != nil {
		t.Fatal(loaded)
	}
	if _, err = EvaluateIsolationCalibrationD2(context.Background(), s, forest, stat, loaded); err == nil {
		t.Fatal("undefined calibration applied")
	}
}

func TestCalibrationEarlyInputFailures(t *testing.T) {
	if _, err := CalibrateIsolationD2(context.Background(), nil, "missing", "missing", nil); err == nil {
		t.Fatal("nil source accepted")
	}
	ctx, cancel := context.WithCancel(context.Background())
	cancel()
	if _, err := CalibrateIsolationD2(ctx, &Source{}, "missing", "missing", nil); err != context.Canceled {
		t.Fatal("did not stop before loading models", err)
	}
	if _, err := EvaluateIsolationCalibrationD2(context.Background(), &Source{}, "missing", "missing", nil); err == nil {
		t.Fatal("nil calibration accepted")
	}
}

func TestRealIsolationCalibrationReloadD2(t *testing.T) {
	input, stat, forest, path := os.Getenv("NIR_REAL_PARQUET"), os.Getenv("NIR_REAL_PROFILE"), os.Getenv("NIR_REAL_ISOLATION_PROFILE"), os.Getenv("NIR_REAL_CALIBRATION")
	if input == "" || stat == "" || forest == "" || path == "" {
		t.Skip("real D2 calibration inputs not configured")
	}
	s, err := OpenSource(input, filepath.Join(filepath.Dir(input), "manifest.json"))
	if err != nil {
		t.Fatal(err)
	}
	r, err := LoadIsolationCalibration(path, s, forest, stat)
	if err != nil {
		t.Fatal(err)
	}
	before, err := json.Marshal(r)
	if err != nil {
		t.Fatal(err)
	}
	e, err := EvaluateIsolationCalibrationD2(context.Background(), s, forest, stat, r)
	if err != nil {
		t.Fatal(err)
	}
	after, err := json.Marshal(r)
	if err != nil {
		t.Fatal(err)
	}
	if e.Audit != r.Audit || e.Confusion != r.Calibration.Confusion || e.IFFirings != r.IFFirings || !reflect.DeepEqual(e.Metrics, r.Calibration.Metrics) || string(before) != string(after) {
		t.Fatal("D2 results/calibration changed after loading")
	}
	t.Logf("theta=%.16g count=%d confusion=%+v IF=%d F1=%.16g", *r.Calibration.Threshold, e.Audit.Valid, e.Confusion, e.IFFirings, *e.Metrics.F1)
}
