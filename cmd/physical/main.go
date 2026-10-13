// physical fits the component model on D1 or applies a saved profile to D2.
package main

import (
	"context"
	"encoding/json"
	"flag"
	"fmt"
	"os"
	"os/signal"
	"path/filepath"
	"time"

	"cluster-anomaly-detection/internal/analysis"
	"cluster-anomaly-detection/internal/experiment"
)

func main() {
	if err := run(); err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}
}
func run() error {
	input := flag.String("input", "data/prepared/summit-D1-pilot/D1.parquet", "existing full-day prepared Parquet")
	manifest := flag.String("manifest", "data/prepared/summit-D1-pilot/manifest.json", "existing prepared manifest")
	output := flag.String("output", "", "new compact JSON result, never overwritten")
	profile := flag.String("profile", "", "load saved physical profile and evaluate D2 without fitting")
	rcond := flag.Float64("svd-rcond", 1e-12, "engineering relative cutoff on QR design SVD")
	jHost := flag.String("j-host", "", "explicit J hostname; all four J flags required")
	jComponent := flag.String("j-component", "", "explicit J component: CPU0/CPU1/GPU0..GPU5")
	jStart := flag.String("j-start", "", "inclusive first residual timestamp, RFC3339")
	jEnd := flag.String("j-end", "", "inclusive last residual timestamp, RFC3339")
	flag.Parse()
	var interval *analysis.JInterval
	if *jHost != "" || *jComponent != "" || *jStart != "" || *jEnd != "" {
		component := -1
		for i, c := range analysis.TemperatureComponents() {
			if c.Name == *jComponent {
				component = i
			}
		}
		start, err := time.Parse(time.RFC3339, *jStart)
		if err != nil {
			return fmt.Errorf("j-start: %w", err)
		}
		end, err := time.Parse(time.RFC3339, *jEnd)
		if err != nil {
			return fmt.Errorf("j-end: %w", err)
		}
		interval = &analysis.JInterval{Hostname: *jHost, Component: component, Start: start.UTC(), End: end.UTC()}
		if err = interval.Validate(analysis.NIRWindows()[1]); err != nil {
			return err
		}
	}
	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt)
	defer stop()
	s, err := experiment.OpenSource(*input, *manifest)
	if err != nil {
		return err
	}
	var result any
	if *profile == "" {
		result, err = experiment.StageB(ctx, s, analysis.PhysicalConfig{SVDRCond: *rcond}, interval, func(msg string) { fmt.Fprintln(os.Stderr, msg) })
	} else {
		p, e := experiment.LoadPhysicalProfile(*profile, s)
		if e != nil {
			return e
		}
		fmt.Fprintln(os.Stderr, "B: loaded physical profile; evaluating D2 without fitting")
		d2, e := experiment.EvaluatePhysical(ctx, s, p, analysis.NIRWindows()[1], interval)
		err = e
		result = struct {
			Source  *experiment.Source             `json:"source"`
			Profile *analysis.PhysicalProfile      `json:"physical_profile"`
			D2      *experiment.PhysicalEvaluation `json:"d2_diagnostics"`
		}{s, p, d2}
	}
	if err != nil {
		return err
	}
	if *output != "" {
		if err = os.MkdirAll(filepath.Dir(*output), 0700); err != nil {
			return err
		}
		if err = experiment.SaveNew(*output, result); err != nil {
			return err
		}
	}
	return json.NewEncoder(os.Stdout).Encode(result)
}
