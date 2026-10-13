package experiment

import (
	"context"
	"encoding/json"
	"fmt"
	"os"

	"cluster-anomaly-detection/internal/analysis"
	"cluster-anomaly-detection/internal/modules/telemetry/domain"
)

type StatisticalEvaluation struct {
	Audit           Audit   `json:"audit"`
	ControlPositive int     `json:"control_positive"`
	DistanceMin     float64 `json:"distance_squared_min"`
	DistanceMax     float64 `json:"distance_squared_max"`
	DistanceMean    float64 `json:"distance_squared_mean"`
}

type StatisticalRun struct {
	Source  *Source                      `json:"source"`
	Profile *analysis.StatisticalProfile `json:"statistical_profile"`
	Windows [3]StatisticalEvaluation     `json:"windows"`
}

// LoadProfile reads the profile from the existing Stage A result envelope and
// validates its numerical parameters before allowing inference.
func LoadProfile(path string) (*analysis.StatisticalProfile, error) {
	b, err := os.ReadFile(path)
	if err != nil {
		return nil, err
	}
	var run StatisticalRun
	if err := json.Unmarshal(b, &run); err != nil {
		return nil, err
	}
	if err := run.Profile.Validate(); err != nil {
		return nil, fmt.Errorf("load statistical profile: %w", err)
	}
	return run.Profile, nil
}

func StageA(ctx context.Context, s *Source, cfg analysis.StatisticalConfig, progress func(string)) (*StatisticalRun, error) {
	if progress != nil {
		progress("A: fitting normalization, covariance, SVD and D1 q99")
	}
	p, err := analysis.FitStatistical(ctx, s.TrainingData(), analysis.NIRWindows()[0], cfg)
	if err != nil {
		return nil, err
	}
	if err = p.Validate(); err != nil {
		return nil, err
	}
	run := &StatisticalRun{Source: s, Profile: p}
	for i, w := range analysis.NIRWindows() {
		if progress != nil {
			progress(fmt.Sprintf("A: evaluating frozen statistical profile on D%d", i+1))
		}
		e := &run.Windows[i]
		n := 0
		e.Audit, err = s.Scan(ctx, w, func(v domain.TelemetryRecord) error {
			if !v.Valid {
				return nil
			}
			d, label, e2 := p.ControlLabel(v.Features())
			if e2 != nil {
				return e2
			}
			n++
			if n == 1 || d < e.DistanceMin {
				e.DistanceMin = d
			}
			if n == 1 || d > e.DistanceMax {
				e.DistanceMax = d
			}
			e.DistanceMean += (d - e.DistanceMean) / float64(n)
			if label {
				e.ControlPositive++
			}
			return nil
		})
		if err != nil {
			return nil, err
		}
		if e.Audit.States != 829440 || e.Audit.Timestamps != 2880 || e.Audit.Hosts != 288 || e.Audit.MinimumStatesPerTimestamp != 288 {
			return nil, fmt.Errorf("D%d does not meet expected complete 288-node grid: %+v", i+1, e.Audit)
		}
		if i == 0 && e.Audit.Valid != p.Observations {
			return nil, fmt.Errorf("D1 valid observation count changed after fitting")
		}
	}
	return run, nil
}

// SaveNew preserves existing results. A partially written result is never reused
// as a successful profile, and the original telemetry is never opened for writing.
func SaveNew(path string, v any) error {
	bytes, err := json.MarshalIndent(v, "", "  ")
	if err != nil {
		return err
	}
	f, err := os.OpenFile(path, os.O_WRONLY|os.O_CREATE|os.O_EXCL, 0600)
	if err != nil {
		return err
	}
	_, writeErr := f.Write(append(bytes, '\n'))
	closeErr := f.Close()
	if writeErr != nil {
		return writeErr
	}
	return closeErr
}
