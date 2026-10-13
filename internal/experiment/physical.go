package experiment

import (
	"context"
	"encoding/json"
	"fmt"
	"os"
	"reflect"
	"time"

	"cluster-anomaly-detection/internal/analysis"
	"cluster-anomaly-detection/internal/modules/telemetry/domain"
)

type PhysicalEvaluation struct {
	Audit             Audit                     `json:"audit"`
	Components        [8]analysis.ResidualStats `json:"temperature_residuals_cpu0_cpu1_gpu0_to_gpu5"`
	PSU               analysis.ResidualStats    `json:"psu_residual_watt"`
	CPUCount          int                       `json:"cpu_predictions"`
	GPUCount          int                       `json:"gpu_predictions"`
	MAECPU            *float64                  `json:"mae_cpu_celsius"`
	MAEGPU            *float64                  `json:"mae_gpu_celsius"`
	PersistenceMAECPU *float64                  `json:"persistence_mae_cpu_celsius"`
	PersistenceMAEGPU *float64                  `json:"persistence_mae_gpu_celsius"`
	J                 *analysis.JResult         `json:"j,omitempty"`
}
type ThermalAssessment struct {
	Stability      analysis.Stability `json:"stability"`
	ReferencePower float64            `json:"d1_mean_component_power_w"`
	Equilibrium    *float64           `json:"equilibrium_at_d1_mean_power_celsius"`
}
type PhysicalRun struct {
	Source         *Source                   `json:"source"`
	Profile        *analysis.PhysicalProfile `json:"physical_profile"`
	TrainingAudit  Audit                     `json:"training_audit"`
	D1             PhysicalEvaluation        `json:"d1_diagnostics"`
	D2             PhysicalEvaluation        `json:"d2_diagnostics"`
	CPUAssessment  ThermalAssessment         `json:"cpu_assessment"`
	GPUAssessment  ThermalAssessment         `json:"gpu_assessment"`
	ElapsedSeconds float64                   `json:"elapsed_seconds"`
}

func observation(v domain.TelemetryRecord) analysis.PhysicalObservation {
	return analysis.PhysicalObservation{Timestamp: v.Timestamp, Hostname: v.Hostname, Features: v.Features()}
}

// PhysicalTrainingData preserves partial F18: each pair/sum is screened by the
// mathematics, rather than discarding a usable CPU because a PSU is missing.
func (s *Source) PhysicalTrainingData(audit *Audit) analysis.PhysicalData {
	return func(ctx context.Context, visit func(analysis.PhysicalObservation) error) error {
		a, err := s.Scan(ctx, analysis.NIRWindows()[0], func(v domain.TelemetryRecord) error { return visit(observation(v)) })
		if audit != nil {
			*audit = a
		}
		return err
	}
}
func assessment(m analysis.ThermalModel, power float64) ThermalAssessment {
	v := ThermalAssessment{Stability: m.Stability(), ReferencePower: power}
	if x, err := m.Equilibrium(power); err == nil {
		v.Equilibrium = &x
	}
	return v
}

// EvaluatePhysical uses a fresh transition history inside the specified split.
// The profile is frozen. Component residuals remain diagnostic only.
func EvaluatePhysical(ctx context.Context, s *Source, p *analysis.PhysicalProfile, w analysis.Window, interval *analysis.JInterval) (*PhysicalEvaluation, error) {
	if err := p.Validate(); err != nil {
		return nil, err
	}
	if w != analysis.NIRWindows()[0] && w != analysis.NIRWindows()[1] {
		return nil, fmt.Errorf("this experiment evaluates only D1/D2")
	}
	t, err := analysis.NewTransitions(w)
	if err != nil {
		return nil, err
	}
	var j *analysis.JAccumulator
	if interval != nil {
		if !s.hosts[interval.Hostname] {
			return nil, fmt.Errorf("J hostname outside source")
		}
		j, err = analysis.NewJAccumulator(*interval, w)
		if err != nil {
			return nil, err
		}
	}
	var components [8]analysis.ResidualAccumulator
	var psu analysis.ResidualAccumulator
	var persistenceCPU, persistenceGPU analysis.ResidualAccumulator
	e := &PhysicalEvaluation{}
	e.Audit, err = s.Scan(ctx, w, func(v domain.TelemetryRecord) error {
		if err := t.Push(observation(v), func(v analysis.ComponentTransition) error {
			_, residual, err := p.ThermalResidual(v)
			if err != nil {
				return err
			}
			if err = components[v.Component].Add(residual); err != nil {
				return err
			}
			baseline := &persistenceGPU
			if v.Component < 2 {
				baseline = &persistenceCPU
			}
			if err = baseline.Add(v.NextTemperature - v.Temperature); err != nil {
				return err
			}
			if j != nil {
				return j.Add(v.Hostname, v.Component, v.Timestamp, residual)
			}
			return nil
		}); err != nil {
			return err
		}
		_, residual, ok, err := p.PSUResidual(v.Features())
		if err != nil {
			return err
		}
		if ok {
			return psu.Add(residual)
		}
		return nil
	})
	if err != nil {
		return nil, err
	}
	var cpuAbs, gpuAbs float64
	for k := range components {
		e.Components[k] = components[k].Result()
		r := e.Components[k]
		if k < 2 {
			e.CPUCount += r.Count
			cpuAbs += r.MAE * float64(r.Count)
		} else {
			e.GPUCount += r.Count
			gpuAbs += r.MAE * float64(r.Count)
		}
	}
	if e.CPUCount > 0 {
		v := cpuAbs / float64(e.CPUCount)
		e.MAECPU = &v
		naive := persistenceCPU.Result().MAE
		e.PersistenceMAECPU = &naive
	}
	if e.GPUCount > 0 {
		v := gpuAbs / float64(e.GPUCount)
		e.MAEGPU = &v
		naive := persistenceGPU.Result().MAE
		e.PersistenceMAEGPU = &naive
	}
	e.PSU = psu.Result()
	if j != nil {
		v, err := j.Result()
		if err != nil {
			return nil, err
		}
		e.J = &v
	}
	return e, nil
}

func StageB(ctx context.Context, s *Source, cfg analysis.PhysicalConfig, interval *analysis.JInterval, progress func(string)) (*PhysicalRun, error) {
	if s == nil {
		return nil, fmt.Errorf("missing physical source")
	}
	if interval != nil {
		if err := interval.Validate(analysis.NIRWindows()[1]); err != nil {
			return nil, err
		}
		if !s.hosts[interval.Hostname] {
			return nil, fmt.Errorf("J hostname outside source")
		}
	}
	start := time.Now()
	notify := func(msg string) {
		if progress != nil {
			progress(msg)
		}
	}
	run := &PhysicalRun{Source: s}
	notify("B: fitting eight physical coefficients and three correlations on D1")
	p, err := analysis.FitPhysical(ctx, s.PhysicalTrainingData(&run.TrainingAudit), analysis.NIRWindows()[0], cfg)
	if err != nil {
		return nil, err
	}
	run.Profile = p
	notify("B: describing eight temperature residuals and PSU residual on D1")
	d1, err := EvaluatePhysical(ctx, s, p, analysis.NIRWindows()[0], nil)
	if err != nil {
		return nil, err
	}
	run.D1 = *d1
	if run.TrainingAudit != run.D1.Audit || run.D1.CPUCount != p.CPUFit.Observations || run.D1.GPUCount != p.GPUFit.Observations || run.D1.PSU.Count != p.PSUFit.Observations {
		return nil, fmt.Errorf("D1 changed between physical passes")
	}
	notify("B: evaluating frozen physical profile on D2")
	d2, err := EvaluatePhysical(ctx, s, p, analysis.NIRWindows()[1], interval)
	if err != nil {
		return nil, err
	}
	run.D2 = *d2
	for i, a := range []Audit{run.TrainingAudit, run.D2.Audit} {
		if a.States != 829440 || a.Timestamps != 2880 || a.Hosts != 288 || a.MinimumStatesPerTimestamp != 288 {
			return nil, fmt.Errorf("D%d incomplete node/time grid: %+v", i+1, a)
		}
	}
	run.CPUAssessment = assessment(p.CPU, p.CPUCorrelation.MeanPower)
	run.GPUAssessment = assessment(p.GPU, p.GPUCorrelation.MeanPower)
	run.ElapsedSeconds = time.Since(start).Seconds()
	return run, nil
}

// LoadPhysicalProfile validates the envelope and binds it to the immutable source.
// Implausible fitted signs are accepted: they are scientific results, not corruption.
func LoadPhysicalProfile(path string, s *Source) (*analysis.PhysicalProfile, error) {
	b, err := os.ReadFile(path)
	if err != nil {
		return nil, err
	}
	var run PhysicalRun
	if err = json.Unmarshal(b, &run); err != nil {
		return nil, err
	}
	if err = run.Profile.Validate(); err != nil {
		return nil, err
	}
	if s == nil || run.Source == nil || s.SHA256 != run.Source.SHA256 || !reflect.DeepEqual(s.Hosts, run.Source.Hosts) || !reflect.DeepEqual(s.Groups, run.Source.Groups) || s.AssumedTimezone != run.Source.AssumedTimezone || s.TimezoneVerified != run.Source.TimezoneVerified {
		return nil, fmt.Errorf("physical profile source/topology mismatch")
	}
	return run.Profile, nil
}
