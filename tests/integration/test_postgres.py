"""Actual canonical DDL, COPY, idempotence and F18 equivalence on synthetic fixtures."""
from decimal import Decimal
from datetime import timedelta
import json
from pathlib import Path

import psycopg
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from common import FEATURES, file_hash
from import_postgres import import_dataset

ROOT = Path(__file__).resolve().parents[2]

pytestmark = pytest.mark.integration


def count(conn, table):
    from psycopg import sql
    return conn.execute(sql.SQL("SELECT count(*) FROM project.{}").format(sql.Identifier(table))).fetchone()[0]


def test_pilot_windows_resume_without_duplicates(database_url, synthetic_dataset):
    from build_dataset import build_pilot
    fixture = synthetic_dataset
    manifest = build_pilot(fixture['paths'][0], fixture['output'], fixture['mapping'])
    assert manifest['selection_provisional'] is True
    from datetime import datetime, timezone
    start = datetime.fromisoformat(manifest['D1_date']).replace(tzinfo=timezone.utc)
    middle, end = start+timedelta(seconds=10), start+timedelta(seconds=20)
    first = import_dataset(fixture['output'], database_url, start=start, end=middle)
    assert first['states'] == 288 and first['inserted_measurements'] == 5184
    assert import_dataset(fixture['output'], database_url, start=start, end=middle)['inserted_measurements'] == 0
    second = import_dataset(fixture['output'], database_url, start=middle, end=end)
    assert second['inserted_measurements'] == 5184
    with psycopg.connect(database_url) as conn:
        assert count(conn, 'telemetry') == 10368
    with pytest.raises(ValueError, match='bounded window'):
        import_dataset(fixture['output'], database_url)


def test_schema_applies_without_demo_and_preserves_constraints(database_url):
    with psycopg.connect(database_url) as conn:
        assert count(conn, "metric_type") == 5
        assert count(conn, "node") == count(conn, "telemetry") == 0
        tables = {r[0] for r in conn.execute("SELECT tablename FROM pg_tables WHERE schemaname='project'")}
        assert tables == {"node_group", "node", "component", "metric_type", "metric_source", "telemetry",
                          "event", "engineer", "maintenance", "resource", "maintenance_resource", "document"}
        assert conn.execute("SELECT count(*) FROM pg_trigger WHERE tgname IN ('metric_source_compatibility','component_kind_immutable','metric_type_kind_immutable')").fetchone()[0] == 3
        with pytest.raises(psycopg.errors.CheckViolation):
            with conn.transaction():
                conn.execute("INSERT INTO project.node_group(code,name,group_type) VALUES('invalid','invalid','topological')")


def test_copy_repeat_and_reconstruction_match_every_prepared_coordinate(database_url, prepared_fixture):
    prepared = prepared_fixture["output"]
    first = import_dataset(prepared, database_url)
    repeat = import_dataset(prepared, database_url)
    assert first == {"states": 1728, "finite_measurements": 31104, "inserted_measurements": 31104}
    assert repeat["inserted_measurements"] == 0 and repeat["states"] == 1728
    with psycopg.connect(database_url) as conn:
        assert count(conn, "node") == 288
        assert count(conn, "node_group") == 17
        assert count(conn, "component") == 2880
        assert count(conn, "metric_source") == 5184
        assert count(conn, "telemetry") == 31104
        assert conn.execute("SELECT min(n),max(n) FROM (SELECT c.node_id,count(*) n FROM project.metric_source ms JOIN project.component c ON c.id=ms.component_id GROUP BY c.node_id) s").fetchone() == (18, 18)
        # Compare the entire small fixture, not an implementation-derived expected vector.
        observed = {(h, ts, f): float(v) for h, ts, f, v in conn.execute("SELECT n.hostname,t.ts,ms.source_key,t.value FROM project.telemetry t JOIN project.metric_source ms ON ms.id=t.metric_source_id JOIN project.component c ON c.id=ms.component_id JOIN project.node n ON n.id=c.node_id")}
        for i in range(1, 4):
            for row in pq.read_table(prepared / f"D{i}.parquet").to_pylist():
                for f in FEATURES:
                    assert observed[row["hostname"], row["timestamp"], f] == pytest.approx(row[f], rel=0, abs=1e-12)
        row = pq.read_table(prepared / "D3.parquet").to_pylist()[0]
        node = conn.execute("SELECT id FROM project.node WHERE hostname=%s", (row["hostname"],)).fetchone()[0]
        # $2 occurs before $1 in SQL; named params avoid positional ordering ambiguity.
        query = (ROOT / "db/queries/f18.sql").read_text(encoding="utf-8").replace("$1", "%(node)s").replace("$2", "%(ts)s")
        cur = conn.execute(query, {"node": node, "ts": row["timestamp"]})
        reconstructed = dict(zip([col.name for col in cur.description], cur.fetchone()))
        for f in FEATURES:
            assert reconstructed[f] == row[f]
        with pytest.raises(psycopg.errors.UniqueViolation):
            with conn.transaction():
                conn.execute("INSERT INTO project.telemetry(metric_source_id,ts,value) SELECT metric_source_id,ts,value FROM project.telemetry LIMIT 1")
        with pytest.raises(psycopg.errors.CheckViolation):
            with conn.transaction():
                conn.execute("UPDATE project.component SET kind='gpu' WHERE kind='cpu'")
        with pytest.raises(psycopg.errors.CheckViolation):
            with conn.transaction():
                conn.execute("INSERT INTO project.metric_source(component_id,metric_type_id,source_key) SELECT c.id,m.id,'wrong' FROM project.component c CROSS JOIN project.metric_type m WHERE c.kind='cpu' AND m.code='GPU_POWER' LIMIT 1")


def test_missing_values_rejected_changes_and_scoped_replace(database_url, prepared_fixture):
    prepared = prepared_fixture["output"]
    import_dataset(prepared, database_url)
    path = prepared / "D2.parquet"
    table = pq.read_table(path)
    rows = table.to_pylist()
    host, ts = rows[0]["hostname"], rows[0]["timestamp"]
    rows[0][FEATURES[0]] = None
    rows[0]["availability_mask"] &= ~1
    rows[0]["is_valid"] = False
    pq.write_table(pa.Table.from_pylist(rows, schema=table.schema), path)
    manifest_path = prepared / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["prepared_file_hashes"]["D2.parquet"] = file_hash(path)
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ValueError, match="differs"):
        import_dataset(prepared, database_url)
    with psycopg.connect(database_url) as conn:
        assert count(conn, "telemetry") == 31104  # Failed import rolled back, including topology.
        source = conn.execute("SELECT ms.id FROM project.metric_source ms JOIN project.component c ON c.id=ms.component_id JOIN project.node n ON n.id=c.node_id WHERE n.hostname=%s AND ms.source_key=%s", (host, FEATURES[0])).fetchone()[0]
        outside_time = ts - timedelta(days=30)
        conn.execute("INSERT INTO project.telemetry(metric_source_id,ts,value) VALUES(%s,%s,123)", (source, outside_time))
    replaced = import_dataset(prepared, database_url, replace=True)
    assert replaced["finite_measurements"] == 31103
    assert import_dataset(prepared, database_url)["inserted_measurements"] == 0
    with psycopg.connect(database_url) as conn:
        assert count(conn, "telemetry") == 31104  # 31103 dataset + unrelated history.
        assert conn.execute("SELECT value FROM project.telemetry WHERE metric_source_id=%s AND ts=%s", (source, outside_time)).fetchone() == (Decimal(123),)
        assert conn.execute("SELECT value FROM project.telemetry WHERE metric_source_id=%s AND ts=%s", (source, ts)).fetchone() is None


def test_demo_data_is_separate_and_cannot_be_mixed(database_url, prepared_fixture):
    with psycopg.connect(database_url) as conn:
        conn.execute((ROOT / "db/demo/V1__demo_data.sql").read_text(encoding="utf-8"))
        assert count(conn, "node") == 1
        assert count(conn, "telemetry") == 35
    with pytest.raises(ValueError, match="refuse mixing"):
        import_dataset(prepared_fixture["output"], database_url)
    with psycopg.connect(database_url) as conn:
        assert count(conn, "node") == 1
        assert count(conn, "telemetry") == 35
