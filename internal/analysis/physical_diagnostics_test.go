package analysis

import (
	"math"
	"testing"
	"time"
)

func TestPearsonZeroVarianceIsUndefined(t *testing.T) {
	var p PearsonAccumulator
	for _, y := range []float64{1, 2, 3} {
		if err := p.Add(5, y); err != nil {
			t.Fatal(err)
		}
	}
	c, err := p.Result()
	if err != nil || c.Observations != 3 || c.R != nil {
		t.Fatalf("correlation=%+v err=%v", c, err)
	}
}

func TestPearsonKnownCorrelationWithLargeOffset(t *testing.T) {
	var p PearsonAccumulator
	for _, x := range []float64{1, 2, 4, 8} {
		if err := p.Add(1e9+x, 1e9-3*x); err != nil {
			t.Fatal(err)
		}
	}
	c, err := p.Result()
	if err != nil || c.R == nil || math.Abs(*c.R+1) > 1e-8 || c.Observations != 4 {
		t.Fatal(c, err)
	}
	if err := p.Add(math.NaN(), 1); err == nil {
		t.Fatal("accepted nonfinite pair")
	}
}

func TestResidualStatsPreserveSignedValues(t *testing.T) {
	var s ResidualAccumulator
	for _, x := range []float64{-2, 1, 3} {
		if err := s.Add(x); err != nil {
			t.Fatal(err)
		}
	}
	r := s.Result()
	if r.Count != 3 || !nearPhysical(r.Mean, 2.0/3) || r.MAE != 2 || !nearPhysical(r.RMSE, math.Sqrt(14.0/3)) || r.Min != -2 || r.Max != 3 {
		t.Fatalf("stats=%+v", r)
	}
}

func TestJIntervalInclusiveSumAndMean(t *testing.T) {
	w := NIRWindows()[0]
	i := JInterval{"node", 2, w.Start.Add(Step), w.Start.Add(3 * Step)}
	j, err := NewJAccumulator(i, w)
	if err != nil {
		t.Fatal(err)
	}
	for k, r := range []float64{-1, 2, -3} {
		if err := j.Add("node", 2, i.Start.Add(time.Duration(k)*Step), r); err != nil {
			t.Fatal(err)
		}
	}
	got, err := j.Result()
	if err != nil {
		t.Fatal(err)
	}
	if got.Samples != 3 || got.J != 60 || got.MAE != 2 {
		t.Fatalf("J result=%+v", got)
	}
}

func TestJRejectsInvalidIntervals(t *testing.T) {
	w := NIRWindows()
	bad := []JInterval{{"", 0, w[0].Start, w[0].Start.Add(Step)}, {"h", 8, w[0].Start, w[0].Start.Add(Step)}, {"h", 0, w[0].Start, w[0].Start}, {"h", 0, w[0].End, w[0].End}, {"h", 0, w[0].Start.Add(Step), w[0].Start.Add(2*Step + time.Second)}, {"h", 0, w[1].Start, w[1].Start.Add(Step)}}
	for _, i := range bad {
		if _, err := NewJAccumulator(i, w[0]); err == nil {
			t.Errorf("accepted interval %+v", i)
		}
	}
	// The last prediction target in D1 remains inside D1, while D2 begins at its exclusive end.
	validBoundary := JInterval{"h", 0, w[0].End.Add(-Step), w[0].End.Add(-Step)}
	if _, err := NewJAccumulator(validBoundary, w[0]); err != nil {
		t.Fatalf("rejected final in-split target: %v", err)
	}
}

func TestJRejectsGapsDuplicatesReverseForeignAndNonfinite(t *testing.T) {
	w := NIRWindows()[0]
	i := JInterval{"node", 0, w.Start.Add(Step), w.Start.Add(3 * Step)}
	type residualInput struct {
		host string
		c    int
		at   time.Time
		r    float64
	}
	tests := []struct {
		name  string
		add   []residualInput
		badAt int
	}{{"gap", []residualInput{{"node", 0, i.Start, 1}, {"node", 0, i.Start.Add(2 * Step), 1}}, 1}, {"duplicate", []residualInput{{"node", 0, i.Start, 1}, {"node", 0, i.Start, 1}}, 1}, {"reverse", []residualInput{{"node", 0, i.Start.Add(Step), 1}, {"node", 0, i.Start, 1}}, 0}, {"nonfinite", []residualInput{{"node", 0, i.Start, math.NaN()}}, 0}}
	for _, tc := range tests {
		t.Run(tc.name, func(t *testing.T) {
			j, _ := NewJAccumulator(i, w)
			for k, x := range tc.add {
				err := j.Add(x.host, x.c, x.at, x.r)
				if k == tc.badAt && err == nil {
					t.Fatal("accepted invalid residual sequence")
				}
				if k != tc.badAt && err != nil {
					t.Fatalf("valid prefix row %d: %v", k, err)
				}
			}
		})
	}
	for _, x := range []struct {
		host string
		c    int
		at   time.Time
	}{{"other", 0, i.Start}, {"node", 1, i.Start}, {"node", 0, i.Start.Add(-Step)}, {"node", 0, i.End.Add(Step)}} {
		j, _ := NewJAccumulator(i, w)
		if err := j.Add(x.host, x.c, x.at, 1); err != nil {
			t.Errorf("out-of-scope row should be ignored: %v", err)
		}
	}
	j, _ := NewJAccumulator(i, w)
	if _, err := j.Result(); err == nil {
		t.Fatal("incomplete interval must not return an estimate")
	}
}
