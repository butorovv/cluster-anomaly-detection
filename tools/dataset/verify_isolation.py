"""Read-only NumPy/PyArrow oracle for the saved Go forest on D1 only.

This checks scoring and descriptive statistics, not RNG equivalence or fitting.
Requires numpy and pyarrow; neither is part of the Go runtime.
"""
import argparse
import hashlib
import json
import math
import time
from pathlib import Path

import numpy as np
import pyarrow
import pyarrow.parquet as pq


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", type=Path, required=True)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--statistical-profile", type=Path, required=True)
    args = parser.parse_args()
    started = time.perf_counter()
    run = json.loads(args.profile.read_text(encoding="utf-8"))
    forest = run["isolation_forest"]
    with args.input.open("rb") as stream:
        assert hashlib.file_digest(stream, "sha256").hexdigest() == run["source"]["prepared_sha256"]
    statistical_bytes = args.statistical_profile.read_bytes()
    assert hashlib.sha256(statistical_bytes).hexdigest() == run["statistical_reference"]["file_sha256"]
    statistical = json.loads(statistical_bytes)["statistical_profile"]
    for key in ("median", "mad", "effective_scale"):
        assert forest[key] == statistical[key]
    assert forest["training_window"] == {
        "start": "2022-01-18T00:00:00Z", "end_exclusive": "2022-01-18T08:00:00Z"
    }
    names = run["feature_order"]
    assert len(names) == 18 and len(set(names)) == 18
    assert len(forest["trees"]) == forest["config"]["trees"]
    size = forest["effective_sample_size"]
    # Independent harmonic summation; do not use the Go cache or log approximation.
    c = np.array([0 if n < 2 else 2 * math.fsum(1 / k for k in range(1, n)) - 2 * (n - 1) / n
                  for n in range(size + 1)])

    def paths(rows, node, depth, result, indices):
        if "left" not in node:
            result[indices] = depth + c[node["size"]]
            return
        left = rows[indices, node["feature"]] < node["split"]
        paths(rows, node["left"], depth + 1, result, indices[left])
        paths(rows, node["right"], depth + 1, result, indices[~left])

    start = np.datetime64("2022-01-18T00:00:00", "us")
    end = np.datetime64("2022-01-18T08:00:00", "us")
    scores = []
    states = 0
    for batch in pq.ParquetFile(args.input).iter_batches(
            batch_size=8192, columns=["timestamp", "is_valid"] + names):
        timestamps = batch.column(0).to_numpy().astype("datetime64[us]")
        if timestamps[0] >= end:
            break
        selected = (timestamps >= start) & (timestamps < end)
        states += int(np.count_nonzero(selected))
        selected &= batch.column(1).to_numpy(zero_copy_only=False)
        if not np.any(selected):
            continue
        rows = np.column_stack([batch.column(j + 2).to_numpy(zero_copy_only=False)[selected]
                                for j in range(18)])
        rows = (rows - forest["median"]) / forest["effective_scale"]
        assert np.isfinite(rows).all()
        total = np.zeros(len(rows))
        indices = np.arange(len(rows))
        for tree in forest["trees"]:
            result = np.zeros(len(rows))
            paths(rows, tree, 0, result, indices)
            total += result
        scores.append(np.exp2(-total / len(forest["trees"]) / c[size]))
    values = np.concatenate(scores)
    expected = run["d1_diagnostics"]["scores"]
    assert states == run["training_audit"]["states"] == 829440
    assert len(values) == expected["count"] == forest["observations"]
    actual = {"min": float(values.min()), "max": float(values.max()),
              "mean": float(values.mean()), "population_stddev": float(values.std())}
    for name, q in (("q01", .01), ("q50", .5), ("q95", .95), ("q99", .99)):
        actual[name] = float(np.quantile(values, q, method="inverted_cdf"))
    differences = {key: abs(value - expected[key]) for key, value in actual.items()}
    assert max(differences.values()) < 1e-12, differences
    print(json.dumps({"numpy": np.__version__, "pyarrow": pyarrow.__version__,
                      "count": len(values), "scores": actual,
                      "absolute_differences": differences,
                      "elapsed_seconds": time.perf_counter() - started}, indent=2))


if __name__ == "__main__":
    main()
