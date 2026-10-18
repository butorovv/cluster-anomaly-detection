"""Independent PR10 audit and D1-only zero-MAD coordinate exclusion diagnostic.

Does not import the runtime analysis helpers, change Go models, or read D3.
Outputs are exclusive: choose a new directory for each reproduction.
"""
import argparse
import csv
import hashlib
import json
import math
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

DTYPE = np.dtype([('timestamp', '<i8'), ('host', '<u4'), ('available', '<u4'),
                  ('features', '<f8', (18,)), ('scores', '<f8', (6,)), ('distance', '<f8')])
EXCLUDED = ['a02n09', 'a02n10', 'a09n05', 'a11n12']
DELTAS = [0, 10, 30, 60]


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def save(path, value):
    with path.open('x', encoding='utf-8', newline='\n') as stream:
        json.dump(value, stream, indent=2, allow_nan=False)
        stream.write('\n')


def channels(data):
    x = data['features'].reshape(2880, 16, 18, 18)
    return np.stack([x[..., 4:10].sum(-1), x[..., 2:4].sum(-1), x[..., :2].sum(-1),
                     x[..., 12:18].mean(-1), x[..., 10:12].mean(-1)], axis=-1)


def r_scores(z, eligible):
    # Score each channel and sign separately; two distinct eligible hosts.
    parts = []
    for sign in [-1, 1]:
        candidates = np.where(eligible[None], np.maximum(sign*z, 0), -np.inf)
        parts.append(np.partition(candidates, -2, axis=2)[:, :, -2, :])
    return np.maximum(*parts).max(axis=-1)


def runs(flags):
    result = []
    for g in range(16):
        edges = np.diff(np.r_[False, flags[:, g], False].astype(int))
        result.extend((g, int(a), int(b)) for a, b in zip(
            np.flatnonzero(edges == 1), np.flatnonzero(edges == -1), strict=True))
    return sorted(result)


def temporal(r, b, delta):
    # Complete observations only, inclusive causal [t-delta,t] window.
    def recent(x):
        padded = np.vstack([np.zeros((1, 16), dtype=int), x.cumsum(axis=0)])
        now = np.arange(1, len(x)+1)
        return padded[now]-padded[np.maximum(0, now-delta//10-1)] > 0
    return recent(r) & recent(b)


def iso(microseconds):
    return datetime.fromtimestamp(int(microseconds)/1e6, timezone.utc).isoformat().replace('+00:00', 'Z')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    # Reject an existing target before performing work; never replace baseline files.
    args.output.mkdir(parents=True, exist_ok=False)
    profile_path = Path('configs/group-profile.summit-v1.json')
    profile = json.loads(profile_path.read_text(encoding='utf-8'))
    meta = json.loads(Path('results/context-v1/metadata.json').read_text(encoding='utf-8'))
    original_paths = [profile_path, Path('configs/group-detection.summit-v1.json')]
    original_paths += sorted(Path('docs/group-runtime-v1').rglob('*'))
    original_paths = [p for p in original_paths if p.is_file()]
    before = {p.as_posix(): sha(p) for p in original_paths}
    exports = {}
    for window in ['D1', 'D2']:
        path = Path(f'results/context-v1/{window}.bin')
        assert sha(path) == meta['binary_sha256'][path.name]
        exports[window] = np.memmap(path, mode='r', dtype=DTYPE)
        d = exports[window]
        assert len(d) == 829440 and (d['available'] == 262143).all()
        times = d['timestamp'].reshape(2880, 288)
        assert (times == times[:, :1]).all() and (np.diff(times[:, 0]) == 10000000).all()
        ids = d['host'].reshape(2880, 288)
        assert (ids == np.arange(288)[None, :]).all()
    assert exports['D1']['timestamp'][-1]+10000000 == exports['D2']['timestamp'][0]
    u1 = channels(exports['D1'])
    med = np.median(u1, axis=0)
    mad = np.median(np.abs(u1-med), axis=0)
    scale = np.maximum(1.4826*mad, 1e-4)
    hosts = np.array(meta['source']['hosts']).reshape(16, 18)
    assert {str(hosts[g, h]) for g, h, k in zip(*np.where(mad == 0)) if k == 3} == set(EXCLUDED)
    assert int((mad == 0).sum()) == 4
    for g, p in enumerate(profile['groups']):
        assert p['hosts'] == hosts[g].tolist()
        for name, actual in [('host_median', med), ('host_mad', mad), ('host_scale', scale)]:
            np.testing.assert_allclose(actual[g], p[name], rtol=1e-12, atol=1e-12)
    eligible = np.ones((16, 18, 5), dtype=bool)
    for host in EXCLUDED:
        g, h = np.argwhere(hosts == host)[0]
        eligible[g, h, 3] = False
    baseline_eligible = np.ones_like(eligible)
    z1 = (u1-med)/scale
    base_train = r_scores(z1, baseline_eligible)
    alternative_train = r_scores(z1, eligible)
    q_index = math.ceil(.99*len(u1))-1
    base_q = np.sort(base_train, axis=0)[q_index]
    alt_q = np.sort(alternative_train, axis=0)[q_index]
    np.testing.assert_allclose(base_q, [p['r_q99'] for p in profile['groups']], rtol=1e-12, atol=1e-12)
    # All alternative parameters (including Q99) are finalized before D2 scoring.
    alternative_profile = dict(version='diagnostic-zero-mad-coordinate-exclusion-v1',
        training='D1 only; all 2880 ticks', excluded=[dict(hostname=h, channel=3) for h in EXCLUDED],
        floor=1e-4, mad_factor=1.4826, quantile='inverted CDF Q99', comparison='strict >',
        host_median=med.tolist(), host_mad=mad.tolist(), host_scale=scale.tolist(),
        r_q99=alt_q.tolist(), training_export_sha256=meta['binary_sha256']['D1.bin'],
        baseline_profile_sha256=before[profile_path.as_posix()], B='frozen baseline, unchanged')
    save(args.output/'diagnostic-r-profile.json', alternative_profile)
    u2 = channels(exports['D2'])
    z2 = (u2-med)/scale
    base_score, alt_score = r_scores(z2, baseline_eligible), r_scores(z2, eligible)
    base_r, alt_r = base_score > base_q, alt_score > alt_q
    vectors = np.concatenate([u2.mean(axis=2), u2.std(axis=2, ddof=0)], axis=-1)
    bscore = np.empty((2880, 16))
    for g, p in enumerate(profile['groups']):
        w = (vectors[:, g]-p['median'])/p['scale']-p['normalized_mean']
        bscore[:, g] = np.einsum('ti,ij,tj->t', w, p['pseudoinverse'], w)
    b = bscore > [p['b_q99'] for p in profile['groups']]
    b1 = json.loads(Path('configs/local-b1.summit-20220118.json').read_text(encoding='utf-8'))
    local_thresholds = np.array([b1['thresholds'][str(h)] for h in hosts.ravel()]).reshape(16, 18)
    local_flags = exports['D2']['scores'].reshape(2880, 16, 18, 6)[..., 0] > local_thresholds
    assert int(local_flags.sum()) == 14341
    support = local_flags.any(axis=2)
    s = local_flags.sum(axis=2)/18
    outside = (local_flags.sum(axis=(1, 2))[:, None]-local_flags.sum(axis=2))/270
    times = exports['D2']['timestamp'].reshape(2880, 288)[:, 0]
    with Path('docs/group-runtime-v1/d2/timeline.csv').open(encoding='utf-8', newline='') as stream:
        saved = list(csv.DictReader(stream))
    assert len(saved) == 46080
    for i, row in enumerate(saved):
        t, g = divmod(i, 16)
        assert row['timestamp'] == iso(times[t]) and row['group'] == f'a{g+1:02}' and row['Y'] == 'unknown'
        assert bool(int(row['R_positive'])) == base_r[t, g] and bool(int(row['B_positive'])) == b[t, g]
        assert float(row['R_threshold']) == base_q[g] and float(row['B_threshold']) == profile['groups'][g]['b_q99']
    np.testing.assert_allclose([float(row['R']) for row in saved], base_score.ravel(), rtol=1e-8, atol=1e-8)
    np.testing.assert_allclose([float(row['B_D2']) for row in saved], bscore.ravel(), rtol=1e-8, atol=1e-8)
    np.testing.assert_allclose([[float(row[f'v{k}']) for k in range(10)] for row in saved], vectors.reshape(-1, 10), rtol=1e-8, atol=1e-8)
    np.testing.assert_allclose([float(row['IF_S']) for row in saved], s.ravel(), rtol=1e-12, atol=1e-12)
    np.testing.assert_allclose([float(row['E']) for row in saved], (s-outside).ravel(), rtol=1e-12, atol=1e-12)
    events = json.loads(Path('docs/group-runtime-v1/d2/events.json').read_text(encoding='utf-8'))
    assert len({e['id'] for e in events}) == len(events)
    # Check saved occurrence timestamps as well as candidate counts.
    occurrence_indices = []
    for flags in [base_r, b]:
        ix = np.where(flags, np.arange(2880)[:, None], -10000)
        occurrence_indices.append(np.maximum.accumulate(ix, axis=0))
    with Path('docs/group-runtime-v1/d2/temporal.csv').open(encoding='utf-8', newline='') as stream:
        count = 0
        seen = set()
        for row in csv.DictReader(stream):
            delta = int(row['delta_seconds']); g = int(row['group'][1:])-1
            t = int((datetime.fromisoformat(row['timestamp']).timestamp()*1e6-int(times[0]))/10000000)
            assert delta in DELTAS and 0 <= t < 2880 and 0 <= g < 16
            assert row['timestamp'] == iso(times[t])
            key = (t, g, delta); assert key not in seen; seen.add(key)
            active = []
            for name, indices in zip(['R', 'B'], occurrence_indices, strict=True):
                ix = int(indices[t, g]); alive = t-ix <= delta//10
                assert int(row[f'temporal_{name}']) == int(alive)
                assert row[f'{name}_witness_time'] == (iso(times[ix]) if alive else '')
                active.append(alive)
            assert int(row['preliminary_candidate']) == int(all(active))
            count += 1
        assert count == 184320
    # Independent values, directions, distinct-host pairs and event witness unions.
    witnesses = {}
    zero_pairs = np.zeros_like(base_r)
    with Path('docs/group-runtime-v1/d2/r-evidence.ndjson').open(encoding='utf-8') as stream:
        for line in stream:
            row = json.loads(line); g = int(row['group'][1:])-1
            t = int((datetime.fromisoformat(row['timestamp']).timestamp()*1e6-int(times[0]))/10000000)
            assert base_r[t, g] and (t, g) not in witnesses
            options = [(float(np.sort(np.maximum(sign*z2[t, g, :, k], 0))[-2]), k, sign)
                       for k in range(5) for sign in [-1, 1]]
            score, k, sign = max(options, key=lambda x: x[0])
            order = np.argsort(-np.maximum(sign*z2[t, g, :, k], 0), kind='stable')[:2]
            pair = [str(hosts[g, h]) for h in order]
            evidence = row['r']
            assert evidence['channel'] == k and evidence['direction'] == sign
            assert [w['hostname'] for w in evidence['defining_pair']] == pair and len(set(pair)) == 2
            above = [str(hosts[g, h]) for h in range(18) if sign*z2[t, g, h, k] > base_q[g]]
            assert [w['hostname'] for w in evidence['witnesses']] == above
            for w in evidence['defining_pair']+evidence['witnesses']:
                h = list(hosts[g]).index(w['hostname'])
                np.testing.assert_allclose([w['value'], w['z'], w['amplitude']],
                    [u2[t, g, h, k], z2[t, g, h, k], u2[t, g, h, k]-med[g, h, k]], rtol=1e-8, atol=1e-8)
                assert w['zero_mad'] == bool(mad[g, h, k] == 0)
            witnesses[t, g] = set(pair+above)
            zero_pairs[t, g] = any(mad[g, h, k] == 0 for h in order)
        assert len(witnesses) == int(base_r.sum())
    measures, event_rows = [], []
    for delta in DELTAS:
        cb, ca = temporal(base_r, b, delta), temporal(alt_r, b, delta)
        expected = runs(cb)
        actual = sorted([e for e in events if e['delta_seconds'] == delta], key=lambda e: (e['group'], e['detected_event_time']))
        assert len(actual) == len(expected)
        for event, (g, a, end) in zip(actual, expected, strict=True):
            assert event['group'] == f'a{g+1:02}' and event['detected_event_time'] == iso(times[a])
            assert event['last_positive_time'] == iso(times[end-1])
            assert event['closed_event_time'] == iso(times[0]+end*10000000)
            assert event['positive_ticks'] == end-a and event['duration_grid_seconds'] == (end-a)*10
            assert event['if_supported_ticks'] == int(support[a:end, g].sum())
            assert event['criteria_incomplete'] and event['hardware_confirmation'] == 'insufficient_criteria'
            witness_union = set()
            zero_count = 0
            for t in range(a, end):
                ix = int(occurrence_indices[0][t, g])
                witness_union.update(witnesses[ix, g]); zero_count += int(zero_pairs[ix, g])
            assert event['witness_hosts'] == sorted(witness_union)
            assert event['zero_mad_pair_ticks'] == zero_count
            key = f"{event['run_id']}/{event['group']}/{delta}/{event['detected_event_time']}"
            assert event['id'] == hashlib.sha256(key.encode()).hexdigest()
        measures.append(dict(delta=delta, baseline_ticks=int(cb.sum()), diagnostic_ticks=int(ca.sum()),
            baseline_events=len(expected), diagnostic_events=len(runs(ca)),
            retained_ticks=int((cb & ca).sum()), removed_ticks=int((cb & ~ca).sum()), added_ticks=int((~cb & ca).sum())))
        for g, a, end in runs(ca):
            event_rows.append([f'a{g+1:02}', delta, iso(times[a]), iso(times[end-1]), iso(times[0]+end*10000000), end-a, (end-a)*10])
    base_runs, alt_runs = runs(base_r & b), runs(alt_r & b)
    per_group = []
    for g, p in enumerate(profile['groups']):
        per_group.append(dict(group=p['group'], baseline_q99=float(base_q[g]), diagnostic_q99=float(alt_q[g]),
            baseline_R=int(base_r[:, g].sum()), diagnostic_R=int(alt_r[:, g].sum()),
            R_removed=int((base_r[:, g] & ~alt_r[:, g]).sum()), R_added=int((~base_r[:, g] & alt_r[:, g]).sum()),
            B=int(b[:, g].sum()), baseline_RB=int((base_r[:, g] & b[:, g]).sum()),
            diagnostic_RB=int((alt_r[:, g] & b[:, g]).sum()),
            RB_removed=int((base_r[:, g] & b[:, g] & ~alt_r[:, g]).sum()),
            RB_added=int((~base_r[:, g] & b[:, g] & alt_r[:, g]).sum()),
            baseline_events=sum(x[0] == g for x in base_runs), diagnostic_events=sum(x[0] == g for x in alt_runs)))
    # Use the frozen report's tie-break: duration descending, group, start ascending.
    longest = min([e for e in events if e['delta_seconds'] == 0], key=lambda e: (-e['duration_grid_seconds'], e['group'], e['detected_event_time']))
    a = int((datetime.fromisoformat(longest['detected_event_time']).timestamp()*1e6-int(times[0]))/10000000)
    end = a+longest['positive_ticks']; g = int(longest['group'][1:])-1
    result = dict(status='PASS', interpretation='Sensitivity diagnostic only, not evidence of superiority or fault labels.',
        source_export_sha256={w: meta['binary_sha256'][w+'.bin'] for w in ['D1', 'D2']},
        numeric_tolerance=dict(rtol=1e-8, atol=1e-8),
        baseline=dict(R=int(base_r.sum()), B=int(b.sum()), RB=int((base_r & b).sum()), events=len(base_runs)),
        diagnostic=dict(R=int(alt_r.sum()), B=int(b.sum()), RB=int((alt_r & b).sum()), events=len(alt_runs)),
        R_changed=dict(removed=int((base_r & ~alt_r).sum()), added=int((~base_r & alt_r).sum())),
        per_group=per_group, temporal=measures,
        independent_audit=dict(group_vectors=46080, R_B_scores_and_decisions=46080,
            temporal_occurrences_and_witness_times=count, R_evidence=len(witnesses),
            event_intervals_ids_and_witness_unions=len(events), IF_support_and_outside_E=46080,
            B1_positive_host_states=int(local_flags.sum())),
        equally_long_baseline_events=[dict(group=e['group'], start=e['detected_event_time']) for e in events
            if e['delta_seconds'] == 0 and e['duration_grid_seconds'] == longest['duration_grid_seconds']],
        longest_baseline_event=dict(id=longest['id'], group=longest['group'], start=longest['detected_event_time'],
            last=longest['last_positive_time'], ticks=end-a, duration_seconds=longest['duration_grid_seconds'],
            diagnostic_positive_times=[iso(times[t]) for t in range(a, end) if alt_r[t, g] and b[t, g]],
            overlapping_diagnostic_events=[dict(start=iso(times[x]), last=iso(times[y-1]), ticks=y-x)
                for gg, x, y in alt_runs if gg == g and x < end and y > a],
            diagnostic_R_ticks=int(alt_r[a:end, g].sum()), diagnostic_RB_ticks=int((alt_r[a:end, g] & b[a:end, g]).sum()),
            diagnostic_R_score_range=[float(alt_score[a:end, g].min()), float(alt_score[a:end, g].max())], diagnostic_threshold=float(alt_q[g])))
    assert before == {p.as_posix(): sha(p) for p in original_paths}
    save(args.output/'baseline-sha256.json', before)
    save(args.output/'comparison.json', result)
    with (args.output/'diagnostic-events.csv').open('x', encoding='utf-8', newline='') as stream:
        writer = csv.writer(stream, lineterminator='\n')
        writer.writerow(['group', 'delta_seconds', 'detected', 'last_positive', 'closed', 'positive_ticks', 'duration_seconds'])
        writer.writerows(event_rows)
    with (args.output/'scores.csv').open('x', encoding='utf-8', newline='') as stream:
        writer = csv.writer(stream, lineterminator='\n')
        writer.writerow(['timestamp', 'group', 'baseline_R', 'baseline_Q99', 'diagnostic_R', 'diagnostic_Q99', 'B_positive'])
        for t in range(2880):
            for g in range(16):
                writer.writerow([iso(times[t]), f'a{g+1:02}', base_score[t, g], base_q[g], alt_score[t, g], alt_q[g], int(b[t, g])])
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
