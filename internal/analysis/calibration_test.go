package analysis

import (
	"context"
	"encoding/json"
	"math"
	"math/big"
	"math/rand"
	"reflect"
	"testing"
)

func TestReferenceScoresAndUndefinedMetrics(t *testing.T) {
	m, err := ReferenceScores(ConfusionMatrix{TP: 2, FP: 1, FN: 2, TN: 5})
	if err != nil {
		t.Fatal(err)
	}
	closeTo(t, *m.Precision, 2.0/3, 0)
	closeTo(t, *m.Recall, .5, 0)
	closeTo(t, *m.F1, 4.0/7, 0)
	for _, tc := range []struct {
		c       ConfusionMatrix
		p, r, f *float64
	}{
		{ConfusionMatrix{TN: 5}, nil, nil, nil},
		{ConfusionMatrix{FN: 2, TN: 3}, nil, floatPointer(0), floatPointer(0)},
		{ConfusionMatrix{FP: 2, TN: 3}, floatPointer(0), nil, floatPointer(0)},
	} {
		got, err := ReferenceScores(tc.c)
		if err != nil || !reflect.DeepEqual(got, ReferenceMetrics{tc.p, tc.r, tc.f}) {
			t.Fatal(got, err)
		}
	}
	for _, c := range []ConfusionMatrix{{TP: -1}, {FP: -1}, {FN: -1}, {TN: -1}, {TP: math.MaxInt64}, {TP: math.MaxInt64 / 2, TN: 1}} {
		if _, err := ReferenceScores(c); err == nil {
			t.Fatal("invalid counts accepted", c)
		}
	}
	if _, err := ReferenceScores(ConfusionMatrix{TP: math.MaxInt64 / 2}); err != nil {
		t.Fatal(err)
	}
}

func floatPointer(v float64) *float64 { return &v }

func TestCalibrationStrictEqualityAndHighestThresholdTie(t *testing.T) {
	rows := []ScoredControl{{.1, false}, {.2, true}, {.3, false}, {.4, false}, {.5, true}}
	c, err := ChooseIsolationThreshold(context.Background(), rows)
	if err != nil {
		t.Fatal(err)
	}
	if *c.Threshold != .4 || c.BestCandidates != 2 || c.Confusion != (ConfusionMatrix{TP: 1, FN: 1, TN: 3}) {
		t.Fatal(c)
	}
	for _, tc := range []struct {
		score float64
		want  bool
	}{{.4, false}, {math.Nextafter(.4, 1), true}, {.1, false}, {.5, true}} {
		got, err := c.Label(tc.score)
		if err != nil || got != tc.want {
			t.Fatal(tc, got, err)
		}
	}
	for _, v := range []float64{math.NaN(), math.Inf(1), 0, -1, 1.01} {
		if _, err := c.Label(v); err == nil {
			t.Fatal("invalid inference score accepted")
		}
	}
	// The conflicting labels in the equal-score block cannot be separated by a
	// strict observed threshold, regardless of ordering inside that block.
	for _, rows := range [][]ScoredControl{{{.1, false}, {.5, true}, {.5, false}}, {{.5, false}, {.1, false}, {.5, true}}} {
		c, err = ChooseIsolationThreshold(context.Background(), rows)
		if err != nil {
			t.Fatal(err)
		}
		if *c.Threshold != .1 || c.Candidates != 2 || c.Confusion != (ConfusionMatrix{TP: 1, FP: 1, TN: 1}) {
			t.Fatal(c)
		}
	}
}

func TestCalibrationAllEqualAndNoControlPositives(t *testing.T) {
	for _, tc := range []struct {
		rows            []ScoredControl
		threshold       *float64
		status          string
		undefined, best int
	}{
		{[]ScoredControl{{.5, true}, {.5, false}}, floatPointer(.5), "calibrated", 0, 1},
		{[]ScoredControl{{.5, false}, {.5, false}}, nil, "undefined_f1", 1, 0},
		{[]ScoredControl{{.1, false}, {.5, false}, {.9, false}}, floatPointer(.5), "calibrated", 1, 2},
		{[]ScoredControl{{.5, true}}, floatPointer(.5), "calibrated", 0, 1},
		{[]ScoredControl{{.5, false}}, nil, "undefined_f1", 1, 0},
	} {
		c, err := ChooseIsolationThreshold(context.Background(), tc.rows)
		if err != nil {
			t.Fatal(err)
		}
		if !reflect.DeepEqual(c.Threshold, tc.threshold) || c.Status != tc.status || c.UndefinedCandidates != tc.undefined || c.BestCandidates != tc.best {
			t.Fatal(c)
		}
		if c.Threshold == nil {
			if _, err := c.Label(.7); err == nil {
				t.Fatal("undefined calibration classified a score")
			}
		}
	}
}

func TestCalibrationExactF1ComparisonBeyondFloatPrecision(t *testing.T) {
	n := uint64(1) << 60
	// n/(n+1) > (n-1)/n, even though float64 rounds both to 1.
	if compareProducts(n, n, n-1, n+1) != 1 || compareProducts(n-1, n+1, n, n) != -1 || compareProducts(n, n+1, n+1, n) != 0 {
		t.Fatal("128-bit comparison lost exact ordering")
	}
}

// Independent quadratic oracle, deliberately limited to small test inputs.
// Every observed candidate is classified from scratch with a big.Rat F1.
func bruteCalibration(rows []ScoredControl) (*float64, ConfusionMatrix, int, int, int) {
	unique := map[float64]bool{}
	for _, r := range rows {
		unique[r.Score] = true
	}
	var theta *float64
	var selected ConfusionMatrix
	var best *big.Rat
	ties, undefined := 0, 0
	for candidate := range unique {
		var c ConfusionMatrix
		for _, r := range rows {
			switch {
			case r.Score > candidate && r.ControlPositive:
				c.TP++
			case r.Score > candidate:
				c.FP++
			case r.ControlPositive:
				c.FN++
			default:
				c.TN++
			}
		}
		den := 2*c.TP + c.FP + c.FN
		if den == 0 {
			undefined++
			continue
		}
		f := big.NewRat(2*c.TP, den)
		if best == nil || f.Cmp(best) > 0 {
			best = f
			ties = 1
			theta = floatPointer(candidate)
			selected = c
		} else if f.Cmp(best) == 0 {
			ties++
			if candidate > *theta {
				theta = floatPointer(candidate)
				selected = c
			}
		}
	}
	if theta == nil {
		selected.TN = int64(len(rows))
	}
	return theta, selected, len(unique), undefined, ties
}

func TestCalibrationMatchesIndependentBruteForce(t *testing.T) {
	rng := rand.New(rand.NewSource(42))
	for trial := 0; trial < 500; trial++ {
		rows := make([]ScoredControl, 1+rng.Intn(25))
		for i := range rows {
			rows[i] = ScoredControl{float64(1+rng.Intn(10)) / 10, rng.Intn(4) == 0}
		}
		before := append([]ScoredControl(nil), rows...)
		got, err := ChooseIsolationThreshold(context.Background(), rows)
		if err != nil {
			t.Fatal(err)
		}
		theta, conf, candidates, undefined, best := bruteCalibration(rows)
		if !reflect.DeepEqual(theta, got.Threshold) || conf != got.Confusion || candidates != got.Candidates || undefined != got.UndefinedCandidates || best != got.BestCandidates {
			t.Fatalf("trial %d: got %+v oracle %v %+v", trial, got, theta, conf)
		}
		if !reflect.DeepEqual(before, rows) {
			t.Fatal("calibration reordered caller observations")
		}
	}
}

func TestCalibrationInvalidInputRoundTripAndCorruption(t *testing.T) {
	for _, rows := range [][]ScoredControl{nil, {{math.NaN(), false}}, {{math.Inf(1), true}}, {{0, false}}, {{-1, false}}, {{1.1, false}}} {
		if _, err := ChooseIsolationThreshold(context.Background(), rows); err == nil {
			t.Fatal("invalid rows accepted")
		}
	}
	ctx, cancel := context.WithCancel(context.Background())
	cancel()
	if _, err := ChooseIsolationThreshold(ctx, []ScoredControl{{.5, true}}); err == nil {
		t.Fatal("canceled context accepted")
	}
	if _, err := ChooseIsolationThreshold(nil, []ScoredControl{{.5, true}}); err == nil {
		t.Fatal("nil context accepted")
	}
	c, err := ChooseIsolationThreshold(context.Background(), []ScoredControl{{.1, false}, {.5, true}, {.9, false}})
	if err != nil {
		t.Fatal(err)
	}
	b, err := json.Marshal(c)
	if err != nil {
		t.Fatal(err)
	}
	var loaded ThresholdCalibration
	if err = json.Unmarshal(b, &loaded); err != nil {
		t.Fatal(err)
	}
	if err = loaded.Validate(); err != nil || !reflect.DeepEqual(c, &loaded) {
		t.Fatal("round trip", err)
	}
	for _, mutate := range []func(*ThresholdCalibration){
		func(c *ThresholdCalibration) { c.Threshold = nil }, func(c *ThresholdCalibration) { c.Threshold = floatPointer(.99) }, func(c *ThresholdCalibration) { c.Metrics.F1 = floatPointer(.99) }, func(c *ThresholdCalibration) { c.Metrics.Precision = nil },
		func(c *ThresholdCalibration) { c.Confusion.TP++ }, func(c *ThresholdCalibration) { c.Observations++ }, func(c *ThresholdCalibration) { c.ControlPositives++ }, func(c *ThresholdCalibration) { c.Candidates = 1 }, func(c *ThresholdCalibration) { c.BestCandidates = 0 }, func(c *ThresholdCalibration) { c.UndefinedCandidates = 1 }, func(c *ThresholdCalibration) { c.Status = "unknown" },
	} {
		var other ThresholdCalibration
		if err = json.Unmarshal(b, &other); err != nil {
			t.Fatal(err)
		}
		mutate(&other)
		if err = other.Validate(); err == nil {
			t.Fatal("corrupted calibration accepted", other)
		}
	}
}
