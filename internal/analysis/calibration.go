package analysis

import (
	"context"
	"fmt"
	"math"
	"math/bits"
	"sort"
)

type ScoredControl struct {
	Score           float64 `json:"score"`
	ControlPositive bool    `json:"control_positive"`
}

type ConfusionMatrix struct {
	TP int64 `json:"tp"`
	FP int64 `json:"fp"`
	FN int64 `json:"fn"`
	TN int64 `json:"tn"`
}

func (c ConfusionMatrix) Validate() error {
	if c.TP < 0 || c.FP < 0 || c.FN < 0 || c.TN < 0 {
		return fmt.Errorf("confusion counts must be nonnegative")
	}
	limit := int64(math.MaxInt64 / 2)
	total := c.TP
	for _, n := range []int64{c.FP, c.FN, c.TN} {
		if n > limit-total {
			return fmt.Errorf("confusion total exceeds safe limit")
		}
		total += n
	}
	return nil
}

func (c ConfusionMatrix) Total() int64 { return c.TP + c.FP + c.FN + c.TN }

type ReferenceMetrics struct {
	Precision *float64 `json:"precision"`
	Recall    *float64 `json:"recall"`
	F1        *float64 `json:"f1"`
}

func ReferenceScores(c ConfusionMatrix) (ReferenceMetrics, error) {
	if err := c.Validate(); err != nil {
		return ReferenceMetrics{}, err
	}
	var m ReferenceMetrics
	if d := c.TP + c.FP; d != 0 {
		v := float64(c.TP) / float64(d)
		m.Precision = &v
	}
	if d := c.TP + c.FN; d != 0 {
		v := float64(c.TP) / float64(d)
		m.Recall = &v
	}
	d := 2*c.TP + c.FP + c.FN
	if d != 0 {
		v := float64(2*c.TP) / float64(d)
		m.F1 = &v
	}
	return m, nil
}

type ThresholdCalibration struct {
	Status              string           `json:"status"`
	Threshold           *float64         `json:"theta_if"`
	Observations        int              `json:"observations"`
	ControlPositives    int              `json:"control_positives"`
	Candidates          int              `json:"candidates"`
	UndefinedCandidates int              `json:"undefined_f1_candidates"`
	BestCandidates      int              `json:"maximal_f1_candidates"`
	MinScore            float64          `json:"min_score"`
	MaxScore            float64          `json:"max_score"`
	Confusion           ConfusionMatrix  `json:"confusion"`
	Metrics             ReferenceMetrics `json:"reference_metrics"`
}

// ChooseIsolationThreshold selects the maximum-F1 strict score threshold on
// the supplied control observations. Equal scores are always evaluated as one block.
func ChooseIsolationThreshold(ctx context.Context, rows []ScoredControl) (*ThresholdCalibration, error) {
	if ctx == nil || len(rows) == 0 {
		return nil, fmt.Errorf("calibration requires a context and observations")
	}
	if err := ctx.Err(); err != nil {
		return nil, err
	}
	ordered := append([]ScoredControl(nil), rows...)
	positives := 0
	for _, row := range ordered {
		if !Finite(row.Score) || row.Score <= 0 || row.Score > 1 {
			return nil, fmt.Errorf("calibration score must be finite and in (0,1]")
		}
		if row.ControlPositive {
			positives++
		}
	}
	if err := ctx.Err(); err != nil {
		return nil, err
	}
	sort.Slice(ordered, func(i, j int) bool { return ordered[i].Score < ordered[j].Score })
	if err := ctx.Err(); err != nil {
		return nil, err
	}
	cal := &ThresholdCalibration{Observations: len(ordered), ControlPositives: positives, Candidates: 0, MinScore: ordered[0].Score, MaxScore: ordered[len(ordered)-1].Score}
	cm := ConfusionMatrix{TP: int64(positives), FP: int64(len(ordered) - positives)}
	var bestNum, bestDen uint64
	for i := 0; i < len(ordered); {
		if err := ctx.Err(); err != nil {
			return nil, err
		}
		j := i + 1
		for j < len(ordered) && ordered[j].Score == ordered[i].Score {
			j++
		}
		// Strict score > theta: remove this entire equal-score block first.
		for k := i; k < j; k++ {
			if ordered[k].ControlPositive {
				cm.TP--
				cm.FN++
			} else {
				cm.FP--
				cm.TN++
			}
		}
		cal.Candidates++
		num, den := uint64(2*cm.TP), uint64(2*cm.TP+cm.FP+cm.FN)
		if den == 0 {
			cal.UndefinedCandidates++
		} else {
			cmp := 1
			if cal.BestCandidates > 0 {
				cmp = compareProducts(num, bestDen, bestNum, den)
			}
			if cmp > 0 {
				bestNum, bestDen = num, den
				cal.BestCandidates = 1
				v := ordered[i].Score
				cal.Threshold, cal.Confusion = &v, cm
			} else if cmp == 0 {
				cal.BestCandidates++
				// Ascending sweep makes this the largest threshold among tied maxima.
				v := ordered[i].Score
				cal.Threshold, cal.Confusion = &v, cm
			}
		}
		i = j
	}
	if cal.BestCandidates == 0 {
		cal.Status = "undefined_f1"
		cal.Confusion = cm
		cal.Metrics = ReferenceMetrics{}
	} else {
		cal.Status = "calibrated"
		metrics, err := ReferenceScores(cal.Confusion)
		if err != nil {
			return nil, err
		}
		cal.Metrics = metrics
	}
	if err := cal.Validate(); err != nil {
		return nil, err
	}
	return cal, nil
}

func compareProducts(a, b, c, d uint64) int {
	hi1, lo1 := bits.Mul64(a, b)
	hi2, lo2 := bits.Mul64(c, d)
	if hi1 < hi2 || hi1 == hi2 && lo1 < lo2 {
		return -1
	}
	if hi1 > hi2 || hi1 == hi2 && lo1 > lo2 {
		return 1
	}
	return 0
}

func (c *ThresholdCalibration) Validate() error {
	if c == nil || c.Observations <= 0 || c.ControlPositives < 0 || c.ControlPositives > c.Observations || c.Candidates <= 0 || c.UndefinedCandidates < 0 || c.UndefinedCandidates > c.Candidates || c.BestCandidates < 0 || c.BestCandidates > c.Candidates-c.UndefinedCandidates || !Finite(c.MinScore) || !Finite(c.MaxScore) || c.MinScore <= 0 || c.MaxScore > 1 || c.MinScore > c.MaxScore {
		return fmt.Errorf("invalid threshold calibration metadata")
	}
	if err := c.Confusion.Validate(); err != nil {
		return err
	}
	if c.Confusion.Total() != int64(c.Observations) || c.Confusion.TP+c.Confusion.FN != int64(c.ControlPositives) {
		return fmt.Errorf("calibration confusion counts disagree with metadata")
	}
	if c.Candidates > c.Observations || c.UndefinedCandidates > 1 {
		return fmt.Errorf("invalid calibration candidate counts")
	}
	if (c.MinScore == c.MaxScore) != (c.Candidates == 1) {
		return fmt.Errorf("candidate count disagrees with score range")
	}
	if c.Status == "undefined_f1" {
		if c.ControlPositives != 0 || c.Candidates != 1 || c.UndefinedCandidates != 1 || c.BestCandidates != 0 || c.Threshold != nil || c.Confusion.TP != 0 || c.Confusion.FP != 0 || c.Confusion.FN != 0 || c.Confusion.TN != int64(c.Observations) || c.Metrics.Precision != nil || c.Metrics.Recall != nil || c.Metrics.F1 != nil {
			return fmt.Errorf("invalid undefined-F1 calibration")
		}
		return nil
	}
	if c.Status != "calibrated" || c.Threshold == nil || !Finite(*c.Threshold) || *c.Threshold < c.MinScore || *c.Threshold > c.MaxScore || c.BestCandidates < 1 || c.UndefinedCandidates != 0 && c.ControlPositives > 0 || c.UndefinedCandidates != 1 && c.ControlPositives == 0 {
		return fmt.Errorf("invalid calibrated threshold metadata")
	}
	if (*c.Threshold == c.MaxScore) != (c.Confusion.TP+c.Confusion.FP == 0) {
		return fmt.Errorf("strict threshold disagrees with predicted positives")
	}
	want, err := ReferenceScores(c.Confusion)
	if err != nil {
		return err
	}
	if !sameMetric(c.Metrics.Precision, want.Precision) || !sameMetric(c.Metrics.Recall, want.Recall) || !sameMetric(c.Metrics.F1, want.F1) || c.Metrics.F1 == nil {
		return fmt.Errorf("calibration metrics disagree with confusion counts")
	}
	return nil
}

// Label applies a validated calibrated threshold using the strict score > theta rule.
func (c *ThresholdCalibration) Label(score float64) (bool, error) {
	if err := c.Validate(); err != nil {
		return false, err
	}
	if c.Status != "calibrated" || c.Threshold == nil {
		return false, fmt.Errorf("calibration has no defined threshold")
	}
	if !Finite(score) || score <= 0 || score > 1 {
		return false, fmt.Errorf("score must be finite and in (0,1]")
	}
	return score > *c.Threshold, nil
}

func sameMetric(a, b *float64) bool {
	if a == nil || b == nil {
		return a == nil && b == nil
	}
	return Finite(*a) && *a == *b
}
