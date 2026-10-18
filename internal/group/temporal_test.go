package group

import (
	"testing"
	"time"
)

func temporalRaw(tick time.Time, r, y, b State) Raw {
	return Raw{Timestamp: tick, Group: "a01", R: RResult{Criterion: Criterion{State: r}}, Y: YResult{Criterion: Criterion{State: y}}, B: Criterion{State: b}}
}

func TestEngineDeltaPairAndUnknownBreak(t *testing.T) {
	start := time.Date(2022, 1, 1, 0, 0, 0, 0, time.UTC)
	for _, tc := range []struct {
		delta        int
		wantPositive bool
	}{{0, false}, {10, true}} {
		e, err := NewEngine("cfg", "a01", tc.delta, start)
		if err != nil {
			t.Fatal(err)
		}
		if _, _, err = e.Step(temporalRaw(start, Positive, Unknown, Negative)); err != nil {
			t.Fatal(err)
		}
		tr, events, err := e.Step(temporalRaw(start.Add(10*time.Second), Negative, Unknown, Positive))
		if err != nil {
			t.Fatal(err)
		}
		if (tr.Candidate == Positive) != tc.wantPositive {
			t.Fatalf("delta=%d candidate=%s", tc.delta, tr.Candidate)
		}
		if tc.wantPositive && (tr.Mode != "preliminary" || !tr.CriteriaIncomplete || tr.HardwareConfirmation != "insufficient_criteria" || len(events) != 0) {
			t.Fatalf("Y-unknown agreement should remain preliminary: %+v events=%v", tr, events)
		}
	}
	e, _ := NewEngine("cfg", "a01", 10, start)
	e.Step(temporalRaw(start, Positive, Unknown, Negative))
	tr, _, err := e.Step(temporalRaw(start.Add(10*time.Second), Unknown, Unknown, Positive))
	if err != nil {
		t.Fatal(err)
	}
	if tr.Candidate != Unknown {
		t.Fatalf("unknown must break old occurrence: %+v", tr)
	}
	tr, _, err = e.Step(temporalRaw(start.Add(20*time.Second), Positive, Unknown, Positive))
	if err != nil {
		t.Fatal(err)
	}
	if tr.Candidate != Positive {
		t.Fatalf("fresh positives should recover after unknown: %+v", tr)
	}
}

func TestEngineRejectsInvalidDeltaAndOrdering(t *testing.T) {
	start := time.Date(2022, 1, 1, 0, 0, 0, 0, time.UTC)
	if _, err := NewEngine("cfg", "a01", 11, start); err == nil {
		t.Fatal("unsupported delta accepted")
	}
	e, _ := NewEngine("cfg", "a01", 0, start)
	if _, _, err := e.Step(temporalRaw(start, Negative, Negative, Negative)); err != nil {
		t.Fatal(err)
	}
	if _, _, err := e.Step(temporalRaw(start, Negative, Negative, Negative)); err == nil {
		t.Fatal("duplicate tick accepted")
	}
}

func TestLongEventsCloseCensorIDsAndWitnessUnion(t *testing.T) {
	start := time.Date(2022, 1, 18, 8, 0, 0, 0, time.UTC)
	e, _ := NewEngine("cfg", "a01", 0, start)
	for i := 0; i < 1000; i++ {
		r := temporalRaw(start.Add(time.Duration(i)*10*time.Second), Positive, Unknown, Positive)
		r.R.Pair = []Witness{{Hostname: fmtHost(i % 18), ZeroMAD: i == 0}}
		r.IF = Support{Available: 18, Anomalous: i % 2}
		tr, es, err := e.Step(r)
		if err != nil || len(es) != 0 || tr.Candidate != Positive {
			t.Fatal(i, tr, es, err)
		}
	}
	_, es, err := e.Step(temporalRaw(start.Add(10000*time.Second), Negative, Unknown, Positive))
	if err != nil || len(es) != 1 {
		t.Fatal(es, err)
	}
	v := es[0]
	if v.PositiveTicks != 1000 || v.DurationSeconds != 10000 || v.CensoredMissing || v.Closed != start.Add(10000*time.Second) || v.LastPositive != start.Add(9990*time.Second) || len(v.WitnessHosts) != 18 || v.IFSupportedTicks != 500 || v.ZeroMADPairTicks != 1 {
		t.Fatalf("bad summary %+v", v)
	}
	e.Step(temporalRaw(start.Add(10010*time.Second), Positive, Unknown, Positive))
	es, err = e.Flush(start.Add(10020 * time.Second))
	if err != nil || len(es) != 1 || es[0].ID == v.ID || !es[0].CensoredWindow {
		t.Fatal(es, err)
	}
}

func TestTTLBoundariesMissingGapsAndPairDelay(t *testing.T) {
	start := time.Date(2022, 1, 18, 8, 0, 0, 0, time.UTC)
	e, _ := NewEngine("cfg", "a01", 10, start)
	r := temporalRaw(start, Positive, Unknown, Negative)
	r.R.Pair = []Witness{{Hostname: "a01n01", ZeroMAD: true}, {Hostname: "a01n02"}}
	e.Step(r)
	tr, _, err := e.Step(temporalRaw(start.Add(10*time.Second), Negative, Unknown, Positive))
	if err != nil || tr.Candidate != Positive || tr.FirstEvidence == nil || *tr.FirstEvidence != start {
		t.Fatal(tr, err)
	}
	_, es, err := e.Step(temporalRaw(start.Add(20*time.Second), Negative, Unknown, Negative))
	if err != nil || len(es) != 1 || es[0].DelaySeconds != 10 || es[0].ZeroMADPairTicks != 1 || len(es[0].WitnessHosts) != 2 {
		t.Fatal(es, err)
	}
	e, _ = NewEngine("cfg", "a01", 60, start)
	e.Step(temporalRaw(start, Positive, Unknown, Positive))
	tr, es, err = e.Step(temporalRaw(start.Add(20*time.Second), Negative, Unknown, Positive))
	if err != nil || len(es) != 1 || !es[0].CensoredMissing || es[0].Closed != start.Add(10*time.Second) || tr.Candidate != Unknown {
		t.Fatal(tr, es, err)
	}
}

func TestModeTransitionAndUnknownCloses(t *testing.T) {
	start := time.Date(2022, 1, 18, 8, 0, 0, 0, time.UTC)
	e, _ := NewEngine("cfg", "a01", 0, start)
	tr, _, _ := e.Step(temporalRaw(start, Positive, Negative, Positive))
	if tr.Mode != "full" || tr.Candidate != Positive {
		t.Fatal(tr)
	}
	tr, es, err := e.Step(temporalRaw(start.Add(10*time.Second), Positive, Unknown, Positive))
	if err != nil || len(es) != 1 || tr.Mode != "preliminary" {
		t.Fatal(tr, es, err)
	}
	_, es, err = e.Step(temporalRaw(start.Add(20*time.Second), Unknown, Unknown, Positive))
	if err != nil || len(es) != 1 || !es[0].CensoredMissing {
		t.Fatal(es, err)
	}
}

func TestFullYBEventRetainsDistinctHardwareHosts(t *testing.T) {
	start := time.Date(2022, 1, 18, 8, 0, 0, 0, time.UTC)
	e, _ := NewEngine("cfg", "a01", 0, start)
	r := temporalRaw(start, Negative, Positive, Positive)
	r.Y.Hosts = map[string]State{"a01n03": Positive, "a01n04": Positive}
	tr, _, err := e.Step(r)
	if err != nil || tr.Candidate != Positive || tr.Mode != "full" || tr.CriteriaIncomplete {
		t.Fatal(tr, err)
	}
	es, err := e.Flush(start.Add(10 * time.Second))
	if err != nil || len(es) != 1 || len(es[0].WitnessHosts) != 2 || es[0].HardwareConfirmation != "criteria_available" {
		t.Fatal(es, err)
	}
}
