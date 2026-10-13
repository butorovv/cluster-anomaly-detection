package experiment

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"os"
	"runtime"
	"slices"
	"time"

	"cluster-anomaly-detection/internal/analysis"
	"cluster-anomaly-detection/internal/modules/telemetry/domain"
)

const calibrationVersion = "isolation-calibration-v1"
const calibrationSelection = "max_defined_f1_then_largest_observed_threshold"
const calibrationComparison = "score > theta_if"

type CalibrationResources struct {
	ScanSeconds         float64 `json:"d2_scan_score_label_seconds"`
	ScoreSeconds        float64 `json:"if_score_compute_seconds"`
	ControlSeconds      float64 `json:"mahalanobis_compute_seconds"`
	SearchSeconds       float64 `json:"threshold_search_seconds"`
	ElapsedSeconds      float64 `json:"elapsed_seconds"`
	HeapAfterCollection uint64  `json:"go_heap_after_collection_bytes"`
	HeapAfterSearch     uint64  `json:"go_heap_after_search_bytes"`
}

type CalibrationRun struct {
	Version              string                         `json:"version"`
	Selection            string                         `json:"selection_rule"`
	Comparison           string                         `json:"comparison"`
	Source               *Source                        `json:"source"`
	FeatureOrder         []string                       `json:"feature_order"`
	CalibrationWindow    analysis.Window                `json:"calibration_window"`
	IsolationReference   StatisticalReference           `json:"isolation_reference"`
	StatisticalReference StatisticalReference           `json:"statistical_reference"`
	MahalanobisThreshold float64                        `json:"mahalanobis_d1_threshold"`
	Audit                Audit                          `json:"d2_audit"`
	Calibration          *analysis.ThresholdCalibration `json:"calibration"`
	IFFirings            int64                          `json:"if_firings"`
	Resources            CalibrationResources           `json:"resources"`
}

func calibrationModels(s *Source, isolationPath, statisticalPath string) (*analysis.IsolationForest, *analysis.StatisticalProfile, StatisticalReference, StatisticalReference, error) {
	var ifRef, statRef StatisticalReference
	p, statRef, err := isolationNormalizer(statisticalPath, s)
	if err != nil {
		return nil, nil, ifRef, statRef, err
	}
	r, err := LoadIsolationProfile(isolationPath, s, statisticalPath)
	if err != nil {
		return nil, nil, ifRef, statRef, err
	}
	b, err := os.ReadFile(isolationPath)
	if err != nil {
		return nil, nil, ifRef, statRef, err
	}
	h := sha256.Sum256(b)
	ifRef = StatisticalReference{Path: isolationPath, SHA256: hex.EncodeToString(h[:]), Version: r.Profile.Version}
	return r.Profile, p, ifRef, statRef, nil
}

func completeCalibrationD2(a Audit) error {
	if a.Window != analysis.NIRWindows()[1] || a.States != 829440 || a.Timestamps != 2880 || a.Hosts != 288 || a.MinimumStatesPerTimestamp != 288 || a.Valid < 0 || a.Valid > a.States {
		return fmt.Errorf("incomplete D2 node/time grid: %+v", a)
	}
	return nil
}

// CalibrateIsolationD2 only loads D1 models. Its single D2 pass stores scalar
// score/control pairs, never the full F18 dataset, and never visits D3.
func CalibrateIsolationD2(ctx context.Context, s *Source, isolationPath, statisticalPath string, progress func(string)) (*CalibrationRun, error) {
	if s == nil || ctx == nil {
		return nil, fmt.Errorf("missing calibration source/context")
	}
	if err := ctx.Err(); err != nil {
		return nil, err
	}
	start := time.Now()
	f, p, ifRef, statRef, err := calibrationModels(s, isolationPath, statisticalPath)
	if err != nil {
		return nil, err
	}
	r := &CalibrationRun{Version: calibrationVersion, Selection: calibrationSelection, Comparison: calibrationComparison, Source: s, FeatureOrder: append([]string(nil), domain.FeatureNames[:]...), CalibrationWindow: analysis.NIRWindows()[1], IsolationReference: ifRef, StatisticalReference: statRef, MahalanobisThreshold: p.Threshold}
	notify := func(msg string) {
		if progress != nil {
			progress(msg)
		}
	}
	notify("D2: loaded frozen D1 models; computing IF scores and Mahalanobis control labels")
	rows := make([]analysis.ScoredControl, 0, 829440)
	var scoreTime, controlTime time.Duration
	t := time.Now()
	r.Audit, err = s.Scan(ctx, analysis.NIRWindows()[1], func(v domain.TelemetryRecord) error {
		if !v.Valid {
			return nil
		}
		t := time.Now()
		score, err := f.Score(v.Features())
		scoreTime += time.Since(t)
		if err != nil {
			return err
		}
		t = time.Now()
		_, control, err := p.ControlLabel(v.Features())
		controlTime += time.Since(t)
		if err != nil {
			return err
		}
		rows = append(rows, analysis.ScoredControl{Score: score, ControlPositive: control})
		return nil
	})
	r.Resources.ScanSeconds = time.Since(t).Seconds()
	r.Resources.ScoreSeconds = scoreTime.Seconds()
	r.Resources.ControlSeconds = controlTime.Seconds()
	if err != nil {
		return nil, err
	}
	if err = completeCalibrationD2(r.Audit); err != nil {
		return nil, err
	}
	var mem runtime.MemStats
	runtime.ReadMemStats(&mem)
	r.Resources.HeapAfterCollection = mem.HeapAlloc
	notify("D2: sorting observed scores and sweeping equal-score blocks for maximum defined F1")
	t = time.Now()
	r.Calibration, err = analysis.ChooseIsolationThreshold(ctx, rows)
	r.Resources.SearchSeconds = time.Since(t).Seconds()
	if err != nil {
		return nil, err
	}
	if r.Calibration.Observations != r.Audit.Valid {
		return nil, fmt.Errorf("D2 calibration observation count mismatch")
	}
	r.IFFirings = r.Calibration.Confusion.TP + r.Calibration.Confusion.FP
	runtime.ReadMemStats(&mem)
	r.Resources.HeapAfterSearch = mem.HeapAlloc
	r.Resources.ElapsedSeconds = time.Since(start).Seconds()
	return r, nil
}

func (r *CalibrationRun) validate() error {
	if r == nil || r.Version != calibrationVersion || r.Selection != calibrationSelection || r.Comparison != calibrationComparison || r.CalibrationWindow != analysis.NIRWindows()[1] || !slices.Equal(r.FeatureOrder, domain.FeatureNames[:]) || !analysis.Finite(r.MahalanobisThreshold) || r.MahalanobisThreshold < 0 {
		return fmt.Errorf("invalid isolation calibration metadata")
	}
	if err := completeCalibrationD2(r.Audit); err != nil {
		return err
	}
	if err := r.Calibration.Validate(); err != nil {
		return err
	}
	if r.Audit.Valid != r.Calibration.Observations || r.IFFirings != r.Calibration.Confusion.TP+r.Calibration.Confusion.FP {
		return fmt.Errorf("calibration audit/firing count mismatch")
	}
	return nil
}

// LoadIsolationCalibration binds a frozen threshold to the actual immutable
// forest, statistical profile, dataset and F18. No threshold search takes place.
func LoadIsolationCalibration(path string, s *Source, isolationPath, statisticalPath string) (*CalibrationRun, error) {
	b, err := os.ReadFile(path)
	if err != nil {
		return nil, err
	}
	var r CalibrationRun
	if err = json.Unmarshal(b, &r); err != nil {
		return nil, err
	}
	if err = r.validate(); err != nil {
		return nil, err
	}
	if !sameIsolationSource(s, r.Source) {
		return nil, fmt.Errorf("calibration source/topology mismatch")
	}
	_, p, ifRef, statRef, err := calibrationModels(s, isolationPath, statisticalPath)
	if err != nil {
		return nil, err
	}
	if ifRef.SHA256 != r.IsolationReference.SHA256 || ifRef.Version != r.IsolationReference.Version || statRef.SHA256 != r.StatisticalReference.SHA256 || statRef.Version != r.StatisticalReference.Version || p.Threshold != r.MahalanobisThreshold {
		return nil, fmt.Errorf("calibration D1 model identity mismatch")
	}
	return &r, nil
}

type CalibrationEvaluation struct {
	Audit          Audit                     `json:"d2_audit"`
	Confusion      analysis.ConfusionMatrix  `json:"confusion"`
	Metrics        analysis.ReferenceMetrics `json:"reference_metrics"`
	IFFirings      int64                     `json:"if_firings"`
	ElapsedSeconds float64                   `json:"elapsed_seconds"`
}

// EvaluateIsolationCalibrationD2 reapplies a saved threshold on D2 without
// calibration or model fitting. It is intentionally not a D3 evaluation tool.
func EvaluateIsolationCalibrationD2(ctx context.Context, s *Source, isolationPath, statisticalPath string, r *CalibrationRun) (*CalibrationEvaluation, error) {
	if ctx == nil || s == nil {
		return nil, fmt.Errorf("missing evaluation source/context")
	}
	if err := r.validate(); err != nil {
		return nil, err
	}
	if !sameIsolationSource(s, r.Source) {
		return nil, fmt.Errorf("calibration source/topology mismatch")
	}
	f, p, ifRef, statRef, err := calibrationModels(s, isolationPath, statisticalPath)
	if err != nil {
		return nil, err
	}
	if ifRef.SHA256 != r.IsolationReference.SHA256 || ifRef.Version != r.IsolationReference.Version || statRef.SHA256 != r.StatisticalReference.SHA256 || statRef.Version != r.StatisticalReference.Version || p.Threshold != r.MahalanobisThreshold {
		return nil, fmt.Errorf("calibration D1 model identity mismatch")
	}
	if r.Calibration.Threshold == nil {
		return nil, fmt.Errorf("undefined F1 calibration has no applicable threshold")
	}
	theta := *r.Calibration.Threshold
	start := time.Now()
	e := &CalibrationEvaluation{}
	e.Audit, err = s.Scan(ctx, analysis.NIRWindows()[1], func(v domain.TelemetryRecord) error {
		if !v.Valid {
			return nil
		}
		score, err := f.Score(v.Features())
		if err != nil {
			return err
		}
		_, control, err := p.ControlLabel(v.Features())
		if err != nil {
			return err
		}
		positive := score > theta
		switch {
		case positive && control:
			e.Confusion.TP++
		case positive:
			e.Confusion.FP++
		case control:
			e.Confusion.FN++
		default:
			e.Confusion.TN++
		}
		return nil
	})
	if err != nil {
		return nil, err
	}
	if err = completeCalibrationD2(e.Audit); err != nil {
		return nil, err
	}
	e.Metrics, err = analysis.ReferenceScores(e.Confusion)
	if err != nil {
		return nil, err
	}
	e.IFFirings = e.Confusion.TP + e.Confusion.FP
	e.ElapsedSeconds = time.Since(start).Seconds()
	return e, nil
}
