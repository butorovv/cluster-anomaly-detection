package main

import (
	"encoding/binary"
	"encoding/json"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"cluster-anomaly-detection/internal/analysis"
	"cluster-anomaly-detection/internal/experiment"
	"cluster-anomaly-detection/internal/modules/telemetry/domain"
	"cluster-anomaly-detection/tools/context/model"
)

func TestResearchBinaryLayoutAndExclusiveWrite(t *testing.T) {
	path := filepath.Join(t.TempDir(), "states.bin")
	w, err := newWriter(path)
	if err != nil {
		t.Fatal(err)
	}
	r := domain.TelemetryRecord{Timestamp: analysis.NIRWindows()[0].Start, Valid: true, AvailabilityMask: domain.FullAvailabilityMask}
	var features analysis.Vector
	for j := range features {
		features[j] = float64(j + 1)
	}
	r.SetFeatures(features)
	if err = w.write(row{rec: r, host: 7, distance: 123}, []float64{.1, .2, .3, .4, .5, .6}); err != nil {
		t.Fatal(err)
	}
	if _, err = w.close(); err != nil {
		t.Fatal(err)
	}
	b, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	if len(b) != 216 || binary.LittleEndian.Uint32(b[8:12]) != 7 || binary.LittleEndian.Uint32(b[12:16]) != domain.FullAvailabilityMask {
		t.Fatal("wrong binary layout")
	}
	if _, err = newWriter(path); err == nil {
		t.Fatal("overwrote existing research file")
	}
}

func TestSavedForestRoundTripRejectsBrokenContextLink(t *testing.T) {
	f := &analysis.IsolationForest{Version: "isolation-forest-v1", TrainingWindow: analysis.NIRWindows()[0], Observations: 2, EffectiveSampleSize: 2, Config: analysis.IsolationConfig{Trees: 1, SampleSize: 2, MaxDepth: 0, Seed: 42}, Trees: []*analysis.IsolationNode{{Size: 2, Feature: -1}}}
	for j := range f.Scale {
		f.Scale[j] = .0001
	}
	sourceHash, profileHash := strings.Repeat("a", 64), strings.Repeat("b", 64)
	cp := &model.ContextProfile{Version: model.Version, TrainingWindow: analysis.NIRWindows()[0], SourceSHA256: sourceHash, GlobalProfileSHA256: profileHash, Hosts: []string{"a01n01"}, HostMedians: map[string]analysis.Vector{"a01n01": {}}, GlobalScale: f.Scale}
	env := savedForest{Source: &experiment.Source{SHA256: sourceHash, Hosts: cp.Hosts}, StatisticalReference: experiment.StatisticalReference{SHA256: profileHash, Version: "statistical-v1"}, Context: cp, Forest: f}
	b, err := json.Marshal(env)
	if err != nil {
		t.Fatal(err)
	}
	var loaded savedForest
	if err = json.Unmarshal(b, &loaded); err != nil {
		t.Fatal(err)
	}
	if err = loaded.Validate(); err != nil {
		t.Fatal(err)
	}
	loaded.Context.SourceSHA256 = strings.Repeat("c", 64)
	if loaded.Validate() == nil {
		t.Fatal("accepted wrong prepared source")
	}
	loaded.Context.SourceSHA256 = sourceHash
	loaded.Context.GlobalScale[0] = 1
	if loaded.Validate() == nil {
		t.Fatal("accepted double/different scaling")
	}
	loaded.Context.GlobalScale = f.Scale
	loaded.Source.Hosts = []string{"a01n02"}
	if loaded.Validate() == nil {
		t.Fatal("accepted mismatched host order")
	}
}
