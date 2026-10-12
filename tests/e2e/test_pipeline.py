"""Small synthetic cross-language fixtures; never creates production prepared data."""
from collections import Counter
from datetime import datetime
import json
import os
from pathlib import Path
import subprocess
import sys

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from common import FEATURES

ROOT = Path(__file__).resolve().parents[2]


def run(*args, expected=0):
    result = subprocess.run(args, cwd=ROOT, capture_output=True, text=True, timeout=60)
    assert result.returncode == expected, result.stdout + result.stderr
    return result


def test_actual_cli_inspector_builder_and_go_replay(synthetic_dataset):
    executable = os.environ.get("REPLAYER_BINARY")
    if not executable:
        pytest.skip("REPLAYER_BINARY not set: cross-language executable test not run")
    executable = str(Path(executable).resolve())
    fixture = synthetic_dataset
    # Explicit null/NaN/Inf fixtures verify both languages preserve availability.
    table = pq.read_table(fixture["paths"][2])
    rows = table.to_pylist()
    row = next(r for r in rows if r["machine"] == "a01n1")
    row[fixture["mapping_obj"]["features"][FEATURES[0]]] = None
    cpu = fixture["mapping_obj"]["features"]["cpu0_mean_temp"]
    row[cpu[0]], row[cpu[1]] = float("nan"), float("inf")
    pq.write_table(pa.Table.from_pylist(rows, schema=table.schema), fixture["paths"][2])
    report = fixture["tmp_path"] / "inspection.json"
    base = [sys.executable, "tools/dataset/inspect_dataset.py", *map(str, fixture["paths"]),
            "--timestamp-column", "clock", "--hostname-column", "machine", "--report", str(report)]
    diagnostic = run(*base, expected=2)
    assert "mapping remains unconfirmed" in diagnostic.stderr
    run(*base, "--mapping", str(fixture["mapping"]))
    inspected = json.loads(report.read_text(encoding="utf-8"))
    assert len(inspected) == 3 and inspected[2]["missingness"][cpu[0]] == 1
    command = [sys.executable, "tools/dataset/build_dataset.py",
               "--d1", str(fixture["paths"][0]), "--d2", str(fixture["paths"][1]),
               "--d3", str(fixture["paths"][2]), "--mapping", str(fixture["mapping"]),
               "--output", str(fixture["output"]), "--no-postgres"]
    run(*command)
    first = json.loads((fixture["output"] / "manifest.json").read_text(encoding="utf-8"))
    run(*command, "--replace-dataset")
    second = json.loads((fixture["output"] / "manifest.json").read_text(encoding="utf-8"))
    first.pop("build_timestamp"), second.pop("build_timestamp")
    assert first == second  # Topology, values, prepared bytes and statistics reproducible.
    path = fixture["output"] / "D3.parquet"
    replay = run(executable, "--input", str(path), "--speed", "0", "--output", "stdout")
    lines = [json.loads(line) for line in replay.stdout.splitlines()]
    records = [line for line in lines if line["type"] == "telemetry"]
    completions = [line for line in lines if line["type"] == "timestamp_complete"]
    expected = pq.read_table(path).to_pylist()
    assert len(records) == len(expected) == 576
    assert len(completions) == 32
    for sent, prepared in zip(records, expected):
        assert sent["hostname"] == prepared["hostname"]
        assert sent["group_id"] == prepared["group_id"]
        assert sent["node_index"] == prepared["node_index"]
        assert datetime.fromisoformat(sent["timestamp"]) == prepared["timestamp"]
        assert sent["f18"] == [prepared[f] for f in FEATURES]
        assert sent["is_valid"] == prepared["is_valid"]
        assert sent["availability_mask"] == prepared["availability_mask"]
    assert Counter((r["timestamp"], r["group_id"]) for r in records) == Counter({(c["timestamp"], c["group_id"]): c["records"] for c in completions})
    assert sum(not r["is_valid"] for r in records) == 1
    assert 'msg="replay finished"' in replay.stderr
    # Reading errors are returned, not hidden or replaced with synthetic telemetry.
    broken = fixture["tmp_path"] / "broken.parquet"
    broken.write_bytes(b"PAR1truncated")
    run(executable, "--input", str(broken), "--speed", "0", expected=1)
