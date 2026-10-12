"""Build chronologically ordered F18 days; disk-backed sorting, bounded memory."""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq

from common import (BATCH_SIZE, BUILDER_VERSION, FEATURES, FULL_MASK, PREPARED_SCHEMA,
                    SCHEMA_VERSION, file_hash, load_mapping, project_batch, raw_columns,
                    scan_day, select_groups, validate_days, parse_hostname)
from disk_guard import guard


def prepare_day(day, mapping, hosts, target, scratch, assumed_timezone=None):
    fields = PREPARED_SCHEMA.names
    db_path = scratch / "sort.sqlite"
    db = sqlite3.connect(db_path)
    try:
        db.execute("PRAGMA cache_size=-32768")
        db.execute("PRAGMA temp_store=FILE")
        # This is disposable build scratch, never a durable telemetry database.
        db.execute("PRAGMA journal_mode=OFF")
        types = ["INTEGER", "TEXT", "TEXT", "INTEGER", *(["REAL"] * 18),
                 "INTEGER", "INTEGER", "INTEGER", "INTEGER"]
        db.execute("CREATE TABLE states (" + ",".join(f'"{n}" {t}' for n, t in zip(fields, types))
                   + ", PRIMARY KEY(timestamp,group_id,hostname)) WITHOUT ROWID")
        insert = "INSERT INTO states VALUES (" + ",".join("?" for _ in fields) + ")"
        pf = pq.ParquetFile(day.path)
        host_set = pa.array(sorted(hosts))
        selected_missing = dict.fromkeys(FEATURES, 0)
        valid = rows = 0
        for batch in pf.iter_batches(batch_size=BATCH_SIZE, columns=raw_columns(mapping)):
            guard(target, 256 * 1024**2)
            table = pa.Table.from_batches([batch])
            table = table.filter(pc.is_in(table[mapping["hostname"]], value_set=host_set))
            if not len(table):
                continue
            prepared = project_batch(table.to_batches()[0], mapping, assumed_timezone)
            arrays = [pc.cast(prepared["timestamp"], pa.int64()).to_pylist(),
                      *(prepared[f].to_pylist() for f in fields[1:])]
            db.executemany(insert, zip(*arrays))
            db.commit()
            rows += len(prepared)
            valid += sum(prepared["is_valid"].to_pylist())
            for f in FEATURES:
                selected_missing[f] += prepared[f].null_count
        cursor = db.execute("SELECT * FROM states ORDER BY timestamp,group_id,hostname")
        with pq.ParquetWriter(target, PREPARED_SCHEMA, compression="snappy") as writer:
            while batch_rows := cursor.fetchmany(BATCH_SIZE):
                guard(target)
                arrays = [pa.array([bool(v) for v in col] if pa.types.is_boolean(f.type) else col, type=f.type)
                          for col, f in zip(zip(*batch_rows), PREPARED_SCHEMA)]
                writer.write_table(pa.Table.from_arrays(arrays, schema=PREPARED_SCHEMA))
        return {"rows": rows, "valid": valid, "invalid": rows - valid,
                "missing_features": selected_missing,
                "missing_samples": len(hosts) * 8640 - rows,
                "coverage": rows / (len(hosts) * 8640)}
    finally:
        db.close()
        db_path.unlink(missing_ok=True)


def build(paths, output, mapping_path, assumed_timezone=None, postgres=None, replace=False):
    paths = [Path(p).resolve(strict=True) for p in paths]
    if len(paths) != 3 or len(set(paths)) != 3:
        raise ValueError("Exactly three distinct raw files required")
    output = Path(output).resolve()
    if any(output == p.parent for p in paths):
        raise ValueError("Raw archive and prepared output must use different directories")
    schemas = [pq.ParquetFile(p).schema_arrow for p in paths]
    if not all(schemas[0].equals(s, check_metadata=False) for s in schemas[1:]):
        raise ValueError("Raw schemas differ")
    mapping = load_mapping(Path(mapping_path), schemas[0])
    days = []
    for path in paths:
        print(f"Scanning {path.name}", flush=True)
        days.append(scan_day(path, mapping, assumed_timezone))
    validate_days(days)
    selected, eligible = select_groups(days)
    groups = [g[0] for g in selected]
    hosts = sorted(h for g in selected for h in g[1])
    output.mkdir(parents=True, exist_ok=True)
    existing = [output / f"D{i}.parquet" for i in range(1, 4)] + [output / "manifest.json"]
    if any(p.exists() for p in existing) and not replace:
        raise ValueError("Prepared output exists; use --replace-dataset for an intentional replacement")
    with tempfile.TemporaryDirectory(prefix=".dataset-", dir=output.parent) as temp:
        scratch = Path(temp)
        stats = {}
        for i, day in enumerate(days, 1):
            print(f"Preparing D{i} ({day.date})", flush=True)
            stats[f"D{i}"] = prepare_day(day, mapping, hosts, scratch / f"D{i}.parquet", scratch, assumed_timezone)
        manifest = {
            "dataset_name": "Long Term Per-Component Power and Thermal Measurements of the OLCF Summit System",
            "dataset_doi": "10.13139/OLCF/1861393",
            "source_files": [str(p) for p in paths],
            "source_file_hashes": [file_hash(p) for p in paths],
            **{f"D{i}_date": d.date for i, d in enumerate(days, 1)},
            "source_schema": [{"name": f.name, "type": str(f.type), "nullable": f.nullable} for f in schemas[0]],
            "source_timezone": schemas[0].field(mapping["timestamp"]).type.tz or "unknown",
            "assumed_timezone": assumed_timezone,
            "timezone_verified": bool(schemas[0].field(mapping["timestamp"]).type.tz),
            "prepared_timezone": "UTC", "feature_mapping": mapping,
            "cpu_temperature_aggregation_rule": "arithmetic mean of finite non-null mapped core values; no valid cores => null",
            "feature_order": list(FEATURES), "selected_groups": groups, "selected_hosts": hosts,
            **{f"config_{n}_groups": groups[:n] for n in (4, 8, 16)},
            **{f"row_count_{key}": s["rows"] for key, s in stats.items()},
            "valid_states": {k: s["valid"] for k, s in stats.items()},
            "invalid_states": {k: s["invalid"] for k, s in stats.items()},
            "missingness_statistics": stats,
            "selection_rule": "complete 18 positions on all days; descending observed states, ascending F18 missing fraction, lexical group code",
            "group_quality": [{"group_id": g, "coverage": r / (3 * 18 * 8640),
                               "missing_fraction": m / (r * 18)} for g, _, r, m in eligible],
            "builder_version": BUILDER_VERSION, "schema_version": SCHEMA_VERSION,
            "build_timestamp": datetime.now(timezone.utc).isoformat(),
            "prepared_file_hashes": {f"D{i}.parquet": file_hash(scratch / f"D{i}.parquet") for i in range(1, 4)},
            "postgres_import": {"status": "not_requested"},
        }
        (scratch / "manifest.json").write_text(json.dumps(manifest, indent=2, allow_nan=False) + "\n", encoding="utf-8")
        # Files are published only after all three complete successfully. Manifest is the final marker.
        (output / "manifest.json").unlink(missing_ok=True)
        for name in ("D1.parquet", "D2.parquet", "D3.parquet", "manifest.json"):
            os.replace(scratch / name, output / name)
    if postgres:
        from import_postgres import import_dataset
        counts = import_dataset(output, postgres, replace=replace)
        manifest["postgres_import"] = {"status": "completed", **counts}
        temp_manifest = output / "manifest.tmp.json"
        temp_manifest.write_text(json.dumps(manifest, indent=2, allow_nan=False) + "\n", encoding="utf-8")
        os.replace(temp_manifest, output / "manifest.json")
    return manifest


def build_pilot(path, output, mapping_path, assumed_timezone=None):
    """D1-only preliminary selection; reuse the canonical projection and disk sort."""
    path, output = Path(path).resolve(strict=True), Path(output).resolve()
    if path.parent == output:
        raise ValueError('Raw archive and prepared output must use different directories')
    output.mkdir(parents=True, exist_ok=True)
    if any((output / name).exists() for name in ('D1.parquet', 'manifest.json')):
        raise ValueError('Pilot output exists; use a new directory for an intentional rebuild')
    guard(output, 1024**3)
    schema = pq.ParquetFile(path).schema_arrow
    mapping = load_mapping(Path(mapping_path), schema)
    print('Scanning D1 F18 and topology', flush=True)
    day = scan_day(path, mapping, assumed_timezone)
    selected, eligible = select_groups([day])
    groups = [g[0] for g in selected]
    hosts = sorted(h for g in selected for h in g[1])
    print(f'Preparing pilot: raw_rows={day.rows} raw_hosts={len(day.hosts)} groups={groups}', flush=True)
    with tempfile.TemporaryDirectory(prefix='.dataset-', dir=output.parent) as temp:
        scratch = Path(temp)
        stats = prepare_day(day, mapping, hosts, scratch / 'D1.parquet', scratch, assumed_timezone)
        manifest = {
            'dataset_mode': 'D1-pilot', 'selection_provisional': True,
            'source_dataset': 'MachaParfait/ClusterWise', 'source_files': [str(path)],
            'source_file_hashes': [file_hash(path)], 'D1_date': day.date,
            'source_schema': str(schema),
            'source_timezone': schema.field(mapping['timestamp']).type.tz or 'unknown',
            'assumed_timezone': assumed_timezone,
            'timezone_verified': bool(schema.field(mapping['timestamp']).type.tz),
            'prepared_timezone': 'UTC', 'feature_mapping': mapping,
            'cpu_temperature_aggregation_rule': 'source-provided mean when mapped as string; otherwise finite non-null core arithmetic mean',
            'cpu_valid_cores_unknown_sentinel': -1,
            'feature_order': list(FEATURES), 'selected_groups': groups, 'selected_hosts': hosts,
            **{f'config_{n}_groups': groups[:n] for n in (4, 8, 16)},
            'raw_group_count': len({parse_hostname(h)[0] for h in day.hosts}),
            'eligible_complete_group_count': len(eligible),
            'row_count_D1': stats['rows'], 'missingness_statistics': {'D1': stats},
            'raw_rows': day.rows, 'raw_host_count': len(day.hosts),
            'raw_timestamp_min': day.timestamp_min, 'raw_timestamp_max': day.timestamp_max,
            'raw_missing_features': day.missing,
            'group_quality': [{'group_id': g, 'coverage': r / (18*8640), 'missing_fraction': m/(r*18)} for g, _, r, m in eligible],
            'selection_rule': 'D1 only: complete 18 positions; descending observed states, ascending F18 missing fraction, lexical group',
            'builder_version': BUILDER_VERSION, 'schema_version': SCHEMA_VERSION,
            'build_timestamp': datetime.now(timezone.utc).isoformat(),
            'prepared_file_hashes': {'D1.parquet': file_hash(scratch/'D1.parquet')},
            'postgres_import': {'status': 'not_requested'},
        }
        (scratch/'manifest.json').write_text(json.dumps(manifest, indent=2, allow_nan=False)+'\n', encoding='utf-8')
        os.replace(scratch/'D1.parquet', output/'D1.parquet')
        os.replace(scratch/'manifest.json', output/'manifest.json')
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--pilot', action='store_true', help='D1 only; provisional topology; import separately in bounded windows')
    parser.add_argument('--d1', required=True, type=Path)
    for name in ('d2', 'd3'):
        parser.add_argument(f'--{name}', type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--mapping", required=True, type=Path, help="Explicit mapping created after raw inspection")
    parser.add_argument("--timezone", help="Required for timezone-naive raw timestamps; never assumed")
    destination = parser.add_mutually_exclusive_group(required=True)
    destination.add_argument("--postgres", help="DATABASE_URL; never printed")
    destination.add_argument("--no-postgres", action="store_true")
    parser.add_argument("--replace-dataset", action="store_true")
    args = parser.parse_args()
    if args.pilot and (args.d2 or args.d3 or args.postgres or args.replace_dataset):
        parser.error('Pilot requires D1 and --no-postgres; rebuild into a new directory')
    if not args.pilot and not (args.d2 and args.d3):
        parser.error('D2 and D3 required unless --pilot')
    try:
        manifest = (build_pilot(args.d1, args.output, args.mapping, args.timezone) if args.pilot else
                    build([args.d1, args.d2, args.d3], args.output, args.mapping,
                          args.timezone, args.postgres, args.replace_dataset))
    except Exception as exc:
        # Show schema on mapping failures without inventing column names.
        if args.d1.is_file():
            try:
                print(pq.ParquetFile(args.d1).schema_arrow)
            except Exception:
                pass
        parser.exit(1, f"Dataset build failed: {type(exc).__name__}: {exc}\n")
    print(json.dumps({k: manifest[k] for k in ("selected_groups", "row_count_D1", "row_count_D2", "row_count_D3") if k in manifest}))


if __name__ == "__main__":
    main()
