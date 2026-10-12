package repository

import (
	"context"
	"crypto/rand"
	"encoding/hex"
	"math"
	"os"
	"path/filepath"
	"testing"
	"time"

	"cluster-anomaly-detection/internal/modules/telemetry/domain"
	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"
)

func TestPostgresHistoryWithCanonicalSchema(t *testing.T) {
	url := os.Getenv("TEST_DATABASE_URL")
	if url == "" {
		t.Skip("TEST_DATABASE_URL not set: PostgreSQL adapter integration not executed")
	}
	ctx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
	defer cancel()
	admin, err := pgx.Connect(ctx, url)
	if err != nil {
		t.Fatal(err)
	}
	defer admin.Close(context.Background())
	var suffix [8]byte
	if _, err := rand.Read(suffix[:]); err != nil {
		t.Fatal(err)
	}
	name := "kr_go_test_" + hex.EncodeToString(suffix[:])
	quoted := pgx.Identifier{name}.Sanitize()
	if _, err := admin.Exec(ctx, "CREATE DATABASE "+quoted+" TEMPLATE template0"); err != nil {
		t.Fatal(err)
	}
	defer func() {
		cleanup, done := context.WithTimeout(context.Background(), 10*time.Second)
		defer done()
		if _, err := admin.Exec(cleanup, "DROP DATABASE "+quoted+" WITH (FORCE)"); err != nil {
			t.Error(err)
		}
	}()
	cfg, err := pgxpool.ParseConfig(url)
	if err != nil {
		t.Fatal(err)
	}
	cfg.ConnConfig.Database = name
	pool, err := pgxpool.NewWithConfig(ctx, cfg)
	if err != nil {
		t.Fatal(err)
	}
	defer pool.Close()
	migration, err := os.ReadFile(filepath.Join("..", "..", "..", "..", "db", "migrations", "V1__core_schema.sql"))
	if err != nil {
		t.Fatal(err)
	}
	if _, err := pool.Exec(ctx, string(migration)); err != nil {
		t.Fatal(err)
	}
	var root, group, node int
	if err := pool.QueryRow(ctx, "INSERT INTO project.node_group(code,name,group_type) VALUES('SYNTHETIC','test','cluster') RETURNING id").Scan(&root); err != nil {
		t.Fatal(err)
	}
	if err := pool.QueryRow(ctx, "INSERT INTO project.node_group(parent_id,code,name,group_type) VALUES($1,'a01','test','topological') RETURNING id", root).Scan(&group); err != nil {
		t.Fatal(err)
	}
	if err := pool.QueryRow(ctx, "INSERT INTO project.node(node_group_id,hostname,node_index) VALUES($1,'a01n01',1) RETURNING id", group).Scan(&node); err != nil {
		t.Fatal(err)
	}
	components := map[string]int{}
	for kind, size := range map[string]int{"psu": 2, "cpu": 2, "gpu": 6} {
		for i := 0; i < size; i++ {
			var id int
			if err := pool.QueryRow(ctx, "INSERT INTO project.component(node_id,kind,local_index) VALUES($1,$2,$3) RETURNING id", node, kind, i).Scan(&id); err != nil {
				t.Fatal(err)
			}
			components[kind+string(rune('0'+i))] = id
		}
	}
	ts := time.Date(2020, 1, 1, 0, 0, 0, 0, time.UTC)
	measurements := [][]any{}
	for i, feature := range domain.FeatureNames {
		kind, index, metric := "", 0, ""
		switch {
		case i < 2:
			kind, index, metric = "psu", i, "PSU_INPUT_POWER"
		case i < 4:
			kind, index, metric = "cpu", i-2, "CPU_POWER"
		case i < 10:
			kind, index, metric = "gpu", i-4, "GPU_POWER"
		case i < 12:
			kind, index, metric = "cpu", i-10, "CPU_MEAN_TEMP"
		default:
			kind, index, metric = "gpu", i-12, "GPU_CORE_TEMP"
		}
		var source int
		if err := pool.QueryRow(ctx, "INSERT INTO project.metric_source(component_id,metric_type_id,source_key) SELECT $1,id,$2 FROM project.metric_type WHERE code=$3 RETURNING id", components[kind+string(rune('0'+index))], feature, metric).Scan(&source); err != nil {
			t.Fatal(err)
		}
		if i > 0 {
			measurements = append(measurements, []any{source, ts, float64(i + 1)})
		}
	}
	if count, err := pool.CopyFrom(ctx, pgx.Identifier{"project", "telemetry"}, []string{"metric_source_id", "ts", "value"}, pgx.CopyFromRows(measurements)); err != nil || count != 17 {
		t.Fatalf("COPY %d: %v", count, err)
	}
	repo := NewPostgresHistory(pool)
	record, err := repo.RecordAt(ctx, node, ts)
	if err != nil {
		t.Fatal(err)
	}
	if !record.Timestamp.Equal(ts) || record.Hostname != "a01n01" || record.GroupID != "a01" || record.NodeIndex != 1 || record.Valid || record.AvailabilityMask != domain.FullAvailabilityMask-1 {
		t.Fatal(record)
	}
	features := record.Features()
	if !math.IsNaN(features[0]) {
		t.Fatal("missing coordinate coerced to zero")
	}
	for i := 1; i < 18; i++ {
		if features[i] != float64(i+1) {
			t.Fatal(features)
		}
	}
	empty, err := repo.RecordAt(ctx, node, ts.Add(10*time.Second))
	if err != nil {
		t.Fatal(err)
	}
	if empty.Valid || empty.AvailabilityMask != 0 {
		t.Fatal(empty)
	}
	if _, err := repo.RecordAt(ctx, node+999, ts); err != pgx.ErrNoRows {
		t.Fatal(err)
	}
}
