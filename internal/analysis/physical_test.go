package analysis

import (
	"context"
	"math"
	"testing"
	"time"

	"cluster-anomaly-detection/internal/modules/telemetry/domain"
)

func nearPhysical(a, b float64) bool { return math.Abs(a-b) < 1e-8 }

func TestPhysicalForecastsUseEightIndependentF18Pairs(t *testing.T) {
	p := &PhysicalProfile{CPU: ThermalModel{.5, 2, 3}, GPU: ThermalModel{.25, 4, 5}}
	var v Vector
	for i := 0; i < 8; i++ {
		v[2+i] = float64(i + 1)
		v[10+i] = float64(20 + i)
	}
	f, err := p.Forecasts(v)
	if err != nil {
		t.Fatal(err)
	}
	for i := range f {
		if f[i] == nil {
			t.Fatalf("forecast %d unavailable", i)
		}
		m := p.GPU
		if i < 2 {
			m = p.CPU
		}
		want := m.A*v[10+i] + m.B*v[2+i] + m.C
		if !nearPhysical(*f[i], want) {
			t.Errorf("forecast %d = %g, want %g", i, *f[i], want)
		}
	}
	v[14] = math.NaN()
	f, err = p.Forecasts(v)
	if err != nil {
		t.Fatal(err)
	}
	if f[4] != nil || f[3] == nil {
		t.Fatalf("missing pair should affect only its component: %#v", f)
	}
}

func TestPhysicalIndexMapMatchesF18Layout(t *testing.T) {
	cs := TemperatureComponents()
	wantPower := [8]string{"cpu0_power", "cpu1_power", "gpu0_power", "gpu1_power", "gpu2_power", "gpu3_power", "gpu4_power", "gpu5_power"}
	wantTemp := [8]string{"cpu0_mean_temp", "cpu1_mean_temp", "gpu0_core_temp", "gpu1_core_temp", "gpu2_core_temp", "gpu3_core_temp", "gpu4_core_temp", "gpu5_core_temp"}
	for i, c := range cs {
		if c.Power != i+2 || c.Temperature != i+10 || domain.FeatureNames[c.Power] != wantPower[i] || domain.FeatureNames[c.Temperature] != wantTemp[i] {
			t.Errorf("component %d = %+v", i, c)
		}
	}
}

func TestPowerSumsAndResidualsAreSigned(t *testing.T) {
	var v Vector
	for i := 0; i < 10; i++ {
		v[i] = float64(i + 1)
	}
	compute, psu, ok := PowerSums(v)
	if !ok || compute != 52 || psu != 3 {
		t.Fatalf("PowerSums = %g,%g,%v", compute, psu, ok)
	}
	p := &PhysicalProfile{CPU: ThermalModel{.5, 1, 0}, PSU: PSUModel{1, .1}}
	pred, res, err := p.ThermalResidual(ComponentTransition{Component: 0, Temperature: 20, Power: 2, NextTemperature: 8})
	if err != nil || pred != 12 || res != -4 {
		t.Fatalf("thermal prediction/residual = %g,%g,%v", pred, res, err)
	}
	pred, res, avail, err := p.PSUResidual(v)
	if err != nil || !avail || pred != 6.2 || res != -3.2 {
		t.Fatalf("PSU prediction/residual = %g,%g,%v,%v", pred, res, avail, err)
	}
	v[0] = -1
	if _, _, avail, err = p.PSUResidual(v); err != nil || avail {
		t.Fatalf("invalid power availability = %v,%v", avail, err)
	}
}

func TestTransitionsInterleavedHostsAndExactPairs(t *testing.T) {
	w := NIRWindows()[0]
	tr, _ := NewTransitions(w)
	start := w.Start
	makeObs := func(host string, sec int) PhysicalObservation {
		var v Vector
		for i := 0; i < 8; i++ {
			v[i+2] = float64(i + 1)
			v[i+10] = float64(30 + i + sec)
		}
		return PhysicalObservation{start.Add(time.Duration(sec) * time.Second), host, v}
	}
	var got []ComponentTransition
	visit := func(v ComponentTransition) error { got = append(got, v); return nil }
	for _, o := range []PhysicalObservation{makeObs("a", 0), makeObs("b", 0), makeObs("a", 10), makeObs("b", 10), makeObs("a", 20), makeObs("b", 30), makeObs("a", 30)} {
		if err := tr.Push(o, visit); err != nil {
			t.Fatal(err)
		}
	}
	if len(got) != 32 {
		t.Fatalf("got %d transitions, want 32 (no gap bridging)", len(got))
	}
	for i, v := range got {
		want := "a"
		if i >= 8 && i < 16 {
			want = "b"
		}
		if v.Hostname != want {
			t.Errorf("unexpected host at %d: %s", i, v.Hostname)
		}
	}
	// Missing temperature pairs suppress just their own transition.
	tr2, _ := NewTransitions(w)
	first, next := makeObs("partial", 0), makeObs("partial", 10)
	next.Features[14] = math.NaN()
	var partial []ComponentTransition
	_ = tr2.Push(first, func(v ComponentTransition) error { partial = append(partial, v); return nil })
	_ = tr2.Push(next, func(v ComponentTransition) error { partial = append(partial, v); return nil })
	if len(partial) != 7 {
		t.Fatalf("missing pair yielded %d transitions, want 7", len(partial))
	}
}

func TestTransitionsRejectBadOrderAndGrid(t *testing.T) {
	w := NIRWindows()[0]
	tr, _ := NewTransitions(w)
	var v Vector
	o := PhysicalObservation{w.Start, "host", v}
	if err := tr.Push(o, nil); err != nil {
		t.Fatal(err)
	}
	for _, bad := range []PhysicalObservation{o, {w.Start, "host", v}, {w.End, "other", v}, {w.Start.Add(time.Second), "other", v}, {w.Start, "", v}} {
		if err := tr.Push(bad, nil); err == nil {
			t.Errorf("accepted invalid observation %+v", bad)
		}
	}
	tr2, _ := NewTransitions(w)
	if err := tr2.Push(o, nil); err != nil {
		t.Fatal(err)
	}
	if err := tr2.Push(PhysicalObservation{w.Start.Add(20 * time.Second), "host", v}, nil); err != nil {
		t.Fatalf("increasing timestamp with a gap should be accepted: %v", err)
	}
}

func TestFitPhysicalRecoversUnconstrainedCoefficients(t *testing.T) {
	w := NIRWindows()[0]
	data := func(_ context.Context, yield func(PhysicalObservation) error) error {
		var previous Vector
		for i := 0; i < 30; i++ {
			var v Vector
			// Vary every power and temperature independently, including negative slopes.
			for j := 0; j < 8; j++ {
				x := float64((i*(j+3)+j*j)%37 + 10)
				temp := float64((i*i*(j+1)+3*i+j)%43 + 50)
				v[2+j] = x
				v[10+j] = temp
			}
			// PSU response is exactly 7 + .3 * compute.
			compute := 0.0
			for j := 2; j < 10; j++ {
				compute += v[j]
			}
			psu := 7 + .3*compute
			// Encode PSU total using the two PSU channels.
			v[0] = psu * .4
			v[1] = psu - v[0]
			if i > 0 {
				for j := 0; j < 8; j++ {
					a, b, c := -.4, -.02, 40.0
					if j >= 2 {
						a, b, c = .6, .01, 20
					}
					v[10+j] = a*previous[10+j] + b*previous[2+j] + c
				}
			}
			if err := yield(PhysicalObservation{w.Start.Add(time.Duration(i) * Step), "node", v}); err != nil {
				return err
			}
			previous = v
		}
		return nil
	}
	p, err := FitPhysical(context.Background(), data, w, PhysicalConfig{1e-12})
	if err != nil {
		t.Fatal(err)
	}
	for name, m := range map[string]ThermalModel{"CPU": p.CPU, "GPU": p.GPU} {
		want := ThermalModel{-.4, -.02, 40}
		if name == "GPU" {
			want = ThermalModel{.6, .01, 20}
		}
		if !nearPhysical(m.A, want.A) || !nearPhysical(m.B, want.B) || !nearPhysical(m.C, want.C) {
			t.Errorf("%s fit %+v, want %+v", name, m, want)
		}
	}
	if !nearPhysical(p.PSU.Beta0, 7) || !nearPhysical(p.PSU.Beta1, .3) {
		t.Errorf("PSU fit %+v", p.PSU)
	}
}

func TestFitPhysicalRejectsNonD1(t *testing.T) {
	windows := NIRWindows()
	for _, window := range windows[1:] {
		if _, err := FitPhysical(context.Background(), func(context.Context, func(PhysicalObservation) error) error { return nil }, window, PhysicalConfig{1e-12}); err == nil {
			t.Errorf("accepted training split %+v", window)
		}
	}
}

func TestStreamingQRRejectsRankDeficiencyAndIllConditioning(t *testing.T) {
	var q streamingQR
	q.columns = 3
	for i := 0; i < 5; i++ {
		x := float64(i)
		if err := q.add([3]float64{x, 2 * x, 1}, float64(i)); err != nil {
			t.Fatal(err)
		}
	}
	if _, d, err := q.solve(1e-12); err == nil || d.Rank != 2 {
		t.Fatalf("rank deficient solve diagnostics=%+v err=%v", d, err)
	}
	var near streamingQR
	near.columns = 3
	for i := 0; i < 8; i++ {
		x := float64(i + 1)
		if err := near.add([3]float64{x, x + 1e-14*float64(i*i), 1}, 2*x+1); err != nil {
			t.Fatal(err)
		}
	}
	if _, d, err := near.solve(1e-12); err == nil {
		t.Fatalf("near-collinear solve diagnostics=%+v err=%v", d, err)
	}
}

func TestThermalStabilityCriteriaAreSeparate(t *testing.T) {
	for _, tc := range []struct {
		m                          ThermalModel
		stable, monotone, positive bool
	}{{ThermalModel{-.5, 1, 0}, true, false, true}, {ThermalModel{.5, -1, 0}, true, true, false}, {ThermalModel{1, 1, 0}, false, false, true}} {
		s := tc.m.Stability()
		if s.AsymptoticallyStable != tc.stable || s.MonotoneDecay != tc.monotone || s.PositivePowerEffect != tc.positive {
			t.Errorf("%+v => %+v", tc.m, s)
		}
	}
	if _, err := (ThermalModel{1, 1, 0}).Equilibrium(2); err == nil {
		t.Fatal("equilibrium with a=1 should be undefined")
	}
}

func TestPhysicalTrainingRejectsLeakedTargetsAndCancellation(t *testing.T) {
	d1 := NIRWindows()[0]
	for _, ts := range []time.Time{d1.End, d1.Start.Add(-Step)} {
		data := func(_ context.Context, visit func(PhysicalObservation) error) error {
			return visit(PhysicalObservation{Timestamp: ts, Hostname: "h"})
		}
		if _, err := FitPhysical(context.Background(), data, d1, PhysicalConfig{1e-12}); err == nil {
			t.Fatal("accepted observation outside D1")
		}
	}
	ctx, cancel := context.WithCancel(context.Background())
	cancel()
	data := func(_ context.Context, visit func(PhysicalObservation) error) error {
		return visit(PhysicalObservation{Timestamp: d1.Start, Hostname: "h"})
	}
	if _, err := FitPhysical(ctx, data, d1, PhysicalConfig{1e-12}); err != context.Canceled {
		t.Fatal("cancellation lost", err)
	}
}

func TestTransitionsDoNotBridgeMissingCoordinatesOrSplit(t *testing.T) {
	d1, d2 := NIRWindows()[0], NIRWindows()[1]
	tracker, _ := NewTransitions(d1)
	makeObs := func(ts time.Time) PhysicalObservation {
		var v Vector
		for j := 0; j < 8; j++ {
			v[2+j] = float64(10 + j)
			v[10+j] = float64(30 + j)
		}
		return PhysicalObservation{Timestamp: ts, Hostname: "h", Features: v}
	}
	a, b, c := makeObs(d1.End.Add(-3*Step)), makeObs(d1.End.Add(-2*Step)), makeObs(d1.End.Add(-Step))
	b.Features[2] = math.NaN() // CPU0 missing power; excludes both neighboring transitions
	count := [8]int{}
	visit := func(v ComponentTransition) error { count[v.Component]++; return nil }
	for _, v := range []PhysicalObservation{a, b, c} {
		if err := tracker.Push(v, visit); err != nil {
			t.Fatal(err)
		}
	}
	if count[0] != 0 || count[1] != 2 || count[7] != 2 {
		t.Fatal("bridged missing component", count)
	}
	if err := tracker.Push(makeObs(d2.Start), visit); err == nil {
		t.Fatal("crossed split")
	}
	next, _ := NewTransitions(d2)
	if err := next.Push(makeObs(d2.Start), visit); err != nil {
		t.Fatal(err)
	}
	if count[1] != 2 {
		t.Fatal("D2 seeded with D1 state")
	}
	if err := next.Push(makeObs(d2.Start.Add(-Step)), visit); err == nil {
		t.Fatal("accepted reverse timestamp")
	}
}

func TestPhysicalEquilibriumAndDegenerateFits(t *testing.T) {
	m := ThermalModel{A: .8, B: .02, C: 4}
	temp, err := m.Equilibrium(100)
	if err != nil || !nearPhysical(temp, 30) {
		t.Fatal(temp, err)
	}
	pred, err := m.Predict(temp, 100)
	if err != nil || !nearPhysical(pred, temp) {
		t.Fatal("equilibrium is not fixed point", pred, err)
	}
	for _, observations := range []int{0, 1, 10} {
		data := func(_ context.Context, visit func(PhysicalObservation) error) error {
			for i := 0; i < observations; i++ {
				if err := visit(PhysicalObservation{Timestamp: NIRWindows()[0].Start.Add(time.Duration(i) * Step), Hostname: "h"}); err != nil {
					return err
				}
			}
			return nil
		}
		if _, err := FitPhysical(context.Background(), data, NIRWindows()[0], PhysicalConfig{1e-12}); err == nil {
			t.Fatal("accepted degenerate fit", observations)
		}
	}
}
