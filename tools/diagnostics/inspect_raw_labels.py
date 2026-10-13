"""Inspect existing raw label/XID/job metadata only inside the D2 selection."""
import argparse
import collections
import datetime as dt
import hashlib
import json
import math
import time
from pathlib import Path

import numpy as np
import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq


def key(value):
    if value is None:
        return "NULL"
    if isinstance(value, float) and not math.isfinite(value):
        return "NaN" if math.isnan(value) else str(value)
    return str(value)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw", type=Path, default=Path("data/raw/20220118.parquet"))
    parser.add_argument("--manifest", type=Path, default=Path("data/prepared/summit-D1-pilot/manifest.json"))
    parser.add_argument("--output", type=Path, default=Path("results/d2-diagnostics-v1/raw-labels.json"))
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError(args.output)
    started = time.perf_counter()
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    hosts = manifest["selected_hosts"]
    table = pq.ParquetFile(args.raw)
    columns = ["timestamp", "hostname", "label", "xid", "node_state", "allocation_id"]
    if not set(columns) <= set(table.schema_arrow.names):
        raise ValueError("required raw annotations not present")
    host_set = pa.array(hosts)
    counters = {c: collections.Counter() for c in columns[2:]}
    by_host = {h: {c: collections.Counter() for c in columns[2:]} for h in hosts}
    records, event_samples, scanned_groups = 0, [], []
    # Raw time is naive. This is the SAME unverified UTC interpretation used
    # by the prepared manifest, not new evidence for a timezone.
    start, end = dt.datetime(2022, 1, 18, 8), dt.datetime(2022, 1, 18, 16)
    timestamp_type = table.schema_arrow.field("timestamp").type
    for group in range(table.metadata.num_row_groups):
        stats = table.metadata.row_group(group).column(0).statistics
        if stats is not None and stats.has_min_max and (stats.max < start or stats.min >= end):
            continue
        scanned_groups.append(group)
        for batch in table.iter_batches(batch_size=65536, row_groups=[group], columns=columns):
            selected = pc.and_(pc.and_(pc.greater_equal(batch.column(0), pa.scalar(start, type=timestamp_type)),
                                      pc.less(batch.column(0), pa.scalar(end, type=timestamp_type))),
                               pc.is_in(batch.column(1), value_set=host_set))
            if not pc.any(selected).as_py():
                continue
            rows = batch.filter(selected).to_pydict()
            records += len(rows["hostname"])
            for c in columns[2:]:
                counters[c].update(key(v) for v in rows[c])
            for i, h in enumerate(rows["hostname"]):
                for c in columns[2:]:
                    by_host[h][c][key(rows[c][i])] += 1
                xid, label = rows["xid"][i], rows["label"][i]
                flagged = ((isinstance(label, (int, float)) and math.isfinite(label) and label != 0)
                           or (isinstance(xid, (int, float)) and math.isfinite(xid) and xid > 0))
                if flagged:
                    event_samples.append({c: key(rows[c][i]) for c in columns})
    assert records == 829440
    with args.raw.open("rb") as stream:
        raw_hash = hashlib.file_digest(stream, "sha256").hexdigest()
    result = {"raw_sha256": raw_hash, "timestamp_type": str(timestamp_type), "window_under_manifest_time_assumption": [str(start), str(end)],
              "records": records, "row_groups_read": scanned_groups, "counts": counters, "by_host": by_host,
              "nonzero_label_or_positive_xid_rows": event_samples, "elapsed_seconds": time.perf_counter()-started}
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2)
    print(json.dumps({k: result[k] for k in ["records", "timestamp_type", "counts", "nonzero_label_or_positive_xid_rows", "elapsed_seconds"]}, indent=2))


if __name__ == "__main__":
    main()
