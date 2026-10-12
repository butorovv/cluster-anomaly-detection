"""Resume D1 COPY in bounded committed windows, measuring storage and WAL."""
import argparse
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import shutil
import time

import psycopg

from common import file_hash
from disk_guard import MIN_FREE, guard
from import_postgres import import_dataset


def storage(url, path):
    with psycopg.connect(url) as conn:
        database, heap, indexes, total, lsn = conn.execute("SELECT pg_database_size(current_database()), pg_relation_size('project.telemetry'), pg_indexes_size('project.telemetry'), pg_total_relation_size('project.telemetry'), pg_current_wal_lsn()::text").fetchone()
        wal = conn.execute('SELECT coalesce(sum(size),0) FROM pg_ls_waldir()').fetchone()[0]
    return dict(database_bytes=database, telemetry_heap_bytes=heap, telemetry_index_bytes=indexes,
                telemetry_total_bytes=total, wal_directory_bytes=int(wal), wal_lsn=lsn,
                free_bytes=shutil.disk_usage(path.resolve().anchor).free)


def save(path, state):
    temp = path.with_suffix('.tmp.json')
    temp.write_text(json.dumps(state, indent=2, allow_nan=False)+'\n', encoding='utf-8')
    os.replace(temp, path)


def validate_progress(state, day):
    next_time = day
    measurements = states = 0
    for window in state['windows']:
        start, end = map(datetime.fromisoformat, (window['start'], window['end']))
        if start != next_time or not start < end <= min(start+timedelta(minutes=10), day+timedelta(days=1)):
            raise ValueError('Progress windows are not contiguous or exceed the pilot day')
        if not 0 <= window['inserted_measurements'] <= window['finite_measurements'] <= window['states']*18:
            raise ValueError('Invalid progress counts')
        measurements += window['finite_measurements']
        states += window['states']
        next_time = end
    if (state['measurements'], state['states'], state['next_timestamp']) != (measurements, states, next_time.isoformat()):
        raise ValueError('Progress summary differs from committed windows')


def reconcile(url, manifest, state, day):
    validate_progress(state, day)
    next_time = datetime.fromisoformat(state['next_timestamp'])
    with psycopg.connect(url) as conn:
        hosts = {r[0] for r in conn.execute('SELECT hostname FROM project.node')}
        if not hosts and state['measurements'] == state['states'] == 0:
            if conn.execute('SELECT count(*) FROM project.telemetry').fetchone()[0] == 0:
                return
        if hosts != set(manifest['selected_hosts']):
            raise ValueError('Dev nodes differ from this pilot topology')
        committed, total, minimum, maximum = conn.execute('SELECT count(*) FILTER (WHERE ts < %s),count(*),min(ts),max(ts) FROM project.telemetry', (next_time,)).fetchone()
        if committed != state['measurements'] or (minimum and minimum < day) or (maximum and maximum >= min(next_time+timedelta(minutes=10), day+timedelta(days=1))):
            raise ValueError('Database coverage differs from checkpoint; reconcile before continuing')
        # At most one fully committed window can precede its checkpoint. Replaying
        # that window verifies every existing value before recording its coverage.
        if total-committed > 10*6*288*18:
            raise ValueError('Unrecorded database coverage exceeds one import window')


def verify(url, expected):
    with psycopg.connect(url) as conn:
        # Stream the existing unique index; avoid a day-sized hash aggregate/temp sort.
        conn.execute('SET LOCAL enable_hashagg = off')
        rows, minimum, maximum = conn.execute('SELECT count(*),min(ts),max(ts) FROM project.telemetry').fetchone()
        duplicate = conn.execute('SELECT 1 FROM project.telemetry GROUP BY metric_source_id,ts HAVING count(*)>1 LIMIT 1').fetchone()
        nodes = conn.execute('SELECT count(*) FROM project.node').fetchone()[0]
        sources = conn.execute('SELECT count(*) FROM project.metric_source').fetchone()[0]
        if rows != expected or duplicate or nodes != 288 or sources != 5184:
            raise ValueError(f'Verification failed: rows={rows}, expected={expected}, duplicate={duplicate}, nodes={nodes}, sources={sources}')
        return dict(measurements=rows, timestamp_min=minimum.astimezone(timezone.utc).isoformat() if minimum else None,
                    timestamp_max=maximum.astimezone(timezone.utc).isoformat() if maximum else None, nodes=nodes, metric_sources=sources, duplicates=0)


def run(prepared, url, until_minutes=None):
    prepared = Path(prepared)
    if until_minutes is not None and not 1 <= until_minutes <= 1440:
        raise ValueError('until-minutes must be in 1..1440')
    # Restrict real-data writes to the explicitly requested development database.
    with psycopg.connect(url) as conn:
        if conn.execute('SELECT current_database()').fetchone()[0] != 'cluster_anomaly_dev':
            raise ValueError('Pilot runner only writes cluster_anomaly_dev')
    manifest = json.loads((prepared/'manifest.json').read_text(encoding='utf-8'))
    if manifest.get('dataset_mode') != 'D1-pilot':
        raise ValueError('D1 pilot manifest required')
    digest = file_hash(prepared/'D1.parquet')
    if digest != manifest['prepared_file_hashes']['D1.parquet']:
        raise ValueError('Prepared hash mismatch')
    progress_path = prepared/'import-progress.json'
    day = datetime.fromisoformat(manifest['D1_date']).replace(tzinfo=timezone.utc)
    limit = day+timedelta(minutes=until_minutes) if until_minutes else day+timedelta(days=1)
    if progress_path.exists():
        state = json.loads(progress_path.read_text(encoding='utf-8'))
        if state['prepared_sha256'] != digest:
            raise ValueError('Progress belongs to different prepared bytes')
        reconcile(url, manifest, state, day)
    else:
        with psycopg.connect(url) as conn:
            count = conn.execute('SELECT count(*) FROM project.telemetry').fetchone()[0]
        if count:
            raise ValueError('Nonempty dev telemetry without progress; reconcile before running')
        state = dict(prepared_sha256=digest, next_timestamp=day.isoformat(), measurements=0,
                     states=0, windows=[], baseline=storage(url, prepared))
    state['status'] = 'running'
    save(progress_path, state)
    start = datetime.fromisoformat(state['next_timestamp'])
    try:
        while start < limit:
            if (prepared/'STOP_IMPORT').exists():
                raise OSError('STOP_IMPORT marker found; remove marker to resume')
            free = guard(prepared, 256*1024**2)
            # Near the floor use two-minute windows to keep transient allocations small.
            minutes = 2 if free < MIN_FREE + 1024**3 else 10
            end = min(start+timedelta(minutes=minutes), limit)
            before = storage(url, prepared)
            began = time.monotonic()
            result = import_dataset(prepared, url, start=start, end=end, verify_hashes=False)
            elapsed = time.monotonic()-began
            after = storage(url, prepared)
            with psycopg.connect(url) as conn:
                wal_generated = int(conn.execute('SELECT pg_wal_lsn_diff(%s::pg_lsn,%s::pg_lsn)',
                                                (after['wal_lsn'], before['wal_lsn'])).fetchone()[0])
            # A commit may precede this atomic checkpoint. On resume COPY verifies values
            # and ON CONFLICT skips that window; finite counts still describe its coverage.
            state['measurements'] += result['finite_measurements']
            state['states'] += result['states']
            state['next_timestamp'] = end.isoformat()
            window = dict(start=start.isoformat(), end=end.isoformat(), seconds=elapsed, **result,
                          before=before, after=after, wal_generated_bytes=wal_generated)
            state['windows'].append(window)
            save(progress_path, state)
            print(json.dumps(window), flush=True)
            if end == day+timedelta(minutes=10):
                state['ten_minute_verification'] = verify(url, state['measurements'])
                repeat = import_dataset(prepared, url, start=day, end=end, verify_hashes=False)
                if repeat['inserted_measurements']:
                    raise ValueError('Repeat import inserted duplicates')
                state['repeat_import'] = repeat
                save(progress_path, state)
            if end == day+timedelta(hours=1):
                state['hour_verification'] = verify(url, state['measurements'])
                factor = 24
                state['day_estimate_at_one_hour'] = dict(
                    telemetry_bytes=after['telemetry_total_bytes']*factor,
                    seconds=sum(w['seconds'] for w in state['windows'])*factor,
                    available_above_floor=after['free_bytes']-MIN_FREE,
                    remaining_telemetry_bytes=after['telemetry_total_bytes']*(factor-1),
                    remaining_storage_with_wal_reserve=after['telemetry_total_bytes']*(factor-1)+
                    max(after['wal_directory_bytes'], 1024**3)+512*1024**2,
                    fits_conservative_estimate=after['free_bytes']-MIN_FREE >=
                    after['telemetry_total_bytes']*(factor-1)+max(after['wal_directory_bytes'], 1024**3)+512*1024**2)
                save(progress_path, state)
                print(json.dumps(state['day_estimate_at_one_hour']), flush=True)
            start = end
        state['status'] = 'complete' if start == day+timedelta(days=1) else 'stage_complete'
    except (OSError, KeyboardInterrupt) as exc:
        state['status'] = 'stopped_safely'
        state['stop_reason'] = str(exc) or 'KeyboardInterrupt'
        print(state['stop_reason'], flush=True)
    except Exception as exc:
        state['status'] = 'failed'
        state['stop_reason'] = f'{type(exc).__name__}: {exc}'
        raise
    finally:
        state['storage'] = storage(url, prepared)
        save(progress_path, state)
        manifest['postgres_import'] = {k: state[k] for k in ('status', 'measurements', 'states', 'next_timestamp')}
        manifest['postgres_import']['progress_file'] = progress_path.name
        save(prepared/'manifest.json', manifest)
    return state


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--prepared', type=Path, required=True)
    parser.add_argument('--postgres', default=os.environ.get('DATABASE_URL'))
    parser.add_argument('--until-minutes', type=int)
    args = parser.parse_args()
    if not args.postgres:
        parser.error('Supply DATABASE_URL or --postgres')
    result = run(args.prepared, args.postgres, args.until_minutes)
    print(json.dumps({k: result[k] for k in ('status', 'measurements', 'states', 'next_timestamp', 'storage')}), flush=True)
