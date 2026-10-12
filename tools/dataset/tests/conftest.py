"""Synthetic fixtures for the offline dataset contract tests."""
from __future__ import annotations

import json
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

DATASET_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(DATASET_DIR))

import common  # noqa: E402


@pytest.fixture
def synthetic_dataset(tmp_path):
    """17 groups, explicit arbitrary raw names, three consecutive UTC days."""
    raw_dir = tmp_path / "synthetic-raw"
    raw_dir.mkdir()
    features = {}
    fields = [pa.field("clock", pa.timestamp("us", tz="UTC")), pa.field("machine", pa.string())]
    for feature in common.FEATURES:
        if feature.startswith("cpu") and feature.endswith("mean_temp"):
            prefix = "sensor_a" if feature == "cpu0_mean_temp" else "sensor_b"
            features[feature] = [f"{prefix}_left", f"{prefix}_right"]
            fields.extend(pa.field(name, pa.float64()) for name in features[feature])
        else:
            name = f"raw_{feature}_reading"
            features[feature] = name
            fields.append(pa.field(name, pa.float64()))
    schema = pa.schema(fields)
    mapping = {"timestamp": "clock", "hostname": "machine", "features": features}
    mapping_path = tmp_path / "explicit-mapping.json"
    mapping_path.write_text(json.dumps(mapping), encoding="utf-8")
    paths = []
    start = date(2024, 2, 27)
    for day_index in range(3):
        day = start + timedelta(days=day_index)
        timestamps, hosts = [], []
        readings = {field.name: [] for field in fields[2:]}
        for group_index in range(17):
            group = f"{chr(ord('a') + group_index // 25)}{group_index % 25:02d}"
            for node in range(1, 19):
                host = f"{group}n{node}"
                for sample in range(2):
                    # One absent slot must not disqualify the otherwise complete group.
                    if group_index == 0 and node == 1 and day_index == 1 and sample == 1:
                        continue
                    timestamps.append(datetime.combine(day, datetime.min.time(), timezone.utc) + timedelta(seconds=10 * sample))
                    hosts.append(host)
                    for raw_name in readings:
                        readings[raw_name].append(float(node + sample))
        arrays = [pa.array(timestamps, type=schema.field("clock").type), pa.array(hosts)]
        arrays.extend(pa.array(readings[field.name], type=field.type) for field in fields[2:])
        path = raw_dir / f"raw-{day.isoformat()}.parquet"
        pq.write_table(pa.Table.from_arrays(arrays, schema=schema), path)
        paths.append(path)
    return {"tmp_path": tmp_path, "paths": paths, "mapping": mapping_path,
            "mapping_obj": mapping, "schema": schema, "output": tmp_path / "prepared-output"}
