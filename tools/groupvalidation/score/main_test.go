package main

import (
	"fmt"
	"math"
	"strings"
	"testing"
	"time"

	"cluster-anomaly-detection/internal/analysis"
	"cluster-anomaly-detection/internal/local"
)

func fixture() (inputRow, local.Binding) {
	hosts := make([]string, 288)
	for g := 1; g <= 16; g++ {
		for n := 1; n <= 18; n++ {
			hosts[(g-1)*18+n-1] = fmt.Sprintf("a%02dn%02d", g, n)
		}
	}
	b := local.Binding{Hosts: hosts}
	t := analysis.NIRWindows()[1].Start
	r := inputRow{ID: "tick-1", Timestamp: t.Format(time.RFC3339), Group: "a01"}
	return r, b
}

func TestBuildTickValidation(t *testing.T) {
	t.Run("empty is missing", func(t *testing.T) {
		r, b := fixture()
		tick, e := buildTick(r, b)
		if e != nil {
			t.Fatal(e)
		}
		if len(tick.Records) != 0 {
			t.Fatalf("records=%d", len(tick.Records))
		}
	})
	t.Run("finite full record", func(t *testing.T) {
		r, b := fixture()
		f := make([]float64, 18)
		r.Records = []inputRecord{{Hostname: "a01n01", Features: f}}
		tick, e := buildTick(r, b)
		if e != nil {
			t.Fatal(e)
		}
		if !tick.Records["a01n01"].Valid {
			t.Fatal("record not marked complete")
		}
	})
	tests := []struct {
		name   string
		mutate func(*inputRow)
	}{
		{"wrong group", func(r *inputRow) {
			r.Group = "a02"
			r.Records = []inputRecord{{Hostname: "a01n01", Features: make([]float64, 18)}}
		}},
		{"duplicate host", func(r *inputRow) {
			x := inputRecord{Hostname: "a01n01", Features: make([]float64, 18)}
			r.Records = []inputRecord{x, x}
		}},
		{"invalid dimension", func(r *inputRow) { r.Records = []inputRecord{{Hostname: "a01n01", Features: make([]float64, 17)}} }},
		{"nonfinite", func(r *inputRow) {
			f := make([]float64, 18)
			f[3] = math.Inf(1)
			r.Records = []inputRecord{{Hostname: "a01n01", Features: f}}
		}},
		{"off grid", func(r *inputRow) { r.Timestamp = analysis.NIRWindows()[1].Start.Add(time.Second).Format(time.RFC3339) }},
		{"outside D2", func(r *inputRow) { r.Timestamp = analysis.NIRWindows()[2].Start.Format(time.RFC3339) }},
	}
	for _, tc := range tests {
		t.Run(tc.name, func(t *testing.T) {
			r, b := fixture()
			tc.mutate(&r)
			if _, e := buildTick(r, b); e == nil {
				t.Fatal("expected validation error")
			}
		})
	}
}

func TestDecodeLineRejectsTrailingJSON(t *testing.T) {
	var r inputRow
	if e := decodeLine([]byte(`{"id":"x","timestamp":"2022-01-18T08:00:00Z","group":"a01","records":[]} {}`), &r); e == nil {
		t.Fatal("expected trailing JSON error")
	}
	if e := decodeLine([]byte(`{bad`), &r); e == nil {
		t.Fatal("expected malformed JSON error")
	}
	missing := `{"id":"x","timestamp":"2022-01-18T08:00:00Z","group":"a01","records":[{"hostname":"a01n01","features":[` + strings.Repeat("1,", 17) + `null]}]}`
	if e := decodeLine([]byte(missing), &r); e == nil {
		t.Fatal("null sensor silently became a measured zero")
	}
}

func TestAcceptIDRejectsDuplicate(t *testing.T) {
	ids := map[string]bool{}
	if e := acceptID(ids, "same"); e != nil {
		t.Fatal(e)
	}
	if e := acceptID(ids, "same"); e == nil {
		t.Fatal("expected duplicate id error")
	}
}
