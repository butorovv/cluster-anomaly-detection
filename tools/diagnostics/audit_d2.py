"""Independent arithmetic checks and exact joins; reads existing D2 exports only."""
import argparse
import hashlib
import json
import math
from pathlib import Path

import numpy as np

from analyze_d2 import DTYPE


def correction(n):
    return 0.0 if n <= 1 else 2 * math.fsum(1 / k for k in range(1, n)) - 2 * (n - 1) / n


def tree_path(node, vector):
    depth = 0
    while node["feature"] >= 0:
        node = node["left"] if vector[node["feature"]] < node["split"] else node["right"]
        depth += 1
    return depth + correction(node["size"])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--export", type=Path, default=Path("results/d2-diagnostics-v1"))
    parser.add_argument("--annotations", type=Path, default=Path("results/d2-diagnostics-v1/raw-annotations-v2.json"))
    args = parser.parse_args()
    meta = json.loads((args.export / "metadata.json").read_text(encoding="utf-8"))
    summary = json.loads((args.export / "summary.json").read_text(encoding="utf-8"))
    annotations = json.loads(args.annotations.read_text(encoding="utf-8"))
    data = np.memmap(args.export / "states.bin", mode="r", dtype=DTYPE)
    hosts = meta["source"]["hosts"]
    forest = json.loads(Path("results/isolation-20220118-v1.json").read_text(encoding="utf-8"))["isolation_forest"]
    # Separate implementation of c(n), tree traversal and IF scoring, fixed sample.
    indices = np.random.default_rng(123).choice(len(data), 1024, replace=False)
    indices = np.unique(np.concatenate([indices, [e["index"] for e in summary["examples"]]]))
    maximum_score_difference = 0.0
    for i in indices:
        vector = (data[i]["features"] - forest["median"]) / forest["effective_scale"]
        mean_path = math.fsum(tree_path(t, vector) for t in forest["trees"]) / len(forest["trees"])
        score = 2 ** (-mean_path / correction(forest["effective_sample_size"]))
        maximum_score_difference = max(maximum_score_difference, abs(score - data[i]["score"]))
    assert maximum_score_difference < 1e-14
    # Direct pair-by-pair expected count, independent of the convolution in analysis.
    binary = (data["score"] > summary["theta_if"]).reshape(2880, 288)
    frequencies = binary.mean(axis=0)
    expected = []
    for g in range(16):
        p = frequencies[g*18:(g+1)*18]
        expected.append(2880 * math.fsum(p[i]*p[j] for i in range(18) for j in range(i+1,18)))
    expected_error = max(abs(a - b["pair_bins"]) for a,b in zip(expected,summary["analytic_shift_expectations"]))
    assert expected_error < 1e-9
    # Exact timestamp/host matching under the manifest's time assumption.
    joined = []
    for row in annotations["nonzero_label_or_positive_xid_rows"]:
        timestamp = int(np.datetime64(row["timestamp"], "us").astype("int64"))
        delta = timestamp - int(data[0]["timestamp"])
        assert delta % 10_000_000 == 0
        t = delta // 10_000_000
        assert 0 <= t < 2880
        h = hosts.index(row["hostname"])
        state = data[t*288+h]
        assert int(state["timestamp"]) == timestamp and int(state["host"]) == h
        joined.append(dict(row, score=float(state["score"]), distance=float(state["distance"]),
                           if_flag=bool(state["score"] > summary["theta_if"]),
                           maha_flag=bool(state["distance"] > summary["theta_mahalanobis"])))
    host_join = []
    for host in sorted({r["hostname"] for r in joined}):
        rows = [r for r in joined if r["hostname"] == host]
        host_join.append({"hostname":host,"rows":len(rows),"first":min(r["timestamp"] for r in rows),
            "last":max(r["timestamp"] for r in rows),"if_flags":sum(r["if_flag"] for r in rows),
            "maha_flags":sum(r["maha_flag"] for r in rows),
            "score_min":min(r["score"] for r in rows),"score_max":max(r["score"] for r in rows),
            "d2_min":min(r["distance"] for r in rows),"d2_max":max(r["distance"] for r in rows)})
    # Research outputs may be replaced; input files and models must remain identical.
    hashes = {}
    for path, expected_hash in meta["input_sha256"].items():
        with Path(path).open("rb") as stream:
            hashes[path] = hashlib.file_digest(stream,"sha256").hexdigest()
        assert hashes[path] == expected_hash, path
    runs = []
    for g in range(16):
        mask = binary[:,g*18:(g+1)*18].sum(axis=1) >= 2
        padded = np.r_[False,mask,False].astype(int)
        starts, ends = np.flatnonzero(np.diff(padded)==1), np.flatnonzero(np.diff(padded)==-1)
        for first,last in zip(starts,ends):
            runs.append({"group":f"a{g+1:02d}","start":str(np.datetime64(int(data[first*288]["timestamp"]),"us")),
                         "end_exclusive":str(np.datetime64(int(data[0]["timestamp"])+int(last)*10_000_000,"us")),
                         "duration_seconds":int((last-first)*10)})
    result = {"independent_if_states":len(indices),"independent_if_max_difference":maximum_score_difference,
        "independent_pair_expectation_max_difference":expected_error,"input_hashes_unchanged":hashes,
        "annotation_joined_rows":len(joined),"annotation_hosts":host_join,"ge2_intervals":runs,
        "annotation_rows":joined,"analytic_expected_global_pairs":sum(expected)}
    (args.export/"audit.json").write_text(json.dumps(result,indent=2,ensure_ascii=False),encoding="utf-8")
    print(json.dumps({k:v for k,v in result.items() if k not in ["annotation_rows","input_hashes_unchanged","ge2_intervals"]},indent=2))


if __name__ == "__main__":
    main()
