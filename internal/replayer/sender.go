package replayer

import (
	"context"
	"encoding/json"
	"io"
	"log/slog"
	"math"
	"time"

	"cluster-anomaly-detection/internal/modules/telemetry/domain"
)

type LogSender struct{ Logger *slog.Logger }

func (s LogSender) Send(ctx context.Context, r domain.TelemetryRecord) error {
	if err := ctx.Err(); err != nil {
		return err
	}
	s.Logger.DebugContext(ctx, "telemetry record", "timestamp", r.Timestamp, "group", r.GroupID, "host", r.Hostname, "valid", r.Valid, "availability_mask", r.AvailabilityMask, "f18", r.Features())
	return nil
}
func (s LogSender) Complete(ctx context.Context, c TimestampComplete) error {
	if err := ctx.Err(); err != nil {
		return err
	}
	s.Logger.DebugContext(ctx, "timestamp complete", "timestamp", c.Timestamp, "group", c.GroupID, "records", c.Records, "valid_records", c.ValidRecords)
	return nil
}

type JSONSender struct{ encoder *json.Encoder }

func NewJSONSender(w io.Writer) *JSONSender { return &JSONSender{encoder: json.NewEncoder(w)} }

func (s *JSONSender) Send(ctx context.Context, r domain.TelemetryRecord) error {
	if err := ctx.Err(); err != nil {
		return err
	}
	var values [domain.FeatureCount]*float64
	for i, v := range r.Features() {
		if !math.IsNaN(v) && !math.IsInf(v, 0) {
			value := v
			values[i] = &value
		}
	}
	return s.encoder.Encode(struct {
		Type             string                        `json:"type"`
		Timestamp        time.Time                     `json:"timestamp"`
		Hostname         string                        `json:"hostname"`
		GroupID          string                        `json:"group_id"`
		NodeIndex        int                           `json:"node_index"`
		F18              [domain.FeatureCount]*float64 `json:"f18"`
		Valid            bool                          `json:"is_valid"`
		AvailabilityMask uint32                        `json:"availability_mask"`
	}{"telemetry", r.Timestamp, r.Hostname, r.GroupID, r.NodeIndex, values, r.Valid, r.AvailabilityMask})
}
func (s *JSONSender) Complete(ctx context.Context, c TimestampComplete) error {
	if err := ctx.Err(); err != nil {
		return err
	}
	return s.encoder.Encode(struct {
		Type string `json:"type"`
		TimestampComplete
	}{"timestamp_complete", c})
}
