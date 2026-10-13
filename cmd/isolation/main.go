// isolation fits or reloads the global D1 Isolation Forest using Stage A scales.
package main

import (
	"context"
	"encoding/json"
	"flag"
	"fmt"
	"os"
	"os/signal"
	"path/filepath"

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
	defaults := analysis.DefaultIsolationConfig()
	input := flag.String("input", "data/prepared/summit-D1-pilot/D1.parquet", "existing full-day prepared Parquet")
	manifest := flag.String("manifest", "data/prepared/summit-D1-pilot/manifest.json", "existing prepared manifest")
	statistical := flag.String("statistical-profile", "results/statistical-20220118-8h-v1.json", "existing D1 Stage A normalization envelope")
	output := flag.String("output", "", "new JSON result, never overwritten")
	profile := flag.String("profile", "", "load saved forest and rescore D1 without fitting")
	trees := flag.Int("trees", defaults.Trees, "number of isolation trees")
	sample := flag.Int("sample-size", defaults.SampleSize, "independent reservoir size per tree")
	depth := flag.Int("max-depth", defaults.MaxDepth, "maximum edges from root (zero permits root leaf)")
	seed := flag.Int64("seed", defaults.Seed, "deterministic random seed")
	flag.Parse()
	if *profile != "" {
		var invalid bool
		flag.Visit(func(f *flag.Flag) {
			switch f.Name {
			case "trees", "sample-size", "max-depth", "seed":
				invalid = true
			}
		})
		if invalid {
			return fmt.Errorf("hyperparameter flags cannot override a loaded forest")
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
		result, err = experiment.StageC(ctx, s, *statistical, analysis.IsolationConfig{Trees: *trees, SampleSize: *sample, MaxDepth: *depth, Seed: *seed}, func(msg string) { fmt.Fprintln(os.Stderr, msg) })
	} else {
		loaded, e := experiment.LoadIsolationProfile(*profile, s, *statistical)
		if e != nil {
			return e
		}
		fmt.Fprintln(os.Stderr, "C: loaded forest; rescoring D1 without fitting")
		d1, e := experiment.EvaluateIsolationD1(ctx, s, loaded.Profile)
		if e != nil {
			return e
		}
		if d1.Audit != loaded.D1.Audit || d1.Scores != loaded.D1.Scores {
			return fmt.Errorf("D1 scores differ after profile reload")
		}
		result = struct {
			Source        *experiment.Source              `json:"source"`
			D1            *experiment.IsolationEvaluation `json:"d1_diagnostics"`
			ReloadMatched bool                            `json:"reload_matched"`
		}{s, d1, true}
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
