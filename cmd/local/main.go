// local applies a frozen global IF with individual D1 B1 thresholds offline.
package main

import (
	"bufio"
	"context"
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"io"
	"os"
	"os/signal"
	"strings"

	"cluster-anomaly-detection/internal/analysis"
	"cluster-anomaly-detection/internal/local"
)

func main() {
	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt)
	defer stop()
	if err := run(ctx, os.Args[1:], os.Stdout, os.Stderr); err != nil {
		status := local.StatusOf(err)
		if status == "" {
			status = "input_error"
		}
		_ = json.NewEncoder(os.Stderr).Encode(map[string]string{"diagnostic_status": status, "error": err.Error()})
		os.Exit(1)
	}
}

func run(ctx context.Context, args []string, stdout, stderr io.Writer) error {
	flags := flag.NewFlagSet("local", flag.ContinueOnError)
	flags.SetOutput(stderr)
	input := flags.String("input", "data/prepared/summit-D1-pilot/D1.parquet", "existing prepared day")
	manifest := flags.String("manifest", "data/prepared/summit-D1-pilot/manifest.json", "prepared manifest")
	stat := flags.String("statistical-profile", "results/statistical-20220118-8h-v1.json", "frozen D1 statistical profile")
	forest := flags.String("isolation-profile", "results/isolation-20220118-v1.json", "frozen A0 forest")
	profile := flags.String("b1-profile", "configs/local-b1.summit-20220118.json", "bound individual B1 thresholds")
	build := flags.String("build-profile", "", "create a new B1 profile exclusively from D1; never overwrite")
	importDir := flags.String("import-context", "", "reuse checked context research D1 scores/thresholds; requires --build-profile")
	window := flags.String("window", "D2", "inference split: D1, D2 or D3; never changes calibration")
	summaryOnly := flags.Bool("summary-only", false, "emit only compact counts and binding")
	output := flags.String("output", "", "new output file; default stdout; never overwrite")
	if err := flags.Parse(args); err != nil {
		if errors.Is(err, flag.ErrHelp) {
			return nil
		}
		return err
	}
	if flags.NArg() != 0 {
		return fmt.Errorf("unexpected positional arguments")
	}
	if *importDir != "" && *build == "" {
		return fmt.Errorf("--import-context requires --build-profile")
	}
	index := -1
	for i, name := range []string{"D1", "D2", "D3"} {
		if strings.EqualFold(*window, name) {
			index = i
		}
	}
	if index < 0 {
		return fmt.Errorf("--window must be D1, D2 or D3")
	}
	if *build != "" && (*output != "" || *summaryOnly) {
		return fmt.Errorf("profile creation cannot be combined with inference output options")
	}
	models, err := local.OpenModels(*input, *manifest, *stat, *forest)
	if err != nil {
		return err
	}
	if *build != "" {
		var p *local.Profile
		if *importDir != "" {
			p, err = models.ImportContextProfile(*importDir)
		} else {
			p, _, err = models.BuildProfile(ctx)
		}
		if err != nil {
			return err
		}
		if err = local.SaveProfile(*build, p); err != nil {
			return err
		}
		return json.NewEncoder(stdout).Encode(map[string]any{"type": "b1_profile_created", "path": *build, "hosts": p.HostCount, "training_window": p.TrainingWindow, "provenance": p.Provenance})
	}
	var writer io.Writer = stdout
	var file *os.File
	if *output != "" {
		file, err = os.OpenFile(*output, os.O_WRONLY|os.O_CREATE|os.O_EXCL, 0600)
		if err != nil {
			return err
		}
		defer file.Close()
		writer = file
	}
	buffer := bufio.NewWriterSize(writer, 1<<20)
	encoder := json.NewEncoder(buffer)
	var visit func(local.LocalResult) error
	if !*summaryOnly {
		visit = func(result local.LocalResult) error {
			return encoder.Encode(struct {
				Type string `json:"type"`
				local.LocalResult
			}{"local_result", result})
		}
	}
	summary, err := models.Run(ctx, *profile, analysis.NIRWindows()[index], visit)
	if err != nil {
		return err
	}
	if err = encoder.Encode(summary); err != nil {
		return err
	}
	if err = buffer.Flush(); err != nil {
		return err
	}
	if file != nil {
		return file.Close()
	}
	return nil
}
