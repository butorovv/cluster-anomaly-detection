// Research-only read-only D2 export using the existing frozen Go profiles.
package main

import (
	"bufio"
	"context"
	"crypto/sha256"
	"encoding/binary"
	"encoding/hex"
	"flag"
	"fmt"
	"io"
	"math"
	"os"
	"os/signal"
	"path/filepath"
	"time"

	"cluster-anomaly-detection/internal/analysis"
	"cluster-anomaly-detection/internal/experiment"
	"cluster-anomaly-detection/internal/modules/telemetry/domain"
)

type metadata struct {
	Version        string                       `json:"version"`
	Source         *experiment.Source           `json:"source"`
	Features       []string                     `json:"features"`
	Audit          experiment.Audit             `json:"audit"`
	Rows           int                          `json:"rows"`
	RecordBytes    int                          `json:"record_bytes"`
	BinarySHA256   string                       `json:"binary_sha256"`
	InputSHA256    map[string]string            `json:"input_sha256"`
	Calibration    *experiment.CalibrationRun   `json:"calibration"`
	Statistical    *analysis.StatisticalProfile `json:"statistical_profile"`
	Physical       *analysis.PhysicalProfile    `json:"physical_profile"`
	ElapsedSeconds float64                      `json:"elapsed_seconds"`
}

func fileHash(path string) (string, error) {
	f, err := os.Open(path)
	if err != nil {
		return "", err
	}
	defer f.Close()
	h := sha256.New()
	if _, err = io.Copy(h, f); err != nil {
		return "", err
	}
	return hex.EncodeToString(h.Sum(nil)), nil
}
func main() {
	if err := run(); err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}
}
func run() error {
	input := flag.String("input", "data/prepared/summit-D1-pilot/D1.parquet", "immutable full-day Parquet")
	manifest := flag.String("manifest", "data/prepared/summit-D1-pilot/manifest.json", "immutable manifest")
	stat := flag.String("statistical-profile", "results/statistical-20220118-8h-v1.json", "frozen D1 statistical profile")
	forest := flag.String("isolation-profile", "results/isolation-20220118-v1.json", "frozen D1 forest")
	physical := flag.String("physical-profile", "results/physical-20220118-v1.json", "frozen D1 physical profile")
	cal := flag.String("calibration", "results/isolation-calibration-20220118-v1.json", "frozen D2 threshold")
	out := flag.String("output", "results/d2-diagnostics-v1", "new diagnostic directory")
	flag.Parse()
	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt)
	defer stop()
	started := time.Now()
	s, err := experiment.OpenSource(*input, *manifest)
	if err != nil {
		return err
	}
	r, err := experiment.LoadIsolationCalibration(*cal, s, *forest, *stat)
	if err != nil {
		return err
	}
	if r.Calibration.Threshold == nil {
		return fmt.Errorf("calibration is undefined")
	}
	i, err := experiment.LoadIsolationProfile(*forest, s, *stat)
	if err != nil {
		return err
	}
	p, err := experiment.LoadProfile(*stat)
	if err != nil {
		return err
	}
	b, err := experiment.LoadPhysicalProfile(*physical, s)
	if err != nil {
		return err
	}
	m := metadata{Version: "d2-research-export-v1", Source: s, Features: append([]string(nil), domain.FeatureNames[:]...), RecordBytes: 176, InputSHA256: map[string]string{}, Calibration: r, Statistical: p, Physical: b}
	for _, path := range []string{*input, *manifest, *stat, *forest, *physical, *cal} {
		h, err := fileHash(path)
		if err != nil {
			return err
		}
		m.InputSHA256[path] = h
	}
	if err = os.MkdirAll(*out, 0700); err != nil {
		return err
	}
	path := filepath.Join(*out, "states.bin")
	f, err := os.OpenFile(path, os.O_WRONLY|os.O_CREATE|os.O_EXCL, 0600)
	if err != nil {
		return err
	}
	defer f.Close()
	w := bufio.NewWriterSize(f, 1<<20)
	hosts := map[string]int{}
	for j, h := range s.Hosts {
		hosts[h] = j
	}
	var conf analysis.ConfusionMatrix
	m.Audit, err = s.Scan(ctx, analysis.NIRWindows()[1], func(v domain.TelemetryRecord) error {
		features := v.Features()
		score, distance := math.NaN(), math.NaN()
		if v.Valid {
			var e error
			score, e = i.Profile.Score(features)
			if e != nil {
				return e
			}
			distance, e = p.DistanceSquared(features)
			if e != nil {
				return e
			}
			positive, control := score > *r.Calibration.Threshold, distance > p.Threshold
			switch {
			case positive && control:
				conf.TP++
			case positive:
				conf.FP++
			case control:
				conf.FN++
			default:
				conf.TN++
			}
		}
		// Fixed little-endian record: int64 unix_us, uint32 host_index,
		// uint32 available, 18 raw float64 F18, float64 score, float64 D².
		var record [176]byte
		binary.LittleEndian.PutUint64(record[:8], uint64(v.Timestamp.UnixMicro()))
		binary.LittleEndian.PutUint32(record[8:12], uint32(hosts[v.Hostname]))
		if v.Valid {
			binary.LittleEndian.PutUint32(record[12:16], 1)
		}
		for j, x := range features {
			binary.LittleEndian.PutUint64(record[16+8*j:24+8*j], math.Float64bits(x))
		}
		binary.LittleEndian.PutUint64(record[160:168], math.Float64bits(score))
		binary.LittleEndian.PutUint64(record[168:176], math.Float64bits(distance))
		_, e := w.Write(record[:])
		m.Rows++
		return e
	})
	if err != nil {
		return err
	}
	if err = w.Flush(); err != nil {
		return err
	}
	if err = f.Close(); err != nil {
		return err
	}
	if m.Audit != r.Audit || conf != r.Calibration.Confusion || m.Rows != 829440 {
		return fmt.Errorf("D2 baseline did not reproduce: %+v", conf)
	}
	for path, h := range m.InputSHA256 {
		current, err := fileHash(path)
		if err != nil {
			return err
		}
		if current != h {
			return fmt.Errorf("immutable input changed: %s", path)
		}
	}
	m.BinarySHA256, err = fileHash(path)
	if err != nil {
		return err
	}
	m.ElapsedSeconds = time.Since(started).Seconds()
	if err = experiment.SaveNew(filepath.Join(*out, "metadata.json"), m); err != nil {
		return err
	}
	fmt.Printf("D2 export: states=%d bytes=%d confusion=%+v elapsed=%.3fs\n", m.Rows, m.Rows*m.RecordBytes, conf, m.ElapsedSeconds)
	return nil
}
