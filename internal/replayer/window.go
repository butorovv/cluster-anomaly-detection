package replayer

import (
	"context"
	"fmt"
	"time"

	"cluster-anomaly-detection/internal/modules/telemetry/domain"
)

// WindowReader filters the existing prepared Parquet at read time. It preserves
// missingness and checks order/duplicates even in skipped rows. No new file is made.
type WindowReader struct {
	Source     RecordReader
	Start, End time.Time
	previous   domain.TelemetryRecord
	seen       bool
}

func (r *WindowReader) Next(ctx context.Context) (domain.TelemetryRecord, error) {
	if r.Source == nil || r.Start.IsZero() || !r.End.After(r.Start) {
		return domain.TelemetryRecord{}, fmt.Errorf("invalid reader window")
	}
	for {
		v, err := r.Source.Next(ctx)
		if err != nil {
			return v, err
		}
		if r.seen && compareRecords(r.previous, v) >= 0 {
			return domain.TelemetryRecord{}, fmt.Errorf("non-increasing source key in window reader")
		}
		r.previous, r.seen = v, true
		if !v.Timestamp.Before(r.Start) && v.Timestamp.Before(r.End) {
			return v, nil
		}
	}
}
