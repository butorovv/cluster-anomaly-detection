package analysis

import (
	"fmt"
	"math"
	"time"
)

// ResidualStats describes signed residuals, without detector thresholds.
type ResidualStats struct {
	Count    int     `json:"count"`
	Mean     float64 `json:"mean"`
	MAE      float64 `json:"mae"`
	RMSE     float64 `json:"rmse"`
	Min      float64 `json:"min"`
	Max      float64 `json:"max"`
	Variance float64 `json:"population_variance"`
}
type ResidualAccumulator struct {
	n                               int
	mean, abs, square, m2, min, max float64
}

func (s *ResidualAccumulator) Add(v float64) error {
	if !Finite(v) || !Finite(v*v) {
		return fmt.Errorf("nonfinite residual statistic")
	}
	s.n++
	if s.n == 1 || v < s.min {
		s.min = v
	}
	if s.n == 1 || v > s.max {
		s.max = v
	}
	d := v - s.mean
	s.mean += d / float64(s.n)
	s.m2 += d * (v - s.mean)
	s.abs += (math.Abs(v) - s.abs) / float64(s.n)
	s.square += (v*v - s.square) / float64(s.n)
	if !Finite(s.mean) || !Finite(s.m2) || !Finite(s.abs) || !Finite(s.square) {
		return fmt.Errorf("residual statistics overflow")
	}
	return nil
}
func (s *ResidualAccumulator) Result() ResidualStats {
	if s.n == 0 {
		return ResidualStats{}
	}
	return ResidualStats{s.n, s.mean, s.abs, math.Sqrt(s.square), s.min, s.max, s.m2 / float64(s.n)}
}

// JInterval includes both residual endpoints (RPZ 36). Start must already have
// a valid one-step prediction within the same split. No missing error is zero.
type JInterval struct {
	Hostname  string    `json:"hostname"`
	Component int       `json:"component_index"`
	Start     time.Time `json:"start_inclusive"`
	End       time.Time `json:"end_inclusive"`
}

func (i JInterval) Validate(w Window) error {
	if !w.Valid() || i.Hostname == "" || i.Component < 0 || i.Component >= 8 || !w.Contains(i.Start) || !w.Contains(i.End) || i.Start.Before(w.Start.Add(Step)) || i.End.Before(i.Start) || i.Start.Sub(w.Start)%Step != 0 || i.End.Sub(i.Start)%Step != 0 {
		return fmt.Errorf("J requires an explicit continuous component interval inside one split")
	}
	return nil
}

type JResult struct {
	Interval JInterval `json:"interval"`
	Samples  int       `json:"samples"`
	J        float64   `json:"j_celsius_seconds"`
	MAE      float64   `json:"mae_celsius"`
}
type JAccumulator struct {
	interval          JInterval
	next              time.Time
	n                 int
	sum, compensation float64
}

func NewJAccumulator(i JInterval, w Window) (*JAccumulator, error) {
	if err := i.Validate(w); err != nil {
		return nil, err
	}
	return &JAccumulator{interval: i, next: i.Start}, nil
}
func (j *JAccumulator) Add(host string, component int, timestamp time.Time, residual float64) error {
	i := j.interval
	if host != i.Hostname || component != i.Component || timestamp.Before(i.Start) || timestamp.After(i.End) {
		return nil
	}
	if !timestamp.Equal(j.next) || !Finite(residual) {
		return fmt.Errorf("J interval contains missing, duplicate or reversed residuals")
	}
	// Compensated summation for the integral, whose exact bounds come from caller.
	x := math.Abs(residual) - j.compensation
	total := j.sum + x
	j.compensation = (total - j.sum) - x
	j.sum = total
	if !Finite(j.sum) {
		return fmt.Errorf("J overflow")
	}
	j.n++
	j.next = j.next.Add(Step)
	return nil
}
func (j *JAccumulator) Result() (JResult, error) {
	if !j.next.Equal(j.interval.End.Add(Step)) || j.n == 0 {
		return JResult{}, fmt.Errorf("J interval is incomplete")
	}
	v := Step.Seconds() * j.sum
	if !Finite(v) {
		return JResult{}, fmt.Errorf("J overflow")
	}
	return JResult{j.interval, j.n, v, j.sum / float64(j.n)}, nil
}
