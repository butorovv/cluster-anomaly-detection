package replayer

import (
	"context"
	"errors"
	"io"
	"os"
	"path/filepath"
	"reflect"
	"testing"
	"time"

	"cluster-anomaly-detection/internal/modules/telemetry/domain"
	"github.com/parquet-go/parquet-go"
)

type windowFixture struct {
	rows []domain.TelemetryRecord
	i    int
}

func (f *windowFixture) Next(context.Context) (domain.TelemetryRecord, error) {
	if f.i == len(f.rows) {
		return domain.TelemetryRecord{}, io.EOF
	}
	v := f.rows[f.i]
	f.i++
	return v, nil
}

func TestWindowReaderHalfOpenOrderMissingAndCancellation(t *testing.T) {
	start := time.Date(2022, 1, 18, 8, 0, 0, 0, time.UTC)
	var rows []domain.TelemetryRecord
	for _, offset := range []time.Duration{-10 * time.Second, 0, 10 * time.Second, 20 * time.Second} {
		v := fixtureRecord(0, "a01n01")
		v.Timestamp = start.Add(offset)
		rows = append(rows, v)
	}
	r := WindowReader{Source: &windowFixture{rows: rows}, Start: start, End: start.Add(20 * time.Second)}
	for _, offset := range []time.Duration{0, 10 * time.Second} {
		v, err := r.Next(context.Background())
		if err != nil || !v.Timestamp.Equal(start.Add(offset)) {
			t.Fatal(v, err)
		}
	}
	if _, err := r.Next(context.Background()); !errors.Is(err, io.EOF) {
		t.Fatal(err)
	}
	r = WindowReader{Source: &windowFixture{rows: []domain.TelemetryRecord{rows[0], rows[0]}}, Start: start, End: start.Add(time.Hour)}
	if _, err := r.Next(context.Background()); err == nil {
		t.Fatal("duplicate in skipped range accepted")
	}
}

func TestWindowReaderStopsAtExcludedEnd(t *testing.T) {
	start := time.Date(2022, 1, 18, 0, 0, 0, 0, time.UTC)
	var rows []domain.TelemetryRecord
	for _, offset := range []time.Duration{0, 10 * time.Second, 20 * time.Second, 30 * time.Second} {
		v := fixtureRecord(0, "a01n01")
		v.Timestamp = start.Add(offset)
		rows = append(rows, v)
	}
	source := &windowFixture{rows: rows}
	r := WindowReader{Source: source, Start: start, End: start.Add(20 * time.Second)}
	for i := 0; i < 2; i++ {
		if _, err := r.Next(context.Background()); err != nil {
			t.Fatal(err)
		}
	}
	for i := 0; i < 2; i++ {
		if _, err := r.Next(context.Background()); !errors.Is(err, io.EOF) {
			t.Fatal(err)
		}
	}
	if source.i != 3 {
		t.Fatal("traversed held-out suffix", source.i)
	}
}

func TestWindowReaderOnPreparedParquet(t *testing.T) {
	row := parquetFixtureRow()
	path := writeFixture(t, row, true)
	raw, err := OpenParquet(path)
	if err != nil {
		t.Fatal(err)
	}
	defer raw.Close()
	start := time.UnixMicro(row.Timestamp).UTC()
	r := WindowReader{Source: raw, Start: start, End: start.Add(10 * time.Second)}
	v, err := r.Next(context.Background())
	if err != nil || v.Features()[17] != 18 {
		t.Fatal(v, err)
	}
	ctx, cancel := context.WithCancel(context.Background())
	cancel()
	if _, err := r.Next(ctx); !errors.Is(err, context.Canceled) {
		t.Fatal(err)
	}
}

// Real-time boundaries are tested with one small synthetic prepared file;
// no extra day or interval Parquet is generated outside the test tempdir.
func TestParquetThreeWindows(t *testing.T) {
	start := time.Date(2022, 1, 18, 0, 0, 0, 0, time.UTC)
	var rows []preparedRow
	for _, seconds := range []int{0, 8*3600 - 10, 8 * 3600, 16*3600 - 10, 16 * 3600, 24*3600 - 10} {
		r := parquetFixtureRow()
		r.Timestamp = start.Add(time.Duration(seconds) * time.Second).UnixMicro()
		rows = append(rows, r)
	}
	path := filepath.Join(t.TempDir(), "windows.parquet")
	f, err := os.Create(path)
	if err != nil {
		t.Fatal(err)
	}
	w := parquet.NewGenericWriter[preparedRow](f, parquet.KeyValueMetadata("schema_version", PreparedSchemaVersion))
	if _, err := w.Write(rows); err != nil {
		t.Fatal(err)
	}
	if err := w.Close(); err != nil {
		t.Fatal(err)
	}
	if err := f.Close(); err != nil {
		t.Fatal(err)
	}
	for i := 0; i < 3; i++ {
		raw, err := OpenParquet(path)
		if err != nil {
			t.Fatal(err)
		}
		r := WindowReader{Source: raw, Start: start.Add(time.Duration(i) * 8 * time.Hour), End: start.Add(time.Duration(i+1) * 8 * time.Hour)}
		for j := 0; j < 2; j++ {
			v, err := r.Next(context.Background())
			if err != nil || v.Timestamp.UnixMicro() != rows[2*i+j].Timestamp {
				t.Fatal(i, j, v, err)
			}
		}
		if _, err := r.Next(context.Background()); !errors.Is(err, io.EOF) {
			t.Fatal(err)
		}
		if err := raw.Close(); err != nil {
			t.Fatal(err)
		}
	}
}

func TestFilteredReplayCompletesLastAllowedTimestamp(t *testing.T) {
	start := time.Date(2022, 1, 18, 8, 0, 0, 0, time.UTC)
	var rows []domain.TelemetryRecord
	for _, offset := range []time.Duration{-10 * time.Second, 0, 10 * time.Second, 20 * time.Second} {
		for _, host := range []string{"a01n01", "a01n02", "a02n01"} {
			v := fixtureRecord(0, host)
			v.Timestamp = start.Add(offset)
			rows = append(rows, v)
		}
	}
	r := WindowReader{Source: &sliceReader{records: rows}, Start: start, End: start.Add(20 * time.Second)}
	sender := &captureSender{}
	stats, err := Replay(context.Background(), &r, sender, sender, &fakeClock{}, 0)
	if err != nil {
		t.Fatal(err)
	}
	if !reflect.DeepEqual(sender.records, rows[3:9]) || stats.Rows != 6 || stats.Completions != 4 {
		t.Fatal(stats, sender.records)
	}
	want := []TimestampComplete{{start, "a01", 2, 2}, {start, "a02", 1, 1}, {start.Add(10 * time.Second), "a01", 2, 2}, {start.Add(10 * time.Second), "a02", 1, 1}}
	if !reflect.DeepEqual(sender.complete, want) {
		t.Fatal(sender.complete)
	}
}
