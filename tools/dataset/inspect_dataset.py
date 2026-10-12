"""Inspect 1--3 real Parquet files in batches; report mapping candidates without guessing."""
from __future__ import annotations

import argparse
from collections import Counter
import json
import re
import sqlite3
import tempfile
from datetime import timedelta
from pathlib import Path

import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq

from common import BATCH_SIZE, EPOCH, load_mapping, timestamp_utc
from disk_guard import guard


def inspect(path, timestamp="timestamp", hostname="hostname", assumed_timezone=None, mapping_path=None, grid_day=False):
    pf = pq.ParquetFile(path)
    schema = pf.schema_arrow
    if timestamp not in schema.names or hostname not in schema.names:
        raise ValueError(f"Required timestamp/hostname columns absent. Schema:\n{schema}")
    if not pa.types.is_timestamp(schema.field(timestamp).type):
        raise ValueError(f"Timestamp type is not a timestamp. Schema:\n{schema}")
    columns = schema.names
    numeric = [f.name for f in schema if pa.types.is_floating(f.type) or pa.types.is_integer(f.type)]
    missing = Counter()
    host_rows = Counter()
    slots = {}
    grid_date = None
    duplicates = seen = 0
    # Exact, disk-backed state keys permit arbitrary intervals and unsorted raw files.
    with tempfile.TemporaryDirectory(prefix="dataset-inspection-") as temp:
        db = sqlite3.connect(Path(temp) / "states.sqlite")
        try:
            db.execute("PRAGMA cache_size=-32768")
            db.execute("PRAGMA temp_store=FILE")
            db.execute("CREATE TABLE states(host TEXT, ts INTEGER, n INTEGER NOT NULL, PRIMARY KEY(host,ts)) WITHOUT ROWID")
            minimum = maximum = None
            timestamp_nulls = 0
            for batch in pf.iter_batches(batch_size=BATCH_SIZE):
                guard(path, 256 * 1024**2)
                table = pa.Table.from_batches([batch])
                for name in columns:
                    if name in numeric:
                        missing[name] += len(table) - pc.sum(pc.cast(pc.fill_null(pc.is_finite(table[name]), False), pa.int64())).as_py()
                    else:
                        missing[name] += table[name].null_count
                times = timestamp_utc(table[timestamp], assumed_timezone)
                timestamp_nulls += times.null_count
                rows = []
                for host, us in zip(table[hostname].to_pylist(), pc.cast(times, pa.int64()).to_pylist()):
                    if host is None:
                        raise ValueError("Null hostname")
                    host_rows[host] += 1
                    if us is not None:
                        if grid_day:
                            date, slot = divmod(us, 86_400_000_000)
                            grid_date = date if grid_date is None else grid_date
                            if date != grid_date or slot % 10_000_000:
                                raise ValueError('Grid-day inspection requires one day on the 10-second grid')
                            byte, bit = divmod(slot // 10_000_000, 8)
                            bits = slots.get(host)
                            if bits is None:
                                bits = slots[host] = bytearray(1080)
                            duplicates += bool(bits[byte] & (1 << bit))
                            bits[byte] |= 1 << bit
                        else:
                            rows.append((host, us))
                        minimum = us if minimum is None else min(minimum, us)
                        maximum = us if maximum is None else max(maximum, us)
                db.executemany("INSERT INTO states VALUES(?,?,1) ON CONFLICT(host,ts) DO UPDATE SET n=n+1", rows)
                db.commit()
                seen += len(batch)
                if seen // 1_000_000 != (seen-len(batch)) // 1_000_000:
                    print(f'Inspection rows={seen}/{pf.metadata.num_rows}', flush=True)
            if not grid_day:
                duplicates = db.execute("SELECT coalesce(sum(n-1),0) FROM states").fetchone()[0]
            intervals = Counter()
            previous_host = previous_ts = None
            keys = ((host, (grid_date * 8640 + slot) * 10_000_000) for host, bits in sorted(slots.items())
                    for slot in range(8640) if bits[slot//8] & (1 << (slot%8))) if grid_day else db.execute("SELECT host,ts FROM states ORDER BY host,ts")
            for host, us in keys:
                if host == previous_host:
                    intervals[(us - previous_ts) / 1_000_000] += 1
                previous_host, previous_ts = host, us
        finally:
            db.close()
    # Candidate names are diagnostics only. Explicit mapping is required by Builder.
    cpu_candidates = {str(i): [n for n in columns if re.fullmatch(fr"p{i}_core_?\d+_temp", n)] for i in range(2)}
    mapping = load_mapping(Path(mapping_path), schema) if mapping_path else None
    return {
        "file": str(Path(path).resolve()), "schema": str(schema),
        "columns": columns,
        "physical_types": [{"name": pf.schema.column(i).name, "physical_type": pf.schema.column(i).physical_type,
                            "logical_type": str(pf.schema.column(i).logical_type)} for i in range(len(pf.schema))],
        "row_count": pf.metadata.num_rows, "timestamp_type": str(schema.field(timestamp).type),
        "timestamp_timezone": schema.field(timestamp).type.tz,
        "assumed_timezone": assumed_timezone, "reported_timezone": "UTC",
        "timestamp_min": (EPOCH + timedelta(microseconds=minimum)).isoformat() if minimum is not None else None,
        "timestamp_max": (EPOCH + timedelta(microseconds=maximum)).isoformat() if maximum is not None else None,
        "timestamp_nulls": timestamp_nulls,
        "sampling_intervals_seconds": dict(sorted(intervals.items())),
        "unique_hostname_count": len(host_rows), "hostname_examples": sorted(host_rows)[:10],
        "rows_per_hostname": dict(sorted(host_rows.items())),
        "duplicate_hostname_timestamp": duplicates, "missingness": dict(missing),
        "power_columns": [n for n in columns if "power" in n.lower()],
        "gpu_temperature_columns": [n for n in columns if "gpu" in n.lower() and "temp" in n.lower()],
        "cpu_core_temperature_candidates": cpu_candidates,
        "confirmed_cpu0_core_columns": mapping["features"]["cpu0_mean_temp"] if mapping else None,
        "confirmed_cpu1_core_columns": mapping["features"]["cpu1_mean_temp"] if mapping else None,
        "mapping_status": "explicit_validated" if mapping else "unconfirmed: supply --mapping after reading this schema",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("files", nargs="+", type=Path)
    parser.add_argument("--timestamp-column", default="timestamp")
    parser.add_argument("--hostname-column", default="hostname")
    parser.add_argument("--timezone", help="Explicit timezone for naive raw timestamps")
    parser.add_argument("--mapping", type=Path)
    parser.add_argument("--report", type=Path)
    parser.add_argument('--grid-day', action='store_true', help='Exact in-memory bitsets for a single 10-second-grid day; no large SQLite scratch')
    args = parser.parse_args()
    if not 1 <= len(args.files) <= 3:
        parser.error("Provide 1--3 Parquet files")
    try:
        reports = [inspect(p, args.timestamp_column, args.hostname_column, args.timezone, args.mapping, args.grid_day) for p in args.files]
    except Exception as exc:
        for path in args.files:
            if path.is_file():
                try:
                    print(pq.ParquetFile(path).schema_arrow)
                except Exception:
                    pass
        parser.exit(1, f"Inspection failed: {type(exc).__name__}: {exc}\n")
    result = json.dumps(reports, indent=2, allow_nan=False)
    print(result)
    if args.report:
        args.report.write_text(result + "\n", encoding="utf-8")
    if any(r["duplicate_hostname_timestamp"] or r["timestamp_nulls"] for r in reports):
        parser.exit(1, "Invalid timestamp keys: see diagnostic report\n")
    if not args.mapping:
        parser.exit(2, "Schema inspected. CPU mapping remains unconfirmed; supply explicit --mapping.\n")


if __name__ == "__main__":
    main()
