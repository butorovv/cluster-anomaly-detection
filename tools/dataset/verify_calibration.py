"""Read-only D2 oracle: frozen forest, Mahalanobis labels and exact F1 sweep.

Requires NumPy/PyArrow. Does not fit models, change data or inspect D3 states.
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


def metrics(c):
    tp, fp, fn = c["tp"], c["fp"], c["fn"]
    return {"precision": tp / (tp + fp) if tp + fp else None,
            "recall": tp / (tp + fn) if tp + fn else None,
            "f1": 2 * tp / (2 * tp + fp + fn) if 2 * tp + fp + fn else None}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--calibration", type=Path, required=True)
    parser.add_argument("--isolation-profile", type=Path, required=True)
    parser.add_argument("--statistical-profile", type=Path, required=True)
    parser.add_argument("--input", type=Path, required=True)
    args = parser.parse_args()
    start_time = time.perf_counter()
    run = json.loads(args.calibration.read_text(encoding="utf-8"))
    forest_bytes = args.isolation_profile.read_bytes()
    statistical_bytes = args.statistical_profile.read_bytes()
    assert hashlib.sha256(forest_bytes).hexdigest() == run["isolation_reference"]["file_sha256"]
    assert hashlib.sha256(statistical_bytes).hexdigest() == run["statistical_reference"]["file_sha256"]
    with args.input.open("rb") as stream:
        assert hashlib.file_digest(stream, "sha256").hexdigest() == run["source"]["prepared_sha256"]
    forest_run = json.loads(forest_bytes)
    forest = forest_run["isolation_forest"]
    statistical = json.loads(statistical_bytes)["statistical_profile"]
    for key in ("median", "mad", "effective_scale"):
        assert forest[key] == statistical[key]
    assert run["comparison"] == "score > theta_if"
    assert run["selection_rule"] == "max_defined_f1_then_largest_observed_threshold"
    assert run["calibration_window"] == {
        "start": "2022-01-18T08:00:00Z", "end_exclusive": "2022-01-18T16:00:00Z"}
    assert run["mahalanobis_d1_threshold"] == statistical["mahalanobis_squared_threshold_q99"]
    names = run["feature_order"]
    assert names == forest_run["feature_order"] and len(names) == 18
    c = np.array([0 if n < 2 else 2 * math.fsum(1 / k for k in range(1, n)) - 2 * (n - 1) / n
                  for n in range(forest["effective_sample_size"] + 1)])

    def paths(rows, node, depth, result, indices):
        if "left" not in node:
            result[indices] = depth + c[node["size"]]
            return
        left = rows[indices, node["feature"]] < node["split"]
        paths(rows, node["left"], depth + 1, result, indices[left])
        paths(rows, node["right"], depth + 1, result, indices[~left])

    scores, controls = [], []
    start = np.datetime64("2022-01-18T08:00:00", "us")
    end = np.datetime64("2022-01-18T16:00:00", "us")
    states, timestamp_set, host_set = 0, set(), set()
    for batch in pq.ParquetFile(args.input).iter_batches(
            batch_size=8192, columns=["timestamp", "is_valid", "hostname"] + names):
        ts = batch.column(0).to_numpy().astype("datetime64[us]")
        if ts[0] >= end:
            break
        selected = (ts >= start) & (ts < end)
        states += int(np.count_nonzero(selected))
        timestamp_set.update(ts[selected].astype("int64").tolist())
        host_set.update(np.array(batch.column(2).to_pylist())[selected])
        selected &= batch.column(1).to_numpy(zero_copy_only=False)
        if not selected.any():
            continue
        raw = np.column_stack([batch.column(j + 3).to_numpy(zero_copy_only=False)[selected]
                               for j in range(18)])
        rows = (raw - statistical["median"]) / statistical["effective_scale"]
        assert np.isfinite(rows).all()
        total = np.zeros(len(rows))
        for tree in forest["trees"]:
            result = np.zeros(len(rows))
            paths(rows, tree, 0, result, np.arange(len(rows)))
            total += result
        scores.append(np.exp2(-total / len(forest["trees"]) / c[-1]))
        centered = rows - statistical["normalized_mean"]
        d2 = np.einsum("ij,jk,ik->i", centered, np.array(statistical["pseudoinverse"]), centered)
        controls.append(d2 > statistical["mahalanobis_squared_threshold_q99"])
    values, labels = np.concatenate(scores), np.concatenate(controls)
    assert states == len(values) == 829440
    assert len(timestamp_set) == 2880 and len(host_set) == 288
    order = np.argsort(values, kind="stable")
    sorted_values, sorted_labels = values[order], labels[order]
    # Suffix sums give strict predictions AFTER every entire equal-score block.
    block_ends = np.r_[np.flatnonzero(sorted_values[:-1] != sorted_values[1:]), len(values) - 1]
    positives = int(labels.sum())
    prefix = np.cumsum(sorted_labels, dtype=np.int64)
    tp_values = positives - prefix[block_ends]
    pred_values = len(values) - block_ends - 1
    fp_values = pred_values - tp_values
    fn_values = positives - tp_values
    denominators = 2 * tp_values + fp_values + fn_values
    best_num, best_den, best_index, ties = 0, 1, None, 0
    # Python integers provide independent exact cross-product comparison.
    for i in range(len(block_ends)):
        num, den = 2 * int(tp_values[i]), int(denominators[i])
        if den == 0:
            continue
        if best_index is None or num * best_den > best_num * den:
            best_num, best_den, best_index, ties = num, den, i, 1
        elif num * best_den == best_num * den:
            best_index, ties = i, ties + 1
    expected = run["calibration"]
    assert best_index is not None and expected["status"] == "calibrated"
    theta = float(sorted_values[block_ends[best_index]])
    predicted = values > theta
    confusion = {"tp": int(np.count_nonzero(predicted & labels)),
                 "fp": int(np.count_nonzero(predicted & ~labels)),
                 "fn": int(np.count_nonzero(~predicted & labels)),
                 "tn": int(np.count_nonzero(~predicted & ~labels))}
    actual_metrics = metrics(confusion)
    assert confusion == expected["confusion"], (confusion, expected["confusion"])
    assert positives == expected["control_positives"] == 9880
    assert int(predicted.sum()) == run["if_firings"]
    assert abs(theta - expected["theta_if"]) < 1e-12
    differences = {key: abs(actual_metrics[key] - expected["reference_metrics"][key])
                   for key in actual_metrics}
    assert max(differences.values()) < 1e-12
    print(json.dumps({"numpy": np.__version__, "pyarrow": pyarrow.__version__,
                      "states": states, "control_positives": positives,
                      "theta_if": theta, "theta_absolute_difference": abs(theta - expected["theta_if"]),
                      "candidates": len(block_ends), "go_candidates": expected["candidates"],
                      "maximal_f1_candidates": ties,
                      "undefined_f1_candidates": int(np.count_nonzero(denominators == 0)),
                      "confusion": confusion, "if_firings": int(predicted.sum()),
                      "reference_metrics": actual_metrics, "metric_absolute_differences": differences,
                      "elapsed_seconds": time.perf_counter() - start_time}, indent=2))


if __name__ == "__main__":
    main()
