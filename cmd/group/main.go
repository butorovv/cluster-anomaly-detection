// group is the research offline D1/D2 runner. It never trains Isolation Forest.
package main

import (
	"bufio"
	"context"
	"encoding/json"
	"flag"
	"fmt"
	"os"
	"os/signal"
	"path/filepath"
	"reflect"
	"runtime"
	"runtime/debug"
	"strconv"
	"time"

	"cluster-anomaly-detection/internal/analysis"
	"cluster-anomaly-detection/internal/group"
	"cluster-anomaly-detection/internal/local"
)

type output struct {
	file    *os.File
	buffer  *bufio.Writer
	encoder *json.Encoder
}

func openOutput(path string) (*output, error) {
	f, e := os.OpenFile(path, os.O_CREATE|os.O_EXCL|os.O_WRONLY, 0600)
	if e != nil {
		return nil, e
	}
	b := bufio.NewWriterSize(f, 1<<20)
	return &output{f, b, json.NewEncoder(b)}, nil
}
func (o *output) Close() error {
	if o == nil {
		return nil
	}
	if e := o.buffer.Flush(); e != nil {
		_ = o.file.Close()
		return e
	}
	return o.file.Close()
}

type counts struct {
	Ticks       int `json:"ticks"`
	RPositive   int `json:"r_positive"`
	BPositive   int `json:"b_positive"`
	YUnknown    int `json:"y_unknown"`
	RUnknown    int `json:"r_unknown"`
	BUnknown    int `json:"b_unknown"`
	Both        int `json:"both"`
	ROnly       int `json:"r_only"`
	BOnly       int `json:"b_only"`
	Neither     int `json:"neither"`
	ZeroPair    int `json:"r_positive_zero_mad_pair"`
	ZeroAbove   int `json:"r_positive_zero_mad_above"`
	IFAnomalies int `json:"if_anomalous_host_states"`
	IFAvailable int `json:"if_available_host_states"`
}

func main() {
	ctx, cancel := signal.NotifyContext(context.Background(), os.Interrupt)
	defer cancel()
	if e := run(ctx); e != nil {
		fmt.Fprintln(os.Stderr, e)
		os.Exit(1)
	}
}
func run(ctx context.Context) (err error) {
	start := time.Now()
	input := flag.String("input", "data/prepared/summit-D1-pilot/D1.parquet", "immutable prepared day")
	manifest := flag.String("manifest", "data/prepared/summit-D1-pilot/manifest.json", "prepared manifest")
	stat := flag.String("statistical-profile", "results/statistical-20220118-8h-v1.json", "frozen node statistical profile")
	forest := flag.String("isolation-profile", "results/isolation-20220118-v1.json", "frozen IF")
	b1 := flag.String("b1-profile", "configs/local-b1.summit-20220118.json", "unchanged individual B1 thresholds")
	hardware := flag.String("hardware", "configs/summit-hardware-reference.json", "approved bounds only")
	config := flag.String("config", "configs/group-detection.summit-v1.json", "frozen research contract")
	profilePath := flag.String("profile", "", "existing group profile for inference")
	fit := flag.Bool("fit", false, "fit D1 only and evaluate D1; no D2")
	window := flag.String("window", "D2", "D1 or D2; D3 deliberately unsupported")
	outputDir := flag.String("output", "", "new output directory (required)")
	groups := flag.Int("groups", 16, "nested universe 4, 8, 16; no refit")
	compact := flag.Bool("summary-only", false, "performance mode: omit raw/temporal NDJSON; keep event outputs")
	flag.Parse()
	if flag.NArg() != 0 || *outputDir == "" || (*groups != 4 && *groups != 8 && *groups != 16) {
		return fmt.Errorf("required --output NEW_DIRECTORY; --groups 4/8/16")
	}
	if *fit && (*profilePath != "" || *groups != 16) {
		return fmt.Errorf("fit requires all 16 groups and no input group profile")
	}
	split := 1
	if *fit || *window == "D1" {
		split = 0
	} else if *window != "D2" {
		return fmt.Errorf("only D1 and D2 allowed")
	}
	if !*fit && *profilePath == "" {
		return fmt.Errorf("--profile required without --fit")
	}
	// Fail before expensive I/O if output exists. Each run owns a new directory.
	if _, e := os.Stat(*outputDir); !os.IsNotExist(e) {
		return fmt.Errorf("output directory already exists or inaccessible")
	}
	if err = os.MkdirAll(filepath.Dir(*outputDir), 0755); err != nil {
		return err
	}
	if err = os.Mkdir(*outputDir, 0755); err != nil {
		return err
	}
	contract, err := group.LoadConfig(*config)
	if err != nil {
		return err
	}
	hashes := map[string]string{}
	for _, path := range []string{*input, *manifest, *stat, *forest, *b1, *hardware, *config} {
		h, e := group.FileSHA(path)
		if e != nil {
			return e
		}
		hashes[path] = h
	}
	models, err := local.OpenModels(*input, *manifest, *stat, *forest)
	if err != nil {
		return err
	}
	lp, err := local.LoadProfile(*b1)
	if err != nil {
		return err
	}
	ld, err := local.NewDetector(lp, models.Forest, models.Binding)
	if err != nil {
		return err
	}
	hw, err := group.LoadHardware(*hardware)
	if err != nil {
		return err
	}
	var p *group.Profile
	fitSeconds := 0.
	if *fit {
		t := time.Now()
		p, err = group.Fit(ctx, models, hashes)
		fitSeconds = time.Since(t).Seconds()
		if err != nil {
			return err
		}
		*profilePath = filepath.Join(*outputDir, "profile.json")
		if err = group.SaveJSON(*profilePath, p); err != nil {
			return err
		}
	} else {
		p, err = group.LoadProfile(*profilePath)
		if err != nil {
			return err
		}
	}
	if !reflect.DeepEqual(p.Binding, models.Binding) || !reflect.DeepEqual(p.InputSHA, hashes) {
		return fmt.Errorf("group profile input/model/config binding mismatch")
	}
	profileSHA, err := group.FileSHA(*profilePath)
	if err != nil {
		return err
	}
	w := analysis.NIRWindows()[split]
	runID, err := group.RunID(profileSHA, hashes, *groups, w)
	if err != nil {
		return err
	}
	events, err := openOutput(filepath.Join(*outputDir, "events.ndjson"))
	if err != nil {
		return err
	}
	defer func() {
		if e := events.Close(); err == nil {
			err = e
		}
	}()
	var rawOut, temporalOut *output
	if !*compact {
		rawOut, err = openOutput(filepath.Join(*outputDir, "raw.ndjson"))
		if err != nil {
			return err
		}
		defer func() {
			if e := rawOut.Close(); err == nil {
				err = e
			}
		}()
		temporalOut, err = openOutput(filepath.Join(*outputDir, "temporal.ndjson"))
		if err != nil {
			return err
		}
		defer func() {
			if e := temporalOut.Close(); err == nil {
				err = e
			}
		}()
	}
	engines := map[string]*group.Engine{}
	for _, delta := range contract.Delta {
		for _, g := range p.Groups[:*groups] {
			e, x := group.NewEngine(runID, g.Group, delta, w.Start)
			if x != nil {
				return x
			}
			engines[g.Group+"/"+strconv.Itoa(delta)] = e
		}
	}
	counters := map[string]*counts{}
	eventCounts := map[int]int{}
	candidateCounts := map[int]int{}
	eventSupported := map[int]int{}
	eventZeroPair := map[int]int{}
	timing := group.Timing{}
	maxHeap := uint64(0)
	ticks := 0
	analysisStart := time.Now()
	writeEvents := func(es []group.Event) error {
		for _, e := range es {
			eventCounts[e.DeltaSeconds]++
			if e.IFSupportedTicks > 0 {
				eventSupported[e.DeltaSeconds]++
			}
			if e.ZeroMADPairTicks > 0 {
				eventZeroPair[e.DeltaSeconds]++
			}
			if x := events.encoder.Encode(e); x != nil {
				return x
			}
		}
		return nil
	}
	err = group.WalkTicks(ctx, models.Source, w, func(t group.Tick) error {
		rows, e := group.Evaluate(p, t, hw, ld, *groups, &timing)
		if e != nil {
			return e
		}
		ticks++
		for _, r := range rows {
			if rawOut != nil {
				if e = rawOut.encoder.Encode(r); e != nil {
					return e
				}
			}
			c := counters[r.Group]
			if c == nil {
				c = &counts{}
				counters[r.Group] = c
			}
			c.Ticks++
			if r.R.State == group.Positive {
				c.RPositive++
				if len(r.R.ZeroMADAbove) > 0 {
					c.ZeroAbove++
				}
				for _, v := range r.R.Pair {
					if v.ZeroMAD {
						c.ZeroPair++
						break
					}
				}
			}
			if r.B.State == group.Positive {
				c.BPositive++
			}
			if r.Y.State == group.Unknown {
				c.YUnknown++
			}
			if r.R.State == group.Unknown {
				c.RUnknown++
			}
			if r.B.State == group.Unknown {
				c.BUnknown++
			}
			if r.R.State != group.Unknown && r.B.State != group.Unknown {
				switch {
				case r.R.State == group.Positive && r.B.State == group.Positive:
					c.Both++
				case r.R.State == group.Positive:
					c.ROnly++
				case r.B.State == group.Positive:
					c.BOnly++
				default:
					c.Neither++
				}
			}
			c.IFAnomalies += r.IF.Anomalous
			c.IFAvailable += r.IF.Available
			for _, delta := range contract.Delta {
				tm := time.Now()
				tr, es, x := engines[r.Group+"/"+strconv.Itoa(delta)].Step(r)
				timing.TemporalSeconds += time.Since(tm).Seconds()
				if x != nil {
					return x
				}
				if tr.Candidate == group.Positive {
					candidateCounts[delta]++
				}
				if temporalOut != nil {
					if e = temporalOut.encoder.Encode(tr); e != nil {
						return e
					}
				}
				if e = writeEvents(es); e != nil {
					return e
				}
			}
		}
		if ticks%30 == 0 {
			var mem runtime.MemStats
			runtime.ReadMemStats(&mem)
			if mem.HeapAlloc > maxHeap {
				maxHeap = mem.HeapAlloc
			}
		}
		return nil
	})
	if err != nil {
		return err
	}
	for _, delta := range contract.Delta {
		for _, g := range p.Groups[:*groups] {
			es, e := engines[g.Group+"/"+strconv.Itoa(delta)].Flush(w.End)
			if e != nil {
				return e
			}
			if e = writeEvents(es); e != nil {
				return e
			}
		}
	}
	analysisSeconds := time.Since(analysisStart).Seconds()
	after := map[string]string{}
	for path, h := range hashes {
		got, e := group.FileSHA(path)
		if e != nil {
			return e
		}
		if got != h {
			return fmt.Errorf("protected input changed: %s", path)
		}
		after[path] = got
	}
	if actual, e := group.FileSHA(*profilePath); e != nil || actual != profileSHA {
		return fmt.Errorf("group profile changed during run")
	}
	var mem runtime.MemStats
	runtime.ReadMemStats(&mem)
	if mem.HeapAlloc > maxHeap {
		maxHeap = mem.HeapAlloc
	}
	build, _ := debug.ReadBuildInfo()
	summary := map[string]any{"version": group.Version, "run_id": runID, "window": w, "groups": *groups, "ticks": ticks, "group_profile_sha256": profileSHA, "input_sha256_before": hashes, "input_sha256_after": after, "fit_seconds": fitSeconds, "analysis_seconds": analysisSeconds, "total_seconds": time.Since(start).Seconds(), "timing": timing, "host_states_per_second": float64(ticks*18*(*groups)) / analysisSeconds, "group_ticks_per_second": float64(ticks*(*groups)) / analysisSeconds, "sampled_peak_heap_bytes": maxHeap, "heap_sampling_cadence_ticks": 30, "total_alloc_bytes": mem.TotalAlloc, "gc_count": mem.NumGC, "go_version": runtime.Version(), "goos": runtime.GOOS, "goarch": runtime.GOARCH, "gomaxprocs": runtime.GOMAXPROCS(0), "build_info": build, "summary_only": *compact, "raw_counts": counters, "event_counts": eventCounts, "candidate_ticks": candidateCounts, "if_supported_events": eventSupported, "zero_mad_pair_events": eventZeroPair, "y_status": "unknown_when_no_approved_bounds", "delta_seconds": contract.Delta, "primary_delta_seconds": 0}
	if err = group.SaveJSON(filepath.Join(*outputDir, "summary.json"), summary); err != nil {
		return err
	}
	return json.NewEncoder(os.Stdout).Encode(summary)
}
