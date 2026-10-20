"""Shared offline F18 contract. No assumed raw CPU-core column names."""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq

FEATURES = (
    "psu0_power", "psu1_power", "cpu0_power", "cpu1_power",
    *(f"gpu{i}_power" for i in range(6)),
    "cpu0_mean_temp", "cpu1_mean_temp",
    *(f"gpu{i}_core_temp" for i in range(6)),
)
FULL_MASK = (1 << len(FEATURES)) - 1
BATCH_SIZE = 8192
BUILDER_VERSION = "1.1.0"
SCHEMA_VERSION = "F18-v1"
MANIFEST_VERSION = "dataset-manifest-v2"
EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)
PREPARED_SCHEMA = pa.schema([
    pa.field("timestamp", pa.timestamp("us", tz="UTC"), nullable=False),
    pa.field("hostname", pa.string(), nullable=False),
    pa.field("group_id", pa.string(), nullable=False),
    pa.field("node_index", pa.int32(), nullable=False),
    *(pa.field(f, pa.float64()) for f in FEATURES),
    pa.field("is_valid", pa.bool_(), nullable=False),
    pa.field("availability_mask", pa.uint32(), nullable=False),
    pa.field("cpu0_valid_cores", pa.int32(), nullable=False),
    pa.field("cpu1_valid_cores", pa.int32(), nullable=False),
], metadata={b"schema_version": SCHEMA_VERSION.encode()})


def parse_hostname(hostname: str) -> tuple[str, int]:
    if not isinstance(hostname, str):
        raise ValueError(f"Missing/non-string hostname: {hostname!r}")
    m = re.fullmatch(r"([a-h])(\d{1,2})n(\d{1,2})", hostname)
    # ClusterWise D1 includes group codes up to h50; the old 24 bound was false.
    if not m or not 1 <= int(m[3]) <= 18:
        raise ValueError(f"Invalid Summit hostname: {hostname!r}")
    return f"{m[1]}{int(m[2]):02d}", int(m[3])


def file_hash(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def load_mapping(path: Path, schema: pa.Schema) -> dict:
    mapping = json.loads(path.read_text(encoding="utf-8"))
    if set(mapping) != {"timestamp", "hostname", "features"}:
        raise ValueError("Mapping requires exactly timestamp, hostname, features")
    features = mapping["features"]
    if set(features) != set(FEATURES):
        raise ValueError(f"Mapping must contain exactly these 18 features: {FEATURES}")
    used = []
    for feature in FEATURES:
        cols = features[feature]
        if feature in ("cpu0_mean_temp", "cpu1_mean_temp"):
            if isinstance(cols, str):
                cols = [cols]  # Explicit source-provided mean; core counts are unknown.
            elif not isinstance(cols, list) or not cols:
                raise ValueError(f"{feature}: explicit mean column or non-empty list of core columns required")
        elif not isinstance(cols, str):
            raise ValueError(f"{feature}: one raw column name required")
        else:
            cols = [cols]
        for col in cols:
            if col not in schema.names:
                raise ValueError(f"Missing raw column {col!r} for {feature}")
            t = schema.field(col).type
            if not (pa.types.is_floating(t) or pa.types.is_integer(t)):
                raise ValueError(f"Non-numeric feature {col}: {t}")
            used.append(col)
    if len(set(used)) != len(used):
        raise ValueError("Raw feature/core columns must be distinct; mapping is ambiguous")
    for key in ("timestamp", "hostname"):
        if not isinstance(mapping[key], str) or mapping[key] not in schema.names:
            raise ValueError(f"Missing explicit {key} column")
    if not pa.types.is_timestamp(schema.field(mapping["timestamp"]).type):
        raise ValueError("Raw timestamp must be a Parquet timestamp, not guessed epoch/string")
    if not (pa.types.is_string(schema.field(mapping["hostname"]).type)
            or pa.types.is_large_string(schema.field(mapping["hostname"]).type)):
        raise ValueError("Raw hostname must be a string")
    return mapping


def clean_numeric(values):
    values = pc.cast(values, pa.float64())
    return pc.if_else(pc.fill_null(pc.is_finite(values), False), values, None)


def mean_cores(table: pa.Table, columns: list[str]):
    total = pa.array([0.0] * len(table))
    count = pa.array([0] * len(table), type=pa.int32())
    for name in columns:
        values = clean_numeric(table[name])
        total = pc.add(total, pc.fill_null(values, 0.0))
        count = pc.add(count, pc.cast(pc.is_valid(values), pa.int32()))
    # Zero is used only as the accumulator identity, never as a missing reading.
    mean = pc.if_else(pc.greater(count, 0), pc.divide(total, pc.cast(count, pa.float64())), None)
    if pc.any(pc.fill_null(pc.invert(pc.is_finite(mean)), False)).as_py():
        raise ValueError("CPU temperature aggregation overflow: cannot derive a finite mean")
    return mean, count


def timestamp_utc(values, assumed_timezone: str | None):
    if not values.type.tz:
        if not assumed_timezone:
            raise ValueError("Naive raw timestamp: supply --timezone with documented source timezone")
        values = pc.assume_timezone(values, assumed_timezone, ambiguous="raise", nonexistent="raise")
    # Reject sub-microsecond loss instead of silently changing logical time.
    return pc.cast(values, pa.timestamp("us", tz="UTC"), safe=True)


def project_batch(batch: pa.RecordBatch, mapping: dict, assumed_timezone=None) -> pa.Table:
    table = pa.Table.from_batches([batch])
    timestamps = timestamp_utc(table[mapping["timestamp"]], assumed_timezone)
    if timestamps.null_count:
        raise ValueError("Null timestamp")
    hosts = table[mapping["hostname"]].to_pylist()
    host_topology = {h: parse_hostname(h) for h in set(hosts)}
    topology = [host_topology[h] for h in hosts]
    columns = [timestamps, pa.array(hosts), pa.array([g for g, _ in topology]),
               pa.array([n for _, n in topology], type=pa.int32())]
    counts = []
    masks = [0] * len(table)
    for i, feature in enumerate(FEATURES):
        raw = mapping["features"][feature]
        if isinstance(raw, list):
            values, count = mean_cores(table, raw)
            counts.append(count)
        else:
            values = clean_numeric(table[raw])
            if feature in ("cpu0_mean_temp", "cpu1_mean_temp"):
                counts.append(pa.array([-1] * len(table), type=pa.int32()))
        columns.append(values)
        for row, available in enumerate(pc.is_valid(values).to_pylist()):
            if available:
                masks[row] |= 1 << i
    columns.extend([pa.array([m == FULL_MASK for m in masks]),
                    pa.array(masks, type=pa.uint32()), *counts])
    return pa.Table.from_arrays(columns, schema=PREPARED_SCHEMA)


def raw_columns(mapping):
    names = [mapping["timestamp"], mapping["hostname"]]
    for raw in mapping["features"].values():
        names.extend(raw if isinstance(raw, list) else [raw])
    return names


def availability_metrics(rows, valid, missing, expected):
    """Missing feature positions include nulls only among observed rows.

    Expected samples refer to the entire UTC day(s), including edge gaps.
    An absent sample contributes all 18 positions to total unavailability.
    No observed rows means an undefined conditional feature fraction (None).
    """
    if not (expected > 0 and 0 <= valid <= rows <= expected
            and rows - valid <= missing <= (rows - valid) * len(FEATURES)):
        raise ValueError('Inconsistent availability counts')
    absent = expected - rows
    unavailable = absent * len(FEATURES) + missing
    return {
        'expected_samples': expected, 'rows': rows, 'valid': valid, 'invalid': rows-valid,
        'missing_samples': absent, 'missing_feature_positions_observed': missing,
        'total_unavailable_feature_positions': unavailable,
        'sample_coverage': rows / expected, 'complete_f18_coverage': valid / expected,
        'feature_missing_fraction_observed': missing / (rows * len(FEATURES)) if rows else None,
        'total_feature_unavailability_fraction': unavailable / (expected * len(FEATURES)),
    }


@dataclass
class HostStats:
    rows: int = 0
    missing_features: int = 0
    valid: int = 0
    slots: bytearray = field(default_factory=lambda: bytearray(1080))


@dataclass
class DayStats:
    path: Path
    date: str
    hosts: dict[str, HostStats]
    rows: int
    missing: dict[str, int]
    timestamp_min: str
    timestamp_max: str


def scan_day(path: Path, mapping: dict, assumed_timezone=None) -> DayStats:
    """One projected batch in memory; 8640 bits per host for exact duplicate checks."""
    pf = pq.ParquetFile(path)
    hosts: dict[str, HostStats] = {}
    missing = dict.fromkeys(FEATURES, 0)
    day = None
    day_number = None
    minimum = maximum = None
    rows = 0
    for batch in pf.iter_batches(batch_size=BATCH_SIZE, columns=raw_columns(mapping)):
        prepared = project_batch(batch, mapping, assumed_timezone)
        times = pc.cast(prepared["timestamp"], pa.int64()).to_pylist()
        masks = prepared["availability_mask"].to_pylist()
        for host, us, mask in zip(prepared["hostname"].to_pylist(), times, masks):
            number, within_day = divmod(us, 86_400_000_000)
            if day_number is None:
                day_number = number
                day = (EPOCH + timedelta(days=number)).date().isoformat()
            if number != day_number:
                raise ValueError(f"{path.name} contains multiple UTC days: {day}, {(EPOCH + timedelta(days=number)).date()}")
            if us % 10_000_000:
                raise ValueError(f"Off-grid timestamp {(EPOCH + timedelta(microseconds=us)).isoformat()}; expected 10-second samples")
            slot = within_day // 10_000_000
            stat = hosts.get(host)
            if stat is None:
                stat = hosts[host] = HostStats()
            byte, bit = divmod(slot, 8)
            if stat.slots[byte] & (1 << bit):
                raise ValueError(f"Duplicate (hostname,timestamp): {host}, {(EPOCH + timedelta(microseconds=us)).isoformat()}")
            stat.slots[byte] |= 1 << bit
            stat.rows += 1
            stat.missing_features += 18 - mask.bit_count()
            stat.valid += mask == FULL_MASK
            minimum = us if minimum is None else min(minimum, us)
            maximum = us if maximum is None else max(maximum, us)
        for f in FEATURES:
            missing[f] += prepared[f].null_count
        rows += len(prepared)
        if rows // 1_000_000 != (rows-len(prepared)) // 1_000_000:
            print(f'Scan rows={rows}/{pf.metadata.num_rows}', flush=True)
    if day is None:
        raise ValueError(f"Empty raw file: {path}")
    return DayStats(path, day, hosts, rows, missing,
                    (EPOCH + timedelta(microseconds=minimum)).isoformat(),
                    (EPOCH + timedelta(microseconds=maximum)).isoformat())


def validate_days(days: list[DayStats]):
    dates = [datetime.fromisoformat(d.date).date() for d in days]
    if len(dates) != 3 or dates[1] != dates[0] + timedelta(days=1) or dates[2] != dates[1] + timedelta(days=1):
        raise ValueError(f"D1 < D2 < D3 must be three consecutive UTC days: {dates}")
    if len({(d.year, d.month) for d in dates}) != 1:
        raise ValueError("D1/D2/D3 must belong to one monthly segment")


def select_groups(days: list[DayStats], count=16):
    common = set(days[0].hosts).intersection(*(d.hosts for d in days[1:]))
    all_groups: dict[str, dict[int, set[str]]] = {}
    for host in set().union(*(d.hosts for d in days)):
        group, node = parse_hostname(host)
        all_groups.setdefault(group, {}).setdefault(node, set()).add(host)
    eligible = []
    for group, positions in all_groups.items():
        if set(positions) != set(range(1, 19)) or any(len(v) != 1 for v in positions.values()):
            continue
        hosts = sorted(next(iter(v)) for v in positions.values())
        if not set(hosts) <= common:
            continue
        rows = sum(d.hosts[h].rows for d in days for h in hosts)
        missing = sum(d.hosts[h].missing_features for d in days for h in hosts)
        eligible.append((group, hosts, rows, missing))
    # Full structural coverage first; then observed states, missingness and lexical tie-break.
    eligible.sort(key=lambda g: (-g[2], g[3] / (g[2] * 18), g[0]))
    if len(eligible) < count:
        raise ValueError(f"Only {len(eligible)} complete groups present on all days; require {count}")
    return eligible[:count], eligible
