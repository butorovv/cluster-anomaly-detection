package repository

import (
	"context"
	"fmt"
	"math"
	"time"

	"cluster-anomaly-detection/internal/modules/telemetry/domain"
	"cluster-anomaly-detection/internal/modules/telemetry/usecase"
	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgtype"
	"github.com/jackc/pgx/v5/pgxpool"
)

type PostgresHistory struct{ pool *pgxpool.Pool }

var _ usecase.HistoryRepository = (*PostgresHistory)(nil)

func NewPostgresHistory(pool *pgxpool.Pool) *PostgresHistory { return &PostgresHistory{pool: pool} }

// RecordAt reconstructs the F18 vector, retaining null coordinates as NaN.
func (r *PostgresHistory) RecordAt(ctx context.Context, nodeID int, timestamp time.Time) (domain.TelemetryRecord, error) {
	rows, err := r.pool.Query(ctx, `
		SELECT n.hostname,g.code,n.node_index,ms.source_key,t.value::double precision
		FROM project.node n
		JOIN project.node_group g ON g.id=n.node_group_id
		JOIN project.component c ON c.node_id=n.id
		JOIN project.metric_source ms ON ms.component_id=c.id
		LEFT JOIN project.telemetry t ON t.metric_source_id=ms.id AND t.ts=$2
		WHERE n.id=$1`, nodeID, timestamp)
	if err != nil {
		return domain.TelemetryRecord{}, err
	}
	defer rows.Close()
	record := domain.TelemetryRecord{Timestamp: timestamp.UTC()}
	var values [domain.FeatureCount]float64
	for i := range values {
		values[i] = math.NaN()
	}
	seen := map[string]bool{}
	for rows.Next() {
		var key string
		var value pgtype.Float8
		if err := rows.Scan(&record.Hostname, &record.GroupID, &record.NodeIndex, &key, &value); err != nil {
			return domain.TelemetryRecord{}, err
		}
		index := -1
		for i, name := range domain.FeatureNames {
			if name == key {
				index = i
				break
			}
		}
		if index < 0 || seen[key] {
			return domain.TelemetryRecord{}, fmt.Errorf("incompatible F18 source_key: %s", key)
		}
		seen[key] = true
		if value.Valid {
			values[index] = value.Float64
			record.AvailabilityMask |= 1 << index
		}
	}
	if err := rows.Err(); err != nil {
		return domain.TelemetryRecord{}, err
	}
	if len(seen) == 0 {
		return domain.TelemetryRecord{}, pgx.ErrNoRows
	}
	if len(seen) != domain.FeatureCount {
		return domain.TelemetryRecord{}, fmt.Errorf("node %d has %d F18 sources, expected 18", nodeID, len(seen))
	}
	record.SetFeatures(values)
	record.Valid = record.AvailabilityMask == domain.FullAvailabilityMask
	return record, record.Validate()
}
