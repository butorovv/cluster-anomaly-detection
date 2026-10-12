"""Transactional COPY of prepared F18 into the unchanged canonical project schema."""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import json
import math
from pathlib import Path

import psycopg
import pyarrow.parquet as pq
import pyarrow as pa
import pyarrow.compute as pc

from common import BATCH_SIZE, FEATURES, FULL_MASK, PREPARED_SCHEMA, SCHEMA_VERSION, file_hash, parse_hostname
from disk_guard import guard

OWNER = "SUMMIT F18 builder v1"


def coordinate(feature):
    if feature.startswith("psu"):
        return "psu", int(feature[3]), "PSU_INPUT_POWER"
    if feature.startswith("cpu"):
        return "cpu", int(feature[3]), "CPU_MEAN_TEMP" if feature.endswith("temp") else "CPU_POWER"
    return "gpu", int(feature[3]), "GPU_CORE_TEMP" if feature.endswith("temp") else "GPU_POWER"


def topology(cur, groups, hosts):
    cur.execute("INSERT INTO project.node_group(code,name,group_type,description) VALUES('SUMMIT','Summit','cluster',%s) ON CONFLICT(code) DO NOTHING", (OWNER,))
    cur.execute("SELECT id,parent_id,group_type,description FROM project.node_group WHERE code='SUMMIT'")
    root, parent, kind, description = cur.fetchone()
    if parent is not None or kind != "cluster" or description != OWNER:
        raise ValueError("Existing SUMMIT root is not owned by this importer; refuse mixing demo or unrelated topology")
    group_ids = {}
    for group in groups:
        cur.execute("INSERT INTO project.node_group(parent_id,code,name,group_type,description) VALUES(%s,%s,%s,'topological',%s) ON CONFLICT(code) DO NOTHING",
                    (root, group, f"Topological group {group}", OWNER))
        cur.execute("SELECT id,parent_id,group_type,description FROM project.node_group WHERE code=%s", (group,))
        gid, parent, kind, description = cur.fetchone()
        if (parent, kind, description) != (root, "topological", OWNER):
            raise ValueError(f"Existing group {group} belongs to a different topology")
        group_ids[group] = gid
    cur.execute("SELECT code,id,component_kind,quantity,unit FROM project.metric_type")
    types = {r[0]: r[1:] for r in cur.fetchall()}
    required = {"PSU_INPUT_POWER": ("psu", "power", "W"), "CPU_POWER": ("cpu", "power", "W"),
                "CPU_MEAN_TEMP": ("cpu", "temperature", "degC"), "GPU_POWER": ("gpu", "power", "W"),
                "GPU_CORE_TEMP": ("gpu", "temperature", "degC")}
    if set(types) != set(required) or any(types[c][1:] != required[c] for c in required):
        raise ValueError("Canonical five metric types/units missing or incompatible; apply core migration")
    source_ids = {}
    for host in hosts:
        group, index = parse_hostname(host)
        cur.execute("INSERT INTO project.node(node_group_id,hostname,node_index,description) VALUES(%s,%s,%s,%s) ON CONFLICT(hostname) DO NOTHING",
                    (group_ids[group], host, index, OWNER))
        cur.execute("SELECT id,node_group_id,node_index,description FROM project.node WHERE hostname=%s", (host,))
        node, gid, actual_index, description = cur.fetchone()
        if (gid, actual_index, description) != (group_ids[group], index, OWNER):
            raise ValueError(f"Existing host {host} differs from selected topology")
        components = {}
        for component_kind, size in (("psu", 2), ("cpu", 2), ("gpu", 6)):
            for local_index in range(size):
                cur.execute("INSERT INTO project.component(node_id,kind,local_index) VALUES(%s,%s,%s) ON CONFLICT(node_id,kind,local_index) DO NOTHING", (node, component_kind, local_index))
                cur.execute("SELECT id FROM project.component WHERE node_id=%s AND kind=%s AND local_index=%s", (node, component_kind, local_index))
                components[component_kind, local_index] = cur.fetchone()[0]
        for feature in FEATURES:
            component_kind, local_index, metric = coordinate(feature)
            component = components[component_kind, local_index]
            cur.execute("INSERT INTO project.metric_source(component_id,metric_type_id,source_key,description) VALUES(%s,%s,%s,%s) ON CONFLICT(component_id,metric_type_id) DO NOTHING",
                        (component, types[metric][0], feature, OWNER))
            cur.execute("SELECT id,source_key FROM project.metric_source WHERE component_id=%s AND metric_type_id=%s", (component, types[metric][0]))
            source, key = cur.fetchone()
            if key != feature:
                raise ValueError(f"Existing metric source has incompatible source_key for {host}/{feature}")
            source_ids[host, feature] = source
        cur.execute("SELECT count(*) FROM project.metric_source ms JOIN project.component c ON c.id=ms.component_id WHERE c.node_id=%s", (node,))
        if cur.fetchone()[0] != 18:
            raise ValueError(f"Host {host} does not have exactly 18 metric sources")
    return source_ids


def import_dataset(prepared, url, replace=False, start=None, end=None, verify_hashes=True):
    prepared = Path(prepared)
    manifest = json.loads((prepared / "manifest.json").read_text(encoding="utf-8"))
    if manifest["schema_version"] != SCHEMA_VERSION or manifest["feature_order"] != list(FEATURES):
        raise ValueError("Prepared manifest does not match F18-v1")
    hosts, groups = manifest["selected_hosts"], manifest["selected_groups"]
    if len(hosts) != 288 or len(set(hosts)) != 288 or len(groups) != 16 or len(set(groups)) != 16:
        raise ValueError("Manifest must describe 16 groups and 288 distinct hosts")
    from collections import Counter
    if Counter(parse_hostname(h)[0] for h in hosts) != Counter({g: 18 for g in groups}):
        raise ValueError("Manifest topology is inconsistent")
    pilot = manifest.get("dataset_mode") == "D1-pilot"
    day_count = 1 if pilot else 3
    dates = [datetime.fromisoformat(manifest[f"D{i}_date"]).replace(tzinfo=timezone.utc) for i in range(1, day_count + 1)]
    if not pilot and (dates[1] != dates[0] + timedelta(days=1) or dates[2] != dates[1] + timedelta(days=1) or len({d.strftime('%Y-%m') for d in dates}) != 1):
        raise ValueError("Manifest days are not consecutive in one month")
    if (start is None) != (end is None):
        raise ValueError('Both start and end required')
    if start is not None and (start.tzinfo is None or end.tzinfo is None or not dates[0] <= start < end <= dates[-1] + timedelta(days=1)):
        raise ValueError('Invalid UTC import window')
    if pilot and start is None:
        raise ValueError('Pilot import requires an explicit bounded window')
    reserve = max(256 * 1024**2, int((end-start).total_seconds()*518.4*600) + 128*1024**2) if start else 768*1024**2
    guard(prepared, reserve)
    for i in range(1, day_count + 1):
        pf = pq.ParquetFile(prepared / f"D{i}.parquet")
        if not pf.schema_arrow.equals(PREPARED_SCHEMA, check_metadata=True) or pf.metadata.num_rows != manifest[f"row_count_D{i}"]:
            raise ValueError(f"Prepared D{i} schema/count differs from manifest")
        if verify_hashes and file_hash(prepared / f"D{i}.parquet") != manifest["prepared_file_hashes"][f"D{i}.parquet"]:
            raise ValueError(f"Prepared D{i} checksum differs from manifest")
    measurements = inserted = states = 0
    host_set = set(hosts)
    with psycopg.connect(url) as conn:
        with conn.cursor() as cur:
            # Serialize SUMMIT importers, including overlapping dataset replacements.
            cur.execute("SELECT pg_advisory_xact_lock(1861393)")
            sources = topology(cur, groups, hosts)
            if replace:
                cur.execute("DELETE FROM project.telemetry WHERE metric_source_id=ANY(%s) AND ts >= %s AND ts < %s",
                            (list(sources.values()), start or dates[0], end or dates[-1] + timedelta(days=1)))
            cur.execute("CREATE TEMP TABLE f18_stage(metric_source_id int NOT NULL, ts timestamptz NOT NULL, value numeric, PRIMARY KEY(metric_source_id,ts)) ON COMMIT DROP")
            for i in range(1, day_count + 1):
                previous = None
                day_states = 0
                for batch in pq.ParquetFile(prepared / f"D{i}.parquet").iter_batches(batch_size=BATCH_SIZE):
                    if start is not None:
                        batch = batch.filter(pc.and_(pc.greater_equal(batch.column('timestamp'), pa.scalar(start, type=pa.timestamp('us', tz='UTC'))), pc.less(batch.column('timestamp'), pa.scalar(end, type=pa.timestamp('us', tz='UTC')))))
                    if not len(batch):
                        continue
                    guard(prepared, 256 * 1024**2)
                    with cur.copy("COPY f18_stage(metric_source_id,ts,value) FROM STDIN") as copy:
                        for row in batch.to_pylist():
                            host, ts = row["hostname"], row["timestamp"]
                            group, index = parse_hostname(host)
                            key = (ts, group, host)
                            if host not in host_set or (row["group_id"], row["node_index"]) != (group, index) or (previous is not None and key <= previous):
                                raise ValueError(f"Unsorted/duplicate/inconsistent prepared state: {host}/{ts}")
                            if ts.date() != dates[i-1].date():
                                raise ValueError("Prepared timestamp outside its manifest day")
                            previous = key
                            mask = 0
                            for bit, feature in enumerate(FEATURES):
                                value = row[feature]
                                if value is not None:
                                    if not math.isfinite(value):
                                        raise ValueError("Non-finite prepared feature; expected null")
                                    mask |= 1 << bit
                                    measurements += 1
                                copy.write_row((sources[host, feature], ts, Decimal(str(value)) if value is not None else None))
                            if mask != row["availability_mask"] or row["is_valid"] != (mask == FULL_MASK):
                                raise ValueError("Prepared validity metadata differs from feature values")
                            for cpu in range(2):
                                core_count = row[f"cpu{cpu}_valid_cores"]
                                if core_count < -1 or (core_count != -1 and (core_count > 0) != bool(mask & (1 << (10 + cpu)))):
                                    raise ValueError("Prepared CPU core metadata differs from temperature availability")
                            states += 1
                            day_states += 1
                    if not replace:
                        cur.execute("SELECT 1 FROM project.telemetry t JOIN f18_stage s USING(metric_source_id,ts) WHERE t.value IS DISTINCT FROM s.value LIMIT 1")
                        if cur.fetchone():
                            raise ValueError("Existing telemetry differs from this dataset; explicit --replace-dataset required")
                    cur.execute("INSERT INTO project.telemetry(metric_source_id,ts,value) SELECT metric_source_id,ts,value FROM f18_stage WHERE value IS NOT NULL ON CONFLICT(metric_source_id,ts) DO NOTHING")
                    inserted += cur.rowcount
                    cur.execute("TRUNCATE f18_stage")
                if start is None and day_states != manifest[f"row_count_D{i}"]:
                    raise ValueError("Prepared count changed during import")
    return {"states": states, "finite_measurements": measurements, "inserted_measurements": inserted}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prepared", type=Path, required=True)
    parser.add_argument("--postgres", required=True)
    parser.add_argument("--replace-dataset", action="store_true")
    parser.add_argument('--start', type=datetime.fromisoformat)
    parser.add_argument('--end', type=datetime.fromisoformat)
    args = parser.parse_args()
    try:
        print(json.dumps(import_dataset(args.prepared, args.postgres, args.replace_dataset, args.start, args.end)))
    except Exception as exc:
        parser.exit(1, f"Import failed: {type(exc).__name__}: {exc}\n")


if __name__ == "__main__":
    main()
