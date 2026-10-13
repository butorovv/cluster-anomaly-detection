// calibration fixes an IF threshold on D2 using the existing frozen D1 models.
package main

import (
	"context"
	"encoding/json"
	"flag"
	"fmt"
	"os"
	"os/signal"
	"path/filepath"
	"reflect"

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
	statistical := flag.String("statistical-profile", "results/statistical-20220118-8h-v1.json", "frozen Stage A D1 profile")
	forest := flag.String("isolation-profile", "results/isolation-20220118-v1.json", "frozen Stage C D1 forest")
	calibration := flag.String("calibration", "", "load saved threshold and re-evaluate D2 without search")
	output := flag.String("output", "", "new compact JSON result, never overwritten")
	flag.Parse()
	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt)
	defer stop()
	s, err := experiment.OpenSource(*input, *manifest)
	if err != nil {
		return err
	}
	var result any
	if *calibration == "" {
		result, err = experiment.CalibrateIsolationD2(ctx, s, *forest, *statistical, func(msg string) { fmt.Fprintln(os.Stderr, msg) })
	} else {
		r, e := experiment.LoadIsolationCalibration(*calibration, s, *forest, *statistical)
		if e != nil {
			return e
		}
		fmt.Fprintln(os.Stderr, "D2: loaded calibration; applying frozen threshold without search")
		eval, e := experiment.EvaluateIsolationCalibrationD2(ctx, s, *forest, *statistical, r)
		if e != nil {
			return e
		}
		if eval.Audit != r.Audit || eval.Confusion != r.Calibration.Confusion || !reflect.DeepEqual(eval.Metrics, r.Calibration.Metrics) || eval.IFFirings != r.IFFirings {
			return fmt.Errorf("D2 results differ after calibration reload")
		}
		result = struct {
			Evaluation    *experiment.CalibrationEvaluation `json:"d2_evaluation"`
			ReloadMatched bool                              `json:"reload_matched"`
		}{eval, true}
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
