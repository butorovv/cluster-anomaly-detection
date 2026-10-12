// nir performs offline mathematical experiments using existing prepared data.
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
	input := flag.String("input", "data/prepared/summit-D1-pilot/D1.parquet", "existing full-day prepared Parquet")
	manifest := flag.String("manifest", "data/prepared/summit-D1-pilot/manifest.json", "existing prepared manifest")
	output := flag.String("output", "", "new small JSON result path; existing results are not overwritten")
	rcond := flag.Float64("svd-rcond", 1e-12, "engineering relative SVD rank cutoff")
	ddof := flag.Int("covariance-ddof", 1, "engineering covariance convention: 0 or 1")
	flag.Parse()
	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt)
	defer stop()
	s, err := experiment.OpenSource(*input, *manifest)
	if err != nil {
		return err
	}
	result, err := experiment.StageA(ctx, s, analysis.StatisticalConfig{SVDRCond: *rcond, CovarianceDDOF: *ddof}, func(msg string) { fmt.Fprintln(os.Stderr, msg) })
	if err != nil {
		return err
	}
	if *output != "" {
		if err := os.MkdirAll(filepath.Dir(*output), 0700); err != nil {
			return err
		}
		if err := experiment.SaveNew(*output, result); err != nil {
			return err
		}
	}
	return json.NewEncoder(os.Stdout).Encode(result)
}
