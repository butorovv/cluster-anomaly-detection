// Command export creates the host-context forest comparison and fixed binary
// D1/D2 score exports. It never reads D3.
package main

import (
	"bufio"
	"context"
	"crypto/sha256"
	"encoding/binary"
	"encoding/hex"
	"flag"
	"fmt"
	"hash"
	"io"
	"math"
	"os"
	"path/filepath"
	"slices"
	"time"

	"cluster-anomaly-detection/internal/analysis"
	"cluster-anomaly-detection/internal/experiment"
	"cluster-anomaly-detection/internal/modules/telemetry/domain"
	"cluster-anomaly-detection/tools/context/model"
)

type savedForest struct {
	Source               *experiment.Source              `json:"source"`
	StatisticalReference experiment.StatisticalReference `json:"statistical_reference"`
	Context              *model.ContextProfile           `json:"context_profile,omitempty"`
	Forest               *analysis.IsolationForest       `json:"isolation_forest"`
}
type row struct {
	rec      domain.TelemetryRecord
	host     uint32
	distance float64
}
type timing struct {
	TrainingSeconds   float64 `json:"training_seconds"`
	TrainingTimeBasis string  `json:"training_time_basis"`
	MedianFitSeconds  float64 `json:"median_fit_seconds"`
	D1ScoreSeconds    float64 `json:"d1_score_seconds"`
	D2ScoreSeconds    float64 `json:"d2_score_seconds"`
	SerializedBytes   int64   `json:"serialized_bytes"`
}
type metadata struct {
	Source           *experiment.Source    `json:"source"`
	Features         []string              `json:"feature_order"`
	D1Audit          experiment.Audit      `json:"d1_audit"`
	D2Audit          experiment.Audit      `json:"d2_audit"`
	RecordBytes      int                   `json:"record_bytes"`
	ScoreOrder       []string              `json:"score_order"`
	InputSHA256      map[string]string     `json:"input_sha256_before"`
	InputSHA256After map[string]string     `json:"input_sha256_after"`
	BinarySHA256     map[string]string     `json:"binary_sha256"`
	Timing           map[string]timing     `json:"timing"`
	ContextProfile   *model.ContextProfile `json:"context_profile"`
}
type recordWriter struct {
	f *os.File
	w *bufio.Writer
	h hash.Hash
	n int
}

func (s *savedForest) Validate() error {
	if s == nil || s.Source == nil || s.Forest == nil {
		return fmt.Errorf("incomplete context forest envelope")
	}
	if err := s.Forest.Validate(); err != nil {
		return err
	}
	if s.StatisticalReference.SHA256 == "" || s.StatisticalReference.Version == "" {
		return fmt.Errorf("missing statistical profile linkage")
	}
	if s.Context != nil {
		if err := s.Context.ValidateLink(s.Source.SHA256, s.StatisticalReference.SHA256); err != nil {
			return err
		}
		if !slices.Equal(s.Context.Hosts, s.Source.Hosts) || s.Context.GlobalMedian != s.Forest.Median || s.Context.GlobalScale != s.Forest.Scale {
			return fmt.Errorf("context host order or forest normalization mismatch")
		}
	}
	return nil
}

func newWriter(path string) (*recordWriter, error) {
	f, e := os.OpenFile(path, os.O_CREATE|os.O_EXCL|os.O_WRONLY, 0600)
	if e != nil {
		return nil, e
	}
	return &recordWriter{f: f, w: bufio.NewWriterSize(f, 1<<20), h: sha256.New()}, nil
}
func (w *recordWriter) put(b []byte) error {
	if _, e := w.w.Write(b); e != nil {
		return e
	}
	_, _ = w.h.Write(b)
	return nil
}
func (w *recordWriter) close() (string, error) {
	e := w.w.Flush()
	if e == nil {
		e = w.f.Sync()
	}
	ce := w.f.Close()
	if e == nil {
		e = ce
	}
	return hex.EncodeToString(w.h.Sum(nil)), e
}
func (w *recordWriter) write(r row, scores []float64) error {
	if len(scores) != 6 {
		return fmt.Errorf("context export requires six ordered scores")
	}
	var b [216]byte
	binary.LittleEndian.PutUint64(b[0:8], uint64(r.rec.Timestamp.UnixMicro()))
	binary.LittleEndian.PutUint32(b[8:12], r.host)
	binary.LittleEndian.PutUint32(b[12:16], r.rec.AvailabilityMask)
	off := 16
	for _, x := range r.rec.Features() {
		binary.LittleEndian.PutUint64(b[off:off+8], math.Float64bits(x))
		off += 8
	}
	for _, x := range scores {
		binary.LittleEndian.PutUint64(b[off:off+8], math.Float64bits(x))
		off += 8
	}
	binary.LittleEndian.PutUint64(b[off:off+8], math.Float64bits(r.distance))
	if e := w.put(b[:]); e != nil {
		return e
	}
	w.n++
	return nil
}
func fileHash(path string) (string, error) {
	f, e := os.Open(path)
	if e != nil {
		return "", e
	}
	defer f.Close()
	h := sha256.New()
	if _, e = io.Copy(h, f); e != nil {
		return "", e
	}
	return hex.EncodeToString(h.Sum(nil)), nil
}
func main() {
	if e := run(); e != nil {
		fmt.Fprintln(os.Stderr, e)
		os.Exit(1)
	}
}
func run() error {
	input := flag.String("input", "data/prepared/summit-D1-pilot/D1.parquet", "prepared source")
	manifest := flag.String("manifest", "data/prepared/summit-D1-pilot/manifest.json", "prepared manifest")
	statPath := flag.String("statistical-profile", "results/statistical-20220118-8h-v1.json", "frozen D1 statistical profile")
	a0Path := flag.String("a0-profile", "results/isolation-20220118-v1.json", "frozen A0 D1 forest")
	out := flag.String("output-dir", "results/context-v1", "new output directory")
	flag.Parse()
	ctx := context.Background()
	src, e := experiment.OpenSource(*input, *manifest)
	if e != nil {
		return e
	}
	stat, e := experiment.LoadProfile(*statPath)
	if e != nil {
		return e
	}
	a0run, e := experiment.LoadIsolationProfile(*a0Path, src, *statPath)
	if e != nil {
		return e
	}
	immutable := []string{*input, *manifest, *statPath, *a0Path, "results/physical-20220118-v1.json", "results/isolation-calibration-20220118-v1.json"}
	before := map[string]string{}
	for _, p := range immutable {
		h, err := fileHash(p)
		if err != nil {
			return fmt.Errorf("hash immutable input %s: %w", p, err)
		}
		before[p] = h
	}
	ids := map[string]uint32{}
	for i, h := range src.Hosts {
		ids[h] = uint32(i)
	}
	d1 := make([]row, 0, 829440)
	d1audit, e := src.Scan(ctx, analysis.NIRWindows()[0], func(r domain.TelemetryRecord) error {
		id, ok := ids[r.Hostname]
		if !ok {
			return fmt.Errorf("unknown D1 host")
		}
		d := math.NaN()
		if r.Valid {
			var err error
			d, err = stat.DistanceSquared(r.Features())
			if err != nil {
				return err
			}
		}
		d1 = append(d1, row{r, id, d})
		return nil
	})
	if e != nil {
		return e
	}
	if err := completeAudit(d1audit); err != nil {
		return err
	}
	if d1audit.Valid != stat.Observations {
		return fmt.Errorf("D1 valid count differs from frozen global profile")
	}
	medianStart := time.Now()
	cp, e := model.FitContextProfile(records(d1), src.Hosts, stat)
	if e != nil {
		return e
	}
	statHash, e := fileHash(*statPath)
	if e != nil {
		return e
	}
	cp.SourceSHA256, cp.GlobalProfileSHA256 = src.SHA256, statHash
	if e = cp.ValidateLink(src.SHA256, statHash); e != nil {
		return e
	}
	medianFitSeconds := time.Since(medianStart).Seconds()
	cfg := analysis.DefaultIsolationConfig()
	forests := map[string]*analysis.IsolationForest{"a0-42": a0run.Profile}
	a0Info, e := os.Stat(*a0Path)
	if e != nil {
		return e
	}
	times := map[string]timing{"a0-42": {MedianFitSeconds: medianFitSeconds, TrainingSeconds: a0run.Resources.TrainingSeconds, TrainingTimeBasis: "saved A0 baseline metadata", SerializedBytes: a0Info.Size()}}
	for _, seed := range []int64{42, 43, 44} {
		name := fmt.Sprintf("b2-%d", seed)
		t := time.Now()
		f, err := analysis.FitIsolation(ctx, adaptedData(d1, cp), stat, analysis.NIRWindows()[0], analysis.IsolationConfig{Trees: cfg.Trees, SampleSize: cfg.SampleSize, MaxDepth: cfg.MaxDepth, Seed: seed})
		if err != nil {
			return err
		}
		forests[name] = f
		times[name] = timing{TrainingSeconds: time.Since(t).Seconds(), TrainingTimeBasis: "current export run", MedianFitSeconds: medianFitSeconds}
		if seed != 42 {
			name = fmt.Sprintf("a0-%d", seed)
			t = time.Now()
			f, err = analysis.FitIsolation(ctx, rawData(d1), stat, analysis.NIRWindows()[0], analysis.IsolationConfig{Trees: cfg.Trees, SampleSize: cfg.SampleSize, MaxDepth: cfg.MaxDepth, Seed: seed})
			if err != nil {
				return err
			}
			forests[name] = f
			times[name] = timing{TrainingSeconds: time.Since(t).Seconds(), TrainingTimeBasis: "current export run", MedianFitSeconds: medianFitSeconds}
		}
	}
	if e = os.MkdirAll(*out, 0700); e != nil {
		return e
	}
	if e = experiment.SaveNew(filepath.Join(*out, "context-profile.json"), cp); e != nil {
		return e
	}
	for _, name := range []string{"b2-42", "a0-43", "b2-43", "a0-44", "b2-44"} {
		env := savedForest{Source: src, StatisticalReference: experiment.StatisticalReference{Path: *statPath, SHA256: statHash, Version: stat.Version}, Forest: forests[name]}
		if name[:2] == "b2" {
			env.Context = cp
		}
		if e = env.Validate(); e != nil {
			return e
		}
		path := filepath.Join(*out, name+".json")
		if e = experiment.SaveNew(path, env); e != nil {
			return e
		}
		st, _ := os.Stat(path)
		times[name] = timing{TrainingSeconds: times[name].TrainingSeconds, TrainingTimeBasis: times[name].TrainingTimeBasis, MedianFitSeconds: medianFitSeconds, SerializedBytes: st.Size()}
	}
	names := []string{"a0-42", "b2-42", "a0-43", "b2-43", "a0-44", "b2-44"}
	d1Scores := make([][]float64, len(d1))
	for i, r := range d1 {
		d1Scores[i] = make([]float64, len(names))
		for j := range d1Scores[i] {
			d1Scores[i][j] = math.NaN()
		}
		if !r.rec.Valid {
			continue
		}
		for j, n := range names {
			t := time.Now()
			v := r.rec.Features()
			if n[:2] == "b2" {
				v, e = cp.Adapt(r.rec.Hostname, v)
				if e != nil {
					return e
				}
			}
			d1Scores[i][j], e = forests[n].Score(v)
			tv := times[n]
			tv.D1ScoreSeconds += time.Since(t).Seconds()
			times[n] = tv
			if e != nil {
				return e
			}
		}
	}
	writer, e := newWriter(filepath.Join(*out, "D1.bin"))
	if e != nil {
		return e
	}
	for i, r := range d1 {
		if e = writer.write(r, d1Scores[i]); e != nil {
			return e
		}
	}
	d1hash, e := writer.close()
	if e != nil {
		return e
	}
	writer, e = newWriter(filepath.Join(*out, "D2.bin"))
	if e != nil {
		return e
	}
	d2audit, e := src.Scan(ctx, analysis.NIRWindows()[1], func(r domain.TelemetryRecord) error {
		id, ok := ids[r.Hostname]
		if !ok {
			return fmt.Errorf("unknown D2 host")
		}
		var scores []float64
		d := math.NaN()
		if r.Valid {
			d, e = stat.DistanceSquared(r.Features())
			if e != nil {
				return e
			}
			scores = make([]float64, len(names))
			for j, n := range names {
				t := time.Now()
				v := r.Features()
				if n[:2] == "b2" {
					v, e = cp.Adapt(r.Hostname, v)
					if e != nil {
						return e
					}
				}
				scores[j], e = forests[n].Score(v)
				tv := times[n]
				tv.D2ScoreSeconds += time.Since(t).Seconds()
				times[n] = tv
				if e != nil {
					return e
				}
			}
		} else {
			scores = make([]float64, len(names))
			for j := range scores {
				scores[j] = math.NaN()
			}
		}
		return writer.write(row{r, id, d}, scores)
	})
	if e != nil {
		return e
	}
	if err := completeAudit(d2audit); err != nil {
		return err
	}
	d2hash, e := writer.close()
	if e != nil {
		return e
	}
	after := map[string]string{}
	for p, h := range before {
		v, er := fileHash(p)
		if er != nil {
			return er
		}
		after[p] = v
		if v != h {
			return fmt.Errorf("immutable input changed: %s", p)
		}
	}
	return experiment.SaveNew(filepath.Join(*out, "metadata.json"), metadata{src, append([]string(nil), domain.FeatureNames[:]...), d1audit, d2audit, 216, names, before, after, map[string]string{"D1.bin": d1hash, "D2.bin": d2hash}, times, cp})
}
func records(rs []row) []domain.TelemetryRecord {
	v := make([]domain.TelemetryRecord, 0, len(rs))
	for _, r := range rs {
		if r.rec.Valid {
			v = append(v, r.rec)
		}
	}
	return v
}
func completeAudit(a experiment.Audit) error {
	if a.States != 829440 || a.Valid != 829440 || a.Timestamps != 2880 || a.Hosts != 288 || a.MinimumStatesPerTimestamp != 288 {
		return fmt.Errorf("incomplete context export window audit: %+v", a)
	}
	return nil
}
func rawData(rs []row) analysis.Data {
	return func(ctx context.Context, visit func(analysis.Observation) error) error {
		for _, r := range rs {
			if !r.rec.Valid {
				continue
			}
			if e := ctx.Err(); e != nil {
				return e
			}
			if e := visit(analysis.Observation{Timestamp: r.rec.Timestamp, Features: r.rec.Features()}); e != nil {
				return e
			}
		}
		return nil
	}
}
func adaptedData(rs []row, p *model.ContextProfile) analysis.Data {
	return func(ctx context.Context, visit func(analysis.Observation) error) error {
		for _, r := range rs {
			if !r.rec.Valid {
				continue
			}
			if e := ctx.Err(); e != nil {
				return e
			}
			v, e := p.Adapt(r.rec.Hostname, r.rec.Features())
			if e != nil {
				return e
			}
			if e = visit(analysis.Observation{Timestamp: r.rec.Timestamp, Features: v}); e != nil {
				return e
			}
		}
		return nil
	}
}
