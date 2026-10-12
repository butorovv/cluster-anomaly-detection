package usecase

import (
	"context"
	"time"

	"cluster-anomaly-detection/internal/modules/telemetry/domain"
)

// HistoryRepository returns F18 at a requested logical timestamp.
// Individual CPU-core availability counts are not stored in the canonical database.
type HistoryRepository interface {
	RecordAt(context.Context, int, time.Time) (domain.TelemetryRecord, error)
}
