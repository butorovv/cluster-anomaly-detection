"""Stream real Go replay against every prepared row; compare SQL F18 samples."""
import argparse
from datetime import datetime
import json
import os
from pathlib import Path
import re
import subprocess
import time

import psycopg
from psycopg.rows import dict_row
import pyarrow.parquet as pq

from common import BATCH_SIZE, FEATURES


def rows(path):
    for batch in pq.ParquetFile(path).iter_batches(batch_size=BATCH_SIZE):
        yield from batch.to_pylist()


def verify(prepared, binary, url):
    path = prepared/'D1.parquet'
    expected = iter(rows(path))
    result = {}
    records = completions = invalid = 0
    current = None
    count = valid = 0
    started = time.monotonic()
    with (prepared/'replayer-stderr.log').open('w', encoding='utf-8') as log:
        process = subprocess.Popen([str(binary.resolve()), '--input', str(path.resolve()), '--speed', '0', '--output', 'stdout'],
                                   stdout=subprocess.PIPE, stderr=log, text=True, encoding='utf-8')
        try:
            for line in process.stdout:
                sent = json.loads(line)
                ts = datetime.fromisoformat(sent['timestamp'])
                key = (ts, sent['group_id'])
                if sent['type'] == 'telemetry':
                    row = next(expected)
                    assert ts == row['timestamp']
                    assert all(sent[k] == row[k] for k in ('hostname', 'group_id', 'node_index', 'availability_mask', 'is_valid'))
                    assert sent['f18'] == [row[f] for f in FEATURES]
                    assert current is None or current == key
                    current = key
                    count += 1
                    valid += sent['is_valid']
                    invalid += not sent['is_valid']
                    records += 1
                else:
                    assert sent['type'] == 'timestamp_complete' and current == key
                    assert sent['records'] == count and sent['valid_records'] == valid
                    current, count, valid = None, 0, 0
                    completions += 1
            assert process.wait() == 0
            assert next(expected, None) is None and current is None
        except BaseException:
            process.terminate()
            process.wait()
            raise
    result['replayer'] = dict(records=records, timestamp_completions=completions, invalid_records=invalid,
                              seconds=time.monotonic()-started, every_row_compared=True)
    result['sql_f18_samples'] = verify_sql(prepared, url)
    (prepared/'real-verification.json').write_text(json.dumps(result, indent=2)+'\n', encoding='utf-8')
    return result


def verify_sql(prepared, url):
    path = prepared/'D1.parquet'
    sql = Path('db/queries/f18.sql').read_text(encoding='utf-8')
    sql = re.sub(r'\$1\b', '%(node)s', sql)
    sql = re.sub(r'\$2\b', '%(ts)s', sql)
    manifest = json.loads((prepared/'manifest.json').read_text(encoding='utf-8'))
    hosts = set(manifest['selected_hosts'][::48])
    samples = []
    with psycopg.connect(url, row_factory=dict_row) as conn:
        maximum = conn.execute('SELECT max(ts) ts FROM project.telemetry').fetchone()['ts']
        node_ids = {r['hostname']: r['id'] for r in conn.execute('SELECT id,hostname FROM project.node')}
        done = set()
        for row in rows(path):
            host = row['hostname']
            if row['timestamp'] > maximum:
                break
            if host not in hosts or host in done:
                continue
            actual = conn.execute(sql, {'node': node_ids[host], 'ts': row['timestamp']}).fetchone()
            assert all(actual[f] == row[f] for f in FEATURES)
            assert all(actual[k] == row[k] for k in ('timestamp', 'hostname', 'group_id', 'node_index'))
            samples.append(dict(hostname=host, timestamp=row['timestamp'].isoformat(), f18=[row[f] for f in FEATURES]))
            done.add(host)
            if done == hosts:
                break
        assert done == hosts
    return samples


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--prepared', type=Path, required=True)
    parser.add_argument('--binary', type=Path, default=Path('.tools/replayer.exe'))
    parser.add_argument('--postgres', default=os.environ.get('DATABASE_URL'))
    parser.add_argument('--only-sql', action='store_true')
    args = parser.parse_args()
    print(json.dumps(verify_sql(args.prepared, args.postgres) if args.only_sql else verify(args.prepared, args.binary, args.postgres)), flush=True)
