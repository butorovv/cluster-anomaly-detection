package experiment

import (
	"context"
	"crypto/sha256"
	"encoding/binary"
	"fmt"
	"math"
	"os"
	"reflect"
	"testing"
	"time"

	"cluster-anomaly-detection/internal/analysis"
)

// No instrumentation or alternate mathematics is added to production fitting.
// Data boundaries separate pass time from the intervening exact statistics.
func BenchmarkFitStatisticalAudit(b *testing.B) {
	path := os.Getenv("NIR_AUDIT_PARQUET")
	if path == "" {
		b.Skip("set NIR_AUDIT_PARQUET, NIR_AUDIT_MANIFEST, NIR_AUDIT_PROFILE for read-only D1")
	}
	source, err := OpenSource(path, os.Getenv("NIR_AUDIT_MANIFEST"))
	if err != nil {
		b.Fatal(err)
	}
	want, err := LoadProfile(os.Getenv("NIR_AUDIT_PROFILE"))
	if err != nil {
		b.Fatal(err)
	}
	for _, hashSequence := range []bool{false, true} {
		b.Run(fmt.Sprintf("sequence_sha256=%t", hashSequence), func(b *testing.B) {
			b.ReportAllocs()
			var sums [6]time.Duration
			var fitted *analysis.StatisticalProfile
			b.ResetTimer()
			for iteration := 0; iteration < b.N; iteration++ {
				pass := 0
				last := time.Now()
				var hashes [3][32]byte
				data := func(ctx context.Context, visit func(analysis.Observation) error) error {
					start := time.Now()
					if pass > 0 {
						sums[2*pass-1] += start.Sub(last)
					}
					index := pass
					pass++
					n := 0
					h := sha256.New()
					var encoded [8 * (analysis.Dimensions + 1)]byte
					err := source.TrainingData()(ctx, func(o analysis.Observation) error {
						n++
						if hashSequence {
							binary.LittleEndian.PutUint64(encoded[:8], uint64(o.Timestamp.UnixMicro()))
							for j, value := range o.Features {
								binary.LittleEndian.PutUint64(encoded[8*(j+1):], math.Float64bits(value))
							}
							_, _ = h.Write(encoded[:])
						}
						return visit(o)
					})
					if n != want.Observations {
						b.Fatalf("pass %d observations=%d", pass, n)
					}
					copy(hashes[index][:], h.Sum(nil))
					last = time.Now()
					sums[2*index] += last.Sub(start)
					return err
				}
				fitted, err = analysis.FitStatistical(context.Background(), data, analysis.NIRWindows()[0], want.Config)
				sums[5] += time.Since(last)
				if err != nil {
					b.Fatal(err)
				}
				if pass != 3 || (hashSequence && (hashes[0] != hashes[1] || hashes[1] != hashes[2])) {
					b.Fatal("D1 sequence changed")
				}
				if !reflect.DeepEqual(fitted, want) {
					b.Fatal("historical profile differs: exact parity required")
				}
			}
			b.StopTimer()
			for i, name := range []string{"pass1", "medianMAD", "pass2_normalize_Welford", "covariance_SVD", "pass3_distances", "Q99_validate"} {
				b.ReportMetric(float64(sums[i].Nanoseconds())/float64(b.N), "ns/"+name)
			}
			b.ReportMetric(float64(want.Observations*3), "states/op")
			b.ReportMetric(float64(want.Observations*3*analysis.Dimensions*8), "F18-bytes/op")
			// Outside fit timings: explicitly compare all D1 binary decisions too.
			n, positive := 0, 0
			err = source.TrainingData()(context.Background(), func(o analysis.Observation) error {
				d1, label1, e := fitted.ControlLabel(o.Features)
				if e != nil {
					return e
				}
				d2, label2, e := want.ControlLabel(o.Features)
				if e != nil {
					return e
				}
				if d1 != d2 || label1 != label2 {
					return fmt.Errorf("D1 decision changed")
				}
				n++
				if label1 {
					positive++
				}
				return nil
			})
			if err != nil {
				b.Fatal(err)
			}
			b.Logf("exact historical profile and decisions: states=%d positives=%d rank=%d Q99=%.17g", n, positive, fitted.Rank, fitted.Threshold)
		})
	}
}
