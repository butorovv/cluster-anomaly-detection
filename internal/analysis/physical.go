package analysis

import (
	"context"
	"fmt"
	"math"
	"time"

	"gonum.org/v1/gonum/mat"
)

// Component indices are F18-v1 coordinates, not averages across devices.
type Component struct {
	Name               string
	Power, Temperature int
}

func TemperatureComponents() [8]Component {
	return [8]Component{{"CPU0", 2, 10}, {"CPU1", 3, 11}, {"GPU0", 4, 12}, {"GPU1", 5, 13}, {"GPU2", 6, 14}, {"GPU3", 7, 15}, {"GPU4", 8, 16}, {"GPU5", 9, 17}}
}

type PhysicalObservation struct {
	Timestamp time.Time
	Hostname  string
	Features  Vector
}
type PhysicalData func(context.Context, func(PhysicalObservation) error) error

// Missing/nonfinite coordinates and negative powers are unusable. No empirical
// temperature or power cutoffs are tuned on D2. Celsius must exceed absolute zero.
func componentPair(v Vector, c Component) (power, temperature float64, ok bool) {
	power, temperature = v[c.Power], v[c.Temperature]
	ok = Finite(power) && power >= 0 && Finite(temperature) && temperature > -273.15
	return
}

func PowerSums(v Vector) (compute, psu float64, ok bool) {
	for i := 0; i < 10; i++ {
		if !Finite(v[i]) || v[i] < 0 {
			return 0, 0, false
		}
		if i < 2 {
			psu += v[i]
		} else {
			compute += v[i]
		}
	}
	return compute, psu, Finite(compute) && Finite(psu)
}

type ComponentTransition struct {
	Hostname                            string
	Component                           int       // TemperatureComponents index
	Timestamp                           time.Time // target timestamp k+1
	Temperature, Power, NextTemperature float64
}

// Transitions retains one F18 per hostname, never a whole day's rows. Input may
// interleave nodes; per-host timestamps must increase. A new instance is required
// for each split, so no previous D1 value can seed a D2 prediction.
type Transitions struct {
	window   Window
	previous map[string]PhysicalObservation
}

func NewTransitions(w Window) (*Transitions, error) {
	if !w.Valid() {
		return nil, fmt.Errorf("invalid transition window")
	}
	return &Transitions{window: w, previous: make(map[string]PhysicalObservation)}, nil
}
func (t *Transitions) Push(o PhysicalObservation, visit func(ComponentTransition) error) error {
	if o.Hostname == "" || !t.window.Contains(o.Timestamp) || o.Timestamp.Sub(t.window.Start)%Step != 0 {
		return fmt.Errorf("invalid transition identity/window/grid")
	}
	previous, found := t.previous[o.Hostname]
	if found && !o.Timestamp.After(previous.Timestamp) {
		return fmt.Errorf("duplicate or reversed host timestamp")
	}
	if !found && len(t.previous) >= 288 {
		return fmt.Errorf("physical experiment exceeds 288 hosts")
	}
	t.previous[o.Hostname] = o // retain missing states too: never bridge a gap
	if !found || o.Timestamp.Sub(previous.Timestamp) != Step {
		return nil
	}
	for j, c := range TemperatureComponents() {
		power, temperature, ok := componentPair(previous.Features, c)
		_, next, nextOK := componentPair(o.Features, c)
		if ok && nextOK && visit != nil {
			if err := visit(ComponentTransition{o.Hostname, j, o.Timestamp, temperature, power, next}); err != nil {
				return err
			}
		}
	}
	return nil
}

type Correlation struct {
	Observations int      `json:"observations"`
	R            *float64 `json:"r"` // null is undefined, including zero variance
	MeanPower    float64  `json:"mean_power_w"`
	MeanResponse float64  `json:"mean_response"`
}
type PearsonAccumulator struct {
	n                int
	x, y, xx, yy, xy float64
}

func (p *PearsonAccumulator) Add(x, y float64) error {
	if !Finite(x) || !Finite(y) {
		return fmt.Errorf("nonfinite Pearson pair")
	}
	p.n++
	dx, dy := x-p.x, y-p.y
	p.x += dx / float64(p.n)
	p.y += dy / float64(p.n)
	p.xx += dx * (x - p.x)
	p.yy += dy * (y - p.y)
	p.xy += dx * (y - p.y)
	if !Finite(p.xx) || !Finite(p.yy) || !Finite(p.xy) {
		return fmt.Errorf("Pearson overflow")
	}
	return nil
}
func (p *PearsonAccumulator) Result() (Correlation, error) {
	r := Correlation{Observations: p.n, MeanPower: p.x, MeanResponse: p.y}
	if p.n < 2 || p.xx == 0 || p.yy == 0 {
		return r, nil
	}
	if p.xx < 0 || p.yy < 0 {
		return r, fmt.Errorf("negative Pearson variance")
	}
	v := (p.xy / math.Sqrt(p.xx)) / math.Sqrt(p.yy)
	if !Finite(v) || math.Abs(v) > 1+1e-12 {
		return r, fmt.Errorf("invalid Pearson correlation")
	}
	v = math.Max(-1, math.Min(1, v))
	r.R = &v
	return r, nil
}

type ThermalModel struct {
	A float64 `json:"a"`
	B float64 `json:"b_celsius_per_watt"`
	C float64 `json:"c_celsius"`
}

func (m ThermalModel) Predict(temperature, power float64) (float64, error) {
	v := m.A*temperature + m.B*power + m.C
	if !Finite(temperature) || temperature <= -273.15 || !Finite(power) || power < 0 || !Finite(v) {
		return 0, fmt.Errorf("invalid thermal prediction")
	}
	return v, nil
}
func (m ThermalModel) Equilibrium(power float64) (float64, error) {
	if !Finite(m.A) || !Finite(m.B) || !Finite(m.C) || !Finite(power) || power < 0 || m.A == 1 {
		return 0, fmt.Errorf("undefined equilibrium")
	}
	v := (m.B*power + m.C) / (1 - m.A)
	if !Finite(v) {
		return 0, fmt.Errorf("equilibrium overflow")
	}
	return v, nil
}

type Stability struct {
	AsymptoticallyStable bool `json:"abs_a_lt_1"`
	MonotoneDecay        bool `json:"a_between_0_and_1"`
	PositivePowerEffect  bool `json:"b_positive"`
	PhysicallyPlausible  bool `json:"physically_plausible"`
}

func (m ThermalModel) Stability() Stability {
	a, b := Finite(m.A) && m.A > 0 && m.A < 1, Finite(m.B) && m.B > 0
	return Stability{Finite(m.A) && math.Abs(m.A) < 1, a, b, a && b}
}

type PSUModel struct {
	Beta0 float64 `json:"beta_0_watt"`
	Beta1 float64 `json:"beta_1"`
}

func (m PSUModel) Predict(compute float64) (float64, error) {
	v := m.Beta0 + m.Beta1*compute
	if !Finite(compute) || compute < 0 || !Finite(v) {
		return 0, fmt.Errorf("invalid PSU prediction")
	}
	return v, nil
}

type FitDiagnostics struct {
	Observations int     `json:"observations"`
	Rank         int     `json:"rank"`
	Condition    float64 `json:"design_condition_2"`
}
type PhysicalConfig struct {
	SVDRCond float64 `json:"svd_relative_cutoff"`
}
type PhysicalProfile struct {
	Version        string         `json:"version"`
	TrainingWindow Window         `json:"training_window"`
	StepSeconds    int            `json:"step_seconds"`
	Config         PhysicalConfig `json:"numerical_conventions"`
	CPU            ThermalModel   `json:"cpu"`
	GPU            ThermalModel   `json:"gpu"`
	PSU            PSUModel       `json:"psu"`
	CPUFit         FitDiagnostics `json:"cpu_fit"`
	GPUFit         FitDiagnostics `json:"gpu_fit"`
	PSUFit         FitDiagnostics `json:"psu_fit"`
	CPUCorrelation Correlation    `json:"cpu_correlation"`
	GPUCorrelation Correlation    `json:"gpu_correlation"`
	PSUCorrelation Correlation    `json:"psu_correlation"`
}

// streamingQR applies orthogonal Givens rotations to [X|y]. Its small R and
// Q^T y preserve the least-squares minimizer without X^T X or stored samples.
// Gonum SVD of R checks rank/condition and solves the unconstrained fit.
type streamingQR struct {
	columns, n int
	r          [3][3]float64
	z          [3]float64
}

func (q *streamingQR) add(row [3]float64, y float64) error {
	for i := 0; i < q.columns; i++ {
		if !Finite(row[i]) {
			return fmt.Errorf("nonfinite design")
		}
	}
	if !Finite(y) {
		return fmt.Errorf("nonfinite target")
	}
	for j := 0; j < q.columns; j++ {
		r := math.Hypot(q.r[j][j], row[j])
		if r == 0 {
			continue
		}
		c, s := q.r[j][j]/r, row[j]/r
		q.r[j][j] = r
		for k := j + 1; k < q.columns; k++ {
			x := c*q.r[j][k] + s*row[k]
			row[k] = -s*q.r[j][k] + c*row[k]
			q.r[j][k] = x
		}
		x := c*q.z[j] + s*y
		y = -s*q.z[j] + c*y
		q.z[j] = x
	}
	q.n++
	return nil
}
func (q *streamingQR) solve(rcond float64) ([]float64, FitDiagnostics, error) {
	d := FitDiagnostics{Observations: q.n}
	if q.n < q.columns {
		return nil, d, fmt.Errorf("insufficient least-squares observations")
	}
	r, z := mat.NewDense(q.columns, q.columns, nil), mat.NewDense(q.columns, 1, nil)
	for i := 0; i < q.columns; i++ {
		if !Finite(q.z[i]) {
			return nil, d, fmt.Errorf("QR target overflow")
		}
		z.Set(i, 0, q.z[i])
		for j := 0; j < q.columns; j++ {
			if !Finite(q.r[i][j]) {
				return nil, d, fmt.Errorf("QR design overflow")
			}
			r.Set(i, j, q.r[i][j])
		}
	}
	var svd mat.SVD
	if !svd.Factorize(r, mat.SVDFull) {
		return nil, d, fmt.Errorf("least-squares SVD failed")
	}
	d.Rank = svd.Rank(rcond)
	if d.Rank != q.columns {
		return nil, d, fmt.Errorf("non-identifiable least-squares design: rank %d/%d", d.Rank, q.columns)
	}
	d.Condition = svd.Cond()
	if !Finite(d.Condition) || d.Condition >= 1/rcond {
		return nil, d, fmt.Errorf("ill-conditioned least-squares design")
	}
	var solution mat.Dense
	svd.SolveTo(&solution, z, d.Rank)
	values := make([]float64, q.columns)
	for j := range values {
		values[j] = solution.At(j, 0)
		if !Finite(values[j]) {
			return nil, d, fmt.Errorf("nonfinite fit coefficient")
		}
	}
	return values, d, nil
}

func FitPhysical(ctx context.Context, data PhysicalData, window Window, cfg PhysicalConfig) (*PhysicalProfile, error) {
	if window != NIRWindows()[0] || data == nil || !Finite(cfg.SVDRCond) || cfg.SVDRCond <= 0 || cfg.SVDRCond >= 1 {
		return nil, fmt.Errorf("physical training requires fixed D1 and valid SVD cutoff")
	}
	t, _ := NewTransitions(window)
	cpu, gpu, psu := streamingQR{columns: 3}, streamingQR{columns: 3}, streamingQR{columns: 2}
	var cp, gp, pp PearsonAccumulator
	err := data(ctx, func(o PhysicalObservation) error {
		if err := ctx.Err(); err != nil {
			return err
		}
		if err := t.Push(o, func(v ComponentTransition) error {
			q := &gpu
			if v.Component < 2 {
				q = &cpu
			}
			return q.add([3]float64{v.Temperature, v.Power, 1}, v.NextTemperature)
		}); err != nil {
			return err
		}
		for j, c := range TemperatureComponents() {
			power, temp, ok := componentPair(o.Features, c)
			if ok {
				p := &gp
				if j < 2 {
					p = &cp
				}
				if err := p.Add(power, temp); err != nil {
					return err
				}
			}
		}
		compute, power, ok := PowerSums(o.Features)
		if ok {
			if err := pp.Add(compute, power); err != nil {
				return err
			}
			return psu.add([3]float64{1, compute}, power)
		}
		return nil
	})
	if err != nil {
		return nil, err
	}
	p := &PhysicalProfile{Version: "physical-v1", TrainingWindow: window, StepSeconds: 10, Config: cfg}
	c, cd, err := cpu.solve(cfg.SVDRCond)
	if err != nil {
		return nil, fmt.Errorf("CPU: %w", err)
	}
	g, gd, err := gpu.solve(cfg.SVDRCond)
	if err != nil {
		return nil, fmt.Errorf("GPU: %w", err)
	}
	b, pd, err := psu.solve(cfg.SVDRCond)
	if err != nil {
		return nil, fmt.Errorf("PSU: %w", err)
	}
	p.CPU, p.GPU, p.PSU = ThermalModel{c[0], c[1], c[2]}, ThermalModel{g[0], g[1], g[2]}, PSUModel{b[0], b[1]}
	p.CPUFit, p.GPUFit, p.PSUFit = cd, gd, pd
	if p.CPUCorrelation, err = cp.Result(); err != nil {
		return nil, err
	}
	if p.GPUCorrelation, err = gp.Result(); err != nil {
		return nil, err
	}
	if p.PSUCorrelation, err = pp.Result(); err != nil {
		return nil, err
	}
	return p, p.Validate()
}

func (p *PhysicalProfile) Validate() error {
	if p == nil {
		return fmt.Errorf("missing physical profile")
	}
	if p.Version != "physical-v1" || p.TrainingWindow != NIRWindows()[0] || p.StepSeconds != 10 || !Finite(p.Config.SVDRCond) || p.Config.SVDRCond <= 0 || p.Config.SVDRCond >= 1 {
		return fmt.Errorf("invalid physical profile metadata")
	}
	for _, v := range []float64{p.CPU.A, p.CPU.B, p.CPU.C, p.GPU.A, p.GPU.B, p.GPU.C, p.PSU.Beta0, p.PSU.Beta1} {
		if !Finite(v) {
			return fmt.Errorf("nonfinite physical coefficient")
		}
	}
	for j, d := range []FitDiagnostics{p.CPUFit, p.GPUFit, p.PSUFit} {
		rank := 3
		if j == 2 {
			rank = 2
		}
		if d.Observations < rank || d.Rank != rank || !Finite(d.Condition) || d.Condition < 1 || d.Condition >= 1/p.Config.SVDRCond {
			return fmt.Errorf("invalid physical fit diagnostics")
		}
	}
	for _, c := range []Correlation{p.CPUCorrelation, p.GPUCorrelation, p.PSUCorrelation} {
		if c.Observations < 2 || !Finite(c.MeanPower) || c.MeanPower < 0 || !Finite(c.MeanResponse) || (c.R != nil && (!Finite(*c.R) || math.Abs(*c.R) > 1)) {
			return fmt.Errorf("invalid physical correlation")
		}
	}
	if p.CPUFit.Observations > p.CPUCorrelation.Observations || p.GPUFit.Observations > p.GPUCorrelation.Observations || p.PSUFit.Observations != p.PSUCorrelation.Observations {
		return fmt.Errorf("inconsistent physical observation counts")
	}
	return nil
}

// Forecasts returns eight independent one-step predictions; nil means that
// component's pair is unavailable. It neither averages devices nor labels faults.
func (p *PhysicalProfile) Forecasts(v Vector) ([8]*float64, error) {
	var result [8]*float64
	for j, c := range TemperatureComponents() {
		power, temp, ok := componentPair(v, c)
		if !ok {
			continue
		}
		m := p.GPU
		if j < 2 {
			m = p.CPU
		}
		x, err := m.Predict(temp, power)
		if err != nil {
			return result, err
		}
		result[j] = &x
	}
	return result, nil
}
func (p *PhysicalProfile) ThermalResidual(v ComponentTransition) (prediction, residual float64, err error) {
	if v.Component < 0 || v.Component >= 8 || !Finite(v.NextTemperature) || v.NextTemperature <= -273.15 {
		return 0, 0, fmt.Errorf("invalid component target")
	}
	m := p.GPU
	if v.Component < 2 {
		m = p.CPU
	}
	prediction, err = m.Predict(v.Temperature, v.Power)
	if err != nil {
		return
	}
	residual = v.NextTemperature - prediction
	if !Finite(residual) {
		err = fmt.Errorf("thermal residual overflow")
	}
	return
}
func (p *PhysicalProfile) PSUResidual(v Vector) (prediction, residual float64, available bool, err error) {
	compute, power, ok := PowerSums(v)
	if !ok {
		return 0, 0, false, nil
	}
	prediction, err = p.PSU.Predict(compute)
	residual = power - prediction
	if err == nil && !Finite(residual) {
		err = fmt.Errorf("PSU residual overflow")
	}
	return prediction, residual, err == nil, err
}
