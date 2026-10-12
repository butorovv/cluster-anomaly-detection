package experiment

import (
	"context"
	"encoding/json"
	"fmt"
	"math"
	"os"
	"path/filepath"
	"reflect"
	"testing"
	"time"

	"cluster-anomaly-detection/internal/analysis"
	"cluster-anomaly-detection/internal/modules/telemetry/domain"
	"cluster-anomaly-detection/internal/replayer"
	"gonum.org/v1/gonum/mat"
)

// This opt-in integration test reads the existing day without producing Parquet.
// An explicitly selected but inaccessible input fails; it is never skipped.
func TestRealPreparedDayWindows(t *testing.T) {
	path := os.Getenv("NIR_REAL_PARQUET")
	if path == "" {
		t.Skip("NIR_REAL_PARQUET not set: real day integration not executed")
	}
	s, err := OpenSource(path, filepath.Join(filepath.Dir(path), "manifest.json"))
	if err != nil {
		t.Fatal(err)
	}
	var previousEnd time.Time
	for i, w := range analysis.NIRWindows() {
		t.Run(fmt.Sprintf("D%d", i+1), func(t *testing.T) {
			raw, err := replayer.OpenParquet(s.Path)
			if err != nil {
				t.Fatal(err)
			}
			if raw.Rows() != 2488320 {
				t.Fatal("day row count", raw.Rows())
			}
			defer func() {
				if err := raw.Close(); err != nil {
					t.Error(err)
				}
			}()
			sink := &windowAuditSink{t: t, source: s, window: w}
			r := &replayer.WindowReader{Source: raw, Start: w.Start, End: w.End}
			stats, err := replayer.Replay(context.Background(), r, sink, sink, replayer.RealClock{}, 0)
			if err != nil {
				t.Fatal(err)
			}
			if stats.Rows != 829440 || stats.Timestamps != 2880 || stats.Completions != 46080 || stats.Hosts != 288 || stats.Groups != 16 || stats.Invalid != 0 {
				t.Fatalf("unexpected window stats: %+v", stats)
			}
			if !sink.first.Equal(w.Start) || !sink.last.Equal(w.End.Add(-analysis.Step)) || (!previousEnd.IsZero() && !sink.first.After(previousEnd)) {
				t.Fatalf("incorrect half-open boundaries/overlap: %s .. %s", sink.first, sink.last)
			}
			previousEnd = sink.last
			t.Logf("%s .. %s: %+v", sink.first, sink.last, stats)
		})
	}
}

// NIR_REAL_ORIGINAL is the stdout envelope from the same successful cmd/nir run.
// Compare all persisted parameters and recalculate inference at fixed D1 rows.
func TestRealStatisticalProfileReload(t *testing.T) {
	path, profilePath, originalPath := os.Getenv("NIR_REAL_PARQUET"), os.Getenv("NIR_REAL_PROFILE"), os.Getenv("NIR_REAL_ORIGINAL")
	if path == "" || profilePath == "" || originalPath == "" {
		t.Skip("NIR_REAL_PARQUET/PROFILE/ORIGINAL not set: real profile reload not executed")
	}
	loaded, err := LoadProfile(profilePath)
	if err != nil {
		t.Fatal(err)
	}
	b, err := os.ReadFile(originalPath)
	if err != nil {
		t.Fatal(err)
	}
	var original StatisticalRun
	if err := json.Unmarshal(b, &original); err != nil {
		t.Fatal(err)
	}
	if err := original.Profile.Validate(); err != nil {
		t.Fatal(err)
	}
	if !reflect.DeepEqual(original.Profile, loaded) || loaded.Observations != 829440 || loaded.Config != (analysis.StatisticalConfig{SVDRCond: 1e-12, CovarianceDDOF: 1}) {
		t.Fatal("real profile differs after persistence or has incorrect training count/conventions")
	}
	s, err := OpenSource(path, filepath.Join(filepath.Dir(path), "manifest.json"))
	if err != nil {
		t.Fatal(err)
	}
	if original.Source == nil || original.Source.SHA256 != s.SHA256 {
		t.Fatal("profile/source checksum mismatch")
	}
	before := *loaded
	indices := []int{0, 17, 18, 287, 288, 10000, 100000, 200000, 300000, 414720, 500000, 600000, 700000, 800000, 829422, 829439}
	row, sample := 0, 0
	audit, err := s.Scan(context.Background(), analysis.NIRWindows()[0], func(v domain.TelemetryRecord) error {
		if sample < len(indices) && row == indices[sample] {
			wantZ, err := original.Profile.Normalize(v.Features())
			if err != nil {
				return err
			}
			gotZ, err := loaded.Normalize(v.Features())
			if err != nil || wantZ != gotZ {
				t.Fatal("normalization changed after load", row, err)
			}
			wantD, wantLabel, err := original.Profile.ControlLabel(v.Features())
			if err != nil {
				return err
			}
			gotD, gotLabel, err := loaded.ControlLabel(v.Features())
			if err != nil || gotD != wantD || gotLabel != wantLabel {
				t.Fatal("distance/label changed after load", row, err)
			}
			t.Logf("sample row=%d %s/%s: D²=%.17g label=%t", row, v.Timestamp.Format(time.RFC3339), v.Hostname, gotD, gotLabel)
			sample++
		}
		row++
		return nil
	})
	if err != nil || sample != len(indices) || audit.States != 829440 || audit.Valid != loaded.Observations || before != *loaded {
		t.Fatal("real reload verification failed", sample, audit, err)
	}
	cov := mat.NewDense(analysis.Dimensions, analysis.Dimensions, nil)
	inverse := mat.NewDense(analysis.Dimensions, analysis.Dimensions, nil)
	for i := 0; i < analysis.Dimensions; i++ {
		for j := 0; j < analysis.Dimensions; j++ {
			cov.Set(i, j, loaded.Covariance[i][j])
			inverse.Set(i, j, loaded.PseudoInverse[i][j])
		}
	}
	var svd mat.SVD
	if !svd.Factorize(cov, mat.SVDFull) || svd.Rank(1e-12) != loaded.Rank {
		t.Fatal("real covariance SVD failed")
	}
	values := svd.Values(nil)
	var product, recovered, residual mat.Dense
	product.Mul(cov, inverse)
	recovered.Mul(&product, cov)
	residual.Sub(&recovered, cov)
	relativeResidual := mat.Norm(&residual, 2) / mat.Norm(cov, 2)
	if !analysis.Finite(relativeResidual) || relativeResidual > 1e-10 {
		t.Fatal("real Moore-Penrose identity residual", relativeResidual)
	}
	expectedMean := float64(loaded.Rank) * float64(loaded.Observations-1) / float64(loaded.Observations)
	if math.Abs(original.Windows[0].DistanceMean-expectedMean) > 1e-9 {
		t.Fatal("D1 distance mean inconsistent with rank/ddof", original.Windows[0].DistanceMean, expectedMean)
	}
	t.Logf("reload: all parameters exact; %d fixed rows exact; rank=%d sigma_max=%.17g sigma_min=%.17g condition=%.17g MP_relative_residual=%.17g", sample, loaded.Rank, values[0], values[len(values)-1], values[0]/values[len(values)-1], relativeResidual)
}

type windowAuditSink struct {
	t           *testing.T
	source      *Source
	window      analysis.Window
	first, last time.Time
}

func (s *windowAuditSink) Send(_ context.Context, v domain.TelemetryRecord) error {
	if !s.window.Contains(v.Timestamp) || !s.source.hosts[v.Hostname] || !analysis.FiniteVector(v.Features()) || v.Timestamp.Sub(s.window.Start)%analysis.Step != 0 {
		s.t.Fatalf("unexpected real state: %s/%s", v.Timestamp, v.Hostname)
	}
	if s.first.IsZero() {
		s.first = v.Timestamp
	}
	s.last = v.Timestamp
	return nil
}

func (s *windowAuditSink) Complete(_ context.Context, v replayer.TimestampComplete) error {
	if !s.window.Contains(v.Timestamp) || v.Records != 18 || v.ValidRecords != 18 {
		s.t.Fatalf("unexpected real completion: %+v", v)
	}
	return nil
}
