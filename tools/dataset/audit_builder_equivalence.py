"""Compare old/new prepare_day on synthetic telemetry only; never rebuild Summit."""
import argparse
import json
import random
import subprocess
import tempfile
import time
import types
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

import build_dataset
import common


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base', default='44be030f1b2bf254a576184e33776106f6ed3627')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise ValueError('Refusing to overwrite measurements')
    source = subprocess.check_output(['git', '-c', f'safe.directory={Path.cwd().as_posix()}',
                                     'show', f'{args.base}:tools/dataset/build_dataset.py'])
    old = types.ModuleType('audit_old_builder')
    exec(compile(source, '<frozen baseline builder>', 'exec'), old.__dict__)
    hosts = [f'a{g:02}n{n:02}' for g in range(1,17) for n in range(1,19)]
    rows = [(t, h) for t in range(64) for h in hosts]
    random.Random(20261016).shuffle(rows)
    start = datetime(2024, 2, 27, tzinfo=timezone.utc)
    columns = {'clock': pa.array([start+timedelta(seconds=10*t) for t,_ in rows], type=pa.timestamp('us', tz='UTC')),
               'machine': pa.array([h for _,h in rows])}
    for j, name in enumerate(common.FEATURES):
        columns[name] = pa.array([None if (i+j)%101 == 0 else (float('nan') if (i+j)%103 == 0 else 100.+(i+j)%17)
                                 for i in range(len(rows))], type=pa.float64())
    mapping = dict(timestamp='clock', hostname='machine', features={f:f for f in common.FEATURES})
    results = {}
    with tempfile.TemporaryDirectory(prefix='builder-audit-', dir='.cache') as temp:
        root = Path(temp); raw = root/'raw.parquet'
        pq.write_table(pa.table(columns), raw)
        day = common.scan_day(raw, mapping)
        for label, module in [('baseline', old), ('candidate', build_dataset)]:
            scratch = root/label; scratch.mkdir()
            peak = [0]; calls = [0]
            original = module.guard
            def measure(path, reserve=64*1024**2):
                calls[0] += 1
                db = scratch/'sort.sqlite'
                if db.exists():
                    peak[0] = max(peak[0], db.stat().st_size)
                return original(path, reserve)
            module.guard = measure
            try:
                target = scratch/'prepared.parquet'; tick = time.perf_counter()
                stats = module.prepare_day(day, mapping, hosts, target, scratch)
                elapsed = time.perf_counter()-tick
            finally:
                module.guard = original
            results[label] = dict(seconds=elapsed, sqlite_peak_bytes_at_guard=peak[0],
                parquet_bytes=target.stat().st_size, parquet_sha256=common.file_hash(target), guard_calls=calls[0],
                legacy_stats={k:stats[k] for k in ['rows','valid','invalid','missing_features','missing_samples','coverage']})
    assert results['baseline']['parquet_sha256'] == results['candidate']['parquet_sha256']
    assert results['baseline']['legacy_stats'] == results['candidate']['legacy_stats']
    result = dict(base_commit=args.base, seed=20261016, synthetic_only=True, host_ticks=len(rows),
                  interpretation='One small synthetic run; not a full-day disk capacity estimate or performance superiority test',
                  byte_identical=True, results=results)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2)+'\n', encoding='utf-8')
    print(json.dumps(result))


if __name__ == '__main__':
    main()
