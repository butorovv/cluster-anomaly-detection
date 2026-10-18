// Saved-forest D2 scoring benchmark; never trains or reads a full-day Parquet.
package main

import (
	"crypto/sha256"
	"encoding/binary"
	"encoding/hex"
	"encoding/json"
	"flag"
	"fmt"
	"math"
	"os"
	"runtime"
	"sort"
	"time"

	"cluster-anomaly-detection/internal/analysis"
	"cluster-anomaly-detection/tools/context/model"
)

type record struct {
	Raw    analysis.Vector
	Host   int
	A0, B2 float64
}
type sample struct {
	Seconds    []float64 `json:"seconds"`
	Median     float64   `json:"median"`
	Min        float64   `json:"min"`
	Max        float64   `json:"max"`
	Throughput float64   `json:"states_per_second"`
	Error      float64   `json:"max_score_error"`
}

func hash(p string) (string, error) {
	b, e := os.ReadFile(p)
	if e != nil {
		return "", e
	}
	s := sha256.Sum256(b)
	return hex.EncodeToString(s[:]), nil
}
func main() {
	if e := run(); e != nil {
		fmt.Fprintln(os.Stderr, e)
		os.Exit(1)
	}
}
func run() error {
	output := flag.String("output", "results/research43-stage2-v1/forest-benchmark.json", "new output file")
	root := flag.String("export", "results/context-v1", "immutable D1/D2 export directory")
	flag.Parse()
	runtime.GOMAXPROCS(1)
	paths := []string{*root + "/D2.bin", *root + "/metadata.json", "results/isolation-20220118-v1.json", *root + "/b2-42.json"}
	hashes := map[string]string{}
	for _, p := range paths {
		h, e := hash(p)
		if e != nil {
			return e
		}
		hashes[p] = h
	}
	var metadata struct {
		Source struct {
			Hosts []string `json:"hosts"`
		} `json:"source"`
		Context *model.ContextProfile `json:"context_profile"`
	}
	b, e := os.ReadFile(paths[1])
	if e != nil {
		return e
	}
	if e = json.Unmarshal(b, &metadata); e != nil {
		return e
	}
	if metadata.Context == nil || len(metadata.Source.Hosts) != 288 {
		return fmt.Errorf("incomplete metadata")
	}
	if e = metadata.Context.Validate(); e != nil {
		return e
	}
	var forests [2]*analysis.IsolationForest
	for i, p := range paths[2:] {
		var envelope struct {
			Forest *analysis.IsolationForest `json:"isolation_forest"`
		}
		b, e = os.ReadFile(p)
		if e != nil {
			return e
		}
		if e = json.Unmarshal(b, &envelope); e != nil {
			return e
		}
		if envelope.Forest == nil {
			return fmt.Errorf("missing forest")
		}
		if e = envelope.Forest.Validate(); e != nil {
			return e
		}
		if envelope.Forest.TrainingWindow != analysis.NIRWindows()[0] {
			return fmt.Errorf("forest must be D1")
		}
		forests[i] = envelope.Forest
	}
	readStart := time.Now()
	b, e = os.ReadFile(paths[0])
	if e != nil {
		return e
	}
	if len(b) != 829440*216 {
		return fmt.Errorf("wrong D2 record count")
	}
	records := make([]record, 829440)
	start := time.Date(2022, 1, 18, 8, 0, 0, 0, time.UTC).UnixMicro()
	for i := range records {
		row := b[i*216 : (i+1)*216]
		h := int(binary.LittleEndian.Uint32(row[8:12]))
		ts := int64(binary.LittleEndian.Uint64(row[:8]))
		if h != i%288 || ts != start+int64(i/288)*10000000 || binary.LittleEndian.Uint32(row[12:16]) != 262143 {
			return fmt.Errorf("D2 timestamp/host/availability mismatch")
		}
		records[i].Host = h
		for j := 0; j < 18; j++ {
			records[i].Raw[j] = math.Float64frombits(binary.LittleEndian.Uint64(row[16+j*8 : 24+j*8]))
		}
		records[i].A0 = math.Float64frombits(binary.LittleEndian.Uint64(row[160:168]))
		records[i].B2 = math.Float64frombits(binary.LittleEndian.Uint64(row[168:176]))
	}
	readSeconds := time.Since(readStart).Seconds()
	b = nil
	runtime.GC()
	results := map[string]sample{}
	for i, name := range []string{"A0", "B2"} {
		var times []float64
		maxError := 0.
		for repeat := -1; repeat < 5; repeat++ {
			t := time.Now()
			errMax := 0.
			for _, r := range records {
				v := r.Raw
				if i == 1 {
					v, e = metadata.Context.Adapt(metadata.Source.Hosts[r.Host], v)
					if e != nil {
						return e
					}
				}
				score, er := forests[i].Score(v)
				if er != nil {
					return er
				}
				expected := r.A0
				if i == 1 {
					expected = r.B2
				}
				errMax = math.Max(errMax, math.Abs(score-expected))
			}
			elapsed := time.Since(t).Seconds()
			if errMax > 1e-14 {
				return fmt.Errorf("score mismatch %s %g", name, errMax)
			}
			maxError = math.Max(maxError, errMax)
			if repeat >= 0 {
				times = append(times, elapsed)
			}
			fmt.Fprintf(os.Stderr, "%s repeat %d: %.3fs\n", name, repeat, elapsed)
		}
		ordered := append([]float64(nil), times...)
		sort.Float64s(ordered)
		med := ordered[2]
		results[name] = sample{times, med, ordered[0], ordered[4], 829440 / med, maxError}
	}
	var memory runtime.MemStats
	runtime.ReadMemStats(&memory)
	for p, h := range hashes {
		after, e := hash(p)
		if e != nil {
			return e
		}
		if after != h {
			return fmt.Errorf("immutable input changed %s", p)
		}
	}
	value := map[string]any{"models": results, "input_sha256": hashes, "read_decode_seconds": readSeconds, "gomaxprocs": 1, "go_version": runtime.Version(), "goos": runtime.GOOS, "goarch": runtime.GOARCH, "alloc_bytes_after": memory.Alloc, "total_alloc_bytes": memory.TotalAlloc, "go_reserved_bytes": memory.Sys, "states": 829440, "window": "D2 08:00-16:00", "fit_performed": false, "note": "validation/error accumulation included consistently for both methods; warmup then five repeats; memory Sys is Go reserved bytes, not peak RSS"}
	data, e := json.MarshalIndent(value, "", "  ")
	if e != nil {
		return e
	}
	f, e := os.OpenFile(*output, os.O_CREATE|os.O_EXCL|os.O_WRONLY, 0600)
	if e != nil {
		return e
	}
	_, e = f.Write(data)
	closeErr := f.Close()
	if e != nil {
		return e
	}
	return closeErr
}
