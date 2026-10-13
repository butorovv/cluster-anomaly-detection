package experiment

import (
	"context"
	"encoding/json"
	"os"
	"path/filepath"
	"reflect"
	"testing"

	"cluster-anomaly-detection/internal/analysis"
)

func TestSaveNewPreservesExistingResults(t *testing.T) {
	path := filepath.Join(t.TempDir(), "profile.json")
	if err := SaveNew(path, map[string]int{"rank": 18}); err != nil {
		t.Fatal(err)
	}
	if err := SaveNew(path, map[string]int{"rank": 0}); err == nil {
		t.Fatal("overwrote existing result")
	}
	b, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	var m map[string]int
	if err = json.Unmarshal(b, &m); err != nil || m["rank"] != 18 {
		t.Fatal(string(b), err)
	}
}

func TestLoadProfileRoundTripAndRejectsCorruption(t *testing.T) {
	data := func(ctx context.Context, visit func(analysis.Observation) error) error {
		for _, v := range []analysis.Vector{{-1}, {1}} {
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
	path := filepath.Join(t.TempDir(), "stage-a.json")
	if err := SaveNew(path, StatisticalRun{Profile: p}); err != nil {
		t.Fatal(err)
	}
	loaded, err := LoadProfile(path)
	if err != nil || !reflect.DeepEqual(p, loaded) {
		t.Fatal("profile round trip", err)
	}
	want, wantLabel, err := p.ControlLabel(analysis.Vector{3})
	if err != nil {
		t.Fatal(err)
	}
	got, gotLabel, err := loaded.ControlLabel(analysis.Vector{3})
	if err != nil || got != want || gotLabel != wantLabel {
		t.Fatal("inference changed after load", got, gotLabel, err)
	}
	for _, corrupt := range []string{"{}", "{", `{"statistical_profile":null}`} {
		if err := os.WriteFile(path, []byte(corrupt), 0600); err != nil {
			t.Fatal(err)
		}
		if _, err := LoadProfile(path); err == nil {
			t.Fatal("invalid result accepted", corrupt)
		}
	}
	p.PseudoInverse[0][0] *= 2
	b, err := json.Marshal(StatisticalRun{Profile: p})
	if err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(path, b, 0600); err != nil {
		t.Fatal(err)
	}
	if _, err := LoadProfile(path); err == nil {
		t.Fatal("corrupt finite profile accepted")
	}
}
