"""Execute the committed validation protocol; never update the production model."""
import argparse
import collections
import csv
import json
import platform
import subprocess
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from tools.groupdiagnostics.d1 import host_channels
from tools.groupvalidation.common import (CHANNELS, PROTOCOL, candidates, clean, describe, dump,
    fit_group, grouping_metrics, index_of, load_data, score_group, segments, sha, stamp, validate_partition)


def csv_rows(path, rows):
    if not rows:
        return
    with path.open('x', encoding='utf-8', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]), lineterminator='\n')
        writer.writeheader(); writer.writerows(clean(rows))


def interval_metrics(data, results, g, a, end, nearest_seconds=60):
    flags = data['local_flags'].reshape(2880, 16, 18)
    subset = flags[a:end, g]
    witnesses = results[g]['witnesses'][a:end]
    offsets = np.flatnonzero(flags[max(0, a-nearest_seconds//10):min(2880, a+nearest_seconds//10+1), g].any(axis=1))
    offsets = offsets+max(0, a-nearest_seconds//10)-a
    delay = int(offsets[np.argmin(np.abs(offsets))]*10) if len(offsets) else None
    r = results[g]
    bq = data['profile']['groups'][g]['b_q99']
    physical = data['physical']
    reference = physical[max(0, a-30):a, g]
    delta = np.median(physical[a:end, g], axis=0)-np.median(reference, axis=0) if len(reference) else np.full(5, np.nan)
    p = data['profile']['groups'][g]
    amplitude = {}
    for k, name in enumerate(CHANNELS):
        mask = witnesses & (r['channel'][a:end] == k)[:, None]
        values = data['u2'][a:end, g*18:(g+1)*18, k]-np.asarray(p['host_median'])[:, k]
        amplitude[name] = describe(values[mask])
    return dict(group=f'a{g+1:02}', start=stamp(data['times'][a]), end_exclusive=stamp(data['times'][0]+end*10000000),
        duration_seconds=(end-a)*10, IF_tick_fraction=float(subset.any(axis=1).mean()),
        IF_distinct_hosts=int(subset.any(axis=0).sum()), IF_hosts_mean=float(subset.sum(axis=1).mean()),
        IF_hosts_max=int(subset.sum(axis=1).max()), IF_R_host_tick_intersection=int((subset & witnesses).sum()),
        IF_R_distinct_intersection=int((subset & witnesses).any(axis=0).sum()),
        IF_R_union_intersection=int((subset.any(axis=0) & witnesses.any(axis=0)).sum()),
        R_distinct_hosts=int(witnesses.any(axis=0).sum()), nearest_IF_delay_seconds=delay,
        R_channels=','.join(CHANNELS[k] for k in sorted(set(r['channel'][a:end][r['r'][a:end] == 1]))),
        R_witness_amplitudes=amplitude,
        R_witness_hosts=[data['hosts'][g*18+h] for h in np.flatnonzero(witnesses.any(axis=0))],
        B_ratio_mean=float(np.mean(r['b_score'][a:end]/bq)), B_ratio_max=float(np.max(r['b_score'][a:end]/bq)),
        R_ratio_max=float(np.max(r['r_score'][a:end]/data['profile']['groups'][g]['r_q99'])),
        physical_delta_reference_seconds=len(reference)*10,
        **{f'delta_{name}':float(v) for name, v in zip(CHANNELS, delta, strict=True)})


def match_control(candidate, complete, start, length, guard=6):
    bad = (candidate == 1) | ~complete
    prefix = np.r_[0, bad.cumsum()]
    starts = np.arange(len(candidate)-length+1)
    lo, hi = np.maximum(0, starts-guard), np.minimum(len(candidate), starts+length+guard)
    eligible = starts[(prefix[hi]-prefix[lo]) == 0]
    if not len(eligible):
        return None
    return int(min(eligible, key=lambda t: (t//360 != start//360, abs(t-start), t)))


def real_analysis(data, results):
    saved = json.loads(Path('docs/group-runtime-v1/d2/events.json').read_text(encoding='utf-8'))
    original = [e for e in saved if e['delta_seconds'] == 0]
    original.sort(key=lambda e: (e['group'], e['detected_event_time']))
    c = np.stack([candidates(x['r'], x['b']) for x in results], axis=1)
    actual = [(g, a, end) for g in range(16) for a, end in segments(c[:, g] == 1)]
    if len(actual) != 285 or len(original) != 285:
        raise ValueError('baseline event count changed')
    events, controls = [], []
    for e, (g, a, end) in zip(original, actual, strict=True):
        if e['group'] != f'a{g+1:02}' or e['detected_event_time'] != stamp(data['times'][a]):
            raise ValueError('baseline segmentation mismatch')
        if e['positive_ticks'] != end-a:
            raise ValueError('baseline interval mismatch')
        metric = interval_metrics(data, results, g, a, end)
        metric.update(event_id=e['id'], R_witness_host_count=len(e['witness_hosts']),
                      zero_MAD_pair_ticks=e['zero_mad_pair_ticks'])
        events.append(metric)
        matched = match_control(c[:, g], results[g]['complete'], a, end-a)
        if matched is None:
            controls.append(dict(event_id=e['id'], status='no_eligible_control'))
        else:
            control = interval_metrics(data, results, g, matched, matched+end-a)
            control.update(event_id=e['id'], status='matched', offset_seconds=(matched-a)*10,
                           same_start_hour=matched//360 == a//360)
            controls.append(control)
    metrics = ['IF_tick_fraction', 'IF_distinct_hosts', 'IF_hosts_mean', 'IF_hosts_max',
               'IF_R_host_tick_intersection', 'IF_R_distinct_intersection', 'nearest_IF_delay_seconds']
    matched = [x for x in controls if x['status'] == 'matched']
    key_counts = collections.Counter((x['group'], x['start'], x['end_exclusive']) for x in matched)
    summary = dict(events=len(events), matched=len(matched), unique_controls=len(key_counts),
        maximum_control_reuse=max(key_counts.values(), default=0),
        controls_same_start_hour=sum(x['same_start_hour'] for x in matched),
        events_by_start_hour=dict(collections.Counter(x['start'][11:13] for x in events)),
        event_R_witness_hosts=describe([x['R_distinct_hosts'] for x in events]),
        event_B_ratio_max=describe([x['B_ratio_max'] for x in events]),
        events_with_R_channel={k:sum(k in x['R_channels'].split(',') for x in events) for k in CHANNELS},
        event_metrics={k:describe([x[k] for x in events if x[k] is not None]) for k in metrics},
        control_metrics={k:describe([x[k] for x in matched if x[k] is not None]) for k in metrics},
        per_group=[dict(group=f'a{g+1:02}', events=sum(x['group'] == f'a{g+1:02}' for x in events),
            IF_tick_fraction=describe([x['IF_tick_fraction'] for x in events if x['group'] == f'a{g+1:02}']),
            IF_hosts_mean=describe([x['IF_hosts_mean'] for x in events if x['group'] == f'a{g+1:02}']),
            IF_R_intersection=describe([x['IF_R_distinct_intersection'] for x in events if x['group'] == f'a{g+1:02}'])) for g in range(16)])
    return events, controls, summary


def episode(data, results, a, end, label):
    physical = data['physical']
    local = data['local_flags'].reshape(2880, 16, 18)
    rows = []
    for g, x in enumerate(results):
        before = physical[max(0, a-30):a, g]
        change = np.median(physical[a:end, g], axis=0)-np.median(before, axis=0) if len(before) else np.full(5, np.nan)
        onsets = {}
        for key, flags in [('R', x['r'] == 1), ('B', x['b'] == 1), ('RB', candidates(x['r'], x['b']) == 1)]:
            hits = np.flatnonzero(flags[a:end])
            onsets[f'{key}_ticks'] = int(len(hits))
            onsets[f'{key}_first'] = stamp(data['times'][a+hits[0]]) if len(hits) else None
        rows.append(dict(group=f'a{g+1:02}', **onsets, IF_tick_fraction=float(local[a:end, g].any(axis=1).mean()),
            R_ratio_max=float(np.max(x['r_score'][a:end]/data['profile']['groups'][g]['r_q99'])),
            B_ratio_max=float(np.max(x['b_score'][a:end]/data['profile']['groups'][g]['b_q99'])),
            **{f'delta_{name}':float(v) for name, v in zip(CHANNELS, change, strict=True)}))
    correlations = {}
    for k, name in enumerate(CHANNELS):
        values = physical[a:end, 11:16, k]
        pairwise = []
        for g in range(5):
            for h in range(g+1, 5):
                if len(values) > 1 and np.std(values[:, g]) > 0 and np.std(values[:, h]) > 0:
                    pairwise.append(float(np.corrcoef(values[:, g], values[:, h])[0, 1]))
        correlations[name] = describe(pairwise)
    return dict(label=label, start=stamp(data['times'][a]), end_exclusive=stamp(data['times'][0]+end*10000000),
        reference_seconds=min(30, a)*10, per_group=rows, a12_a16_pairwise_physical_correlation=correlations)


def interventions(data, original, config, binary, output):
    # Only altered intervals are copied. Full unaffected results are reused exactly.
    host_index = {h:i for i, h in enumerate(data['hosts'])}
    probe_requests, updates, footprints = [], {}, {}
    for scenario in config['interventions']['scenarios']:
        sid = scenario['id']; changed = {}
        intervals = scenario.get('removals', [scenario])
        for part in intervals:
            a, end = [index_of(x, data['times'][0]) for x in [part['start'], part['end']]]
            if not 0 <= a < end <= 2880:
                raise ValueError('invalid intervention window')
            for t in range(a, end):
                for host in part['hosts']:
                    h = host_index[host]; g = h//18
                    values = changed.setdefault((t, g), np.array(data['f2'][t, g*18:(g+1)*18], copy=True))
                    if sid == 'F':
                        values[h % 18] = np.nan
                    else:
                        for change in scenario['changes']:
                            values[h % 18, change['features']] += change['add_each']
        updates[sid] = changed
        footprints[sid] = dict(groups=sorted({g for _, g in changed}), ticks=sorted({t for t, _ in changed}))
        for (t, g), values in sorted(changed.items()):
            for variant, features in [('baseline', data['f2'][t, g*18:(g+1)*18]), ('perturbed', values)]:
                records = [dict(hostname=data['hosts'][g*18+h], features=x.tolist()) for h, x in enumerate(features) if np.isfinite(x).all()]
                probe_requests.append(dict(id=f'{sid}/{t}/{g}/{variant}', timestamp=stamp(data['times'][t]), group=f'a{g+1:02}', records=records))
    request_path, response_path = output/'probe-input.ndjson', output/'probe-output.ndjson'
    with request_path.open('x', encoding='utf-8', newline='\n') as stream:
        for row in probe_requests:
            stream.write(json.dumps(row, separators=(',', ':'))+'\n')
    completed = subprocess.run([str(binary.resolve()), '--input', str(request_path), '--output', str(response_path)],
                               capture_output=True, text=True, timeout=180)
    if completed.returncode:
        raise RuntimeError(f'Go probe failed: {completed.stderr[:1000]}')
    responses = {}
    with response_path.open(encoding='utf-8') as stream:
        for line in stream:
            row = json.loads(line)
            if row['id'] in responses:
                raise ValueError('duplicate probe ID')
            responses[row['id']] = row['raw']
    if set(responses) != {x['id'] for x in probe_requests}:
        raise ValueError('incomplete Go probe responses')
    summaries, detail_rows = [], []
    base_c = np.stack([candidates(x['r'], x['b']) for x in original], axis=1)
    for scenario in config['interventions']['scenarios']:
        sid = scenario['id']
        altered = [{k:np.array(v, copy=True) for k, v in x.items()} for x in original]
        changed_local = data['local_flags'].reshape(2880, 16, 18).copy()
        availability = np.ones_like(changed_local)
        seen_groups = footprints[sid]['groups']; all_ticks = footprints[sid]['ticks']
        for (t, g), features in sorted(updates[sid].items()):
            availability[t, g] = np.isfinite(features).all(axis=1)
            raw_base = responses[f'{sid}/{t}/{g}/baseline']
            raw = responses[f'{sid}/{t}/{g}/perturbed']
            for key, field in [('r', 'r_score'), ('b', 'b_score')]:
                np.testing.assert_allclose(raw_base[key]['score'], original[g][field][t], rtol=1e-8, atol=1e-8)
                assert (raw_base[key]['state'] == 'positive') == (original[g][key][t] == 1)
            expected = score_group(data['profile']['groups'][g], host_channels(features)[None, ...])
            if raw['y']['state'] != 'unknown':
                raise ValueError('unexpected real hardware confirmation')
            for key, field in [('r', 'r_score'), ('b', 'b_score')]:
                code = {'unknown':-1, 'negative':0, 'positive':1}[raw[key]['state']]
                if code != int(expected[key][0]):
                    raise ValueError('Go/Python perturbation decision mismatch')
                if code >= 0:
                    np.testing.assert_allclose(raw[key]['score'], expected[field][0], rtol=1e-8, atol=1e-8)
                altered[g][key][t] = code
                altered[g][field][t] = raw[key]['score'] if code >= 0 else np.nan
            for key in ['witnesses', 'channel', 'direction', 'complete']:
                altered[g][key][t] = expected[key][0]
            for h, local in enumerate(raw['local']):
                assert local['hostname'] == data['hosts'][g*18+h]
                changed_local[t, g, h] = bool(local['is_available'] and local['is_anomaly'])
                if sid != 'F':
                    assert raw_base['local'][h]['anomaly_score'] == data['local_scores'][t, g*18+h]
            detail_rows.append(dict(scenario=sid, timestamp=stamp(data['times'][t]), group=f'a{g+1:02}',
                R_baseline=float(original[g]['r_score'][t]), R_perturbed=raw['r']['score'],
                B_baseline=float(original[g]['b_score'][t]), B_perturbed=raw['b']['score'],
                R_state=raw['r']['state'], B_state=raw['b']['state'], complete_hosts=raw['complete_hosts'],
                IF_baseline=int(data['local_flags'][t, g*18:(g+1)*18].sum()), IF_perturbed=raw['if']['anomalous'],
                R_witness_hosts=','.join(w['hostname'] for w in raw['r'].get('witnesses') or [])))
        c = np.stack([candidates(x['r'], x['b']) for x in altered], axis=1)
        extra = (c == 1) & (base_c != 1)
        outside = [g for g in range(16) if g not in seen_groups]
        interval = np.ix_(all_ticks, seen_groups)
        extra_in = extra[interval]
        first_extra = np.flatnonzero(extra_in.any(axis=1))
        groups = []
        s_before = data['local_flags'].reshape(2880, 16, 18).sum(axis=2)/18
        s_after = np.divide(changed_local.sum(axis=2), availability.sum(axis=2),
            out=np.full((2880, 16), np.nan), where=availability.sum(axis=2) > 0)
        outside_before = (data['local_flags'].sum(axis=1)[:, None]-s_before*18)/270
        outside_num = changed_local.sum(axis=(1, 2))[:, None]-changed_local.sum(axis=2)
        outside_den = availability.sum(axis=(1, 2))[:, None]-availability.sum(axis=2)
        outside_after = np.divide(outside_num, outside_den, out=np.full((2880, 16), np.nan), where=outside_den > 0)
        for g in seen_groups:
            rows = [x for x in detail_rows if x['scenario'] == sid and x['group'] == f'a{g+1:02}']
            groups.append(dict(group=f'a{g+1:02}', baseline_positive_ticks=int((base_c[all_ticks, g] == 1).sum()),
                perturbed_positive_ticks=int((c[all_ticks, g] == 1).sum()), new_positive_ticks=int(extra[all_ticks, g].sum()),
                R_delta=describe([x['R_perturbed']-x['R_baseline'] for x in rows if x['R_perturbed'] is not None]),
                B_delta=describe([x['B_perturbed']-x['B_baseline'] for x in rows if x['B_perturbed'] is not None]),
                IF_before=describe([x['IF_baseline'] for x in rows]), IF_after=describe([x['IF_perturbed'] for x in rows])))
            groups[-1].update(E_before=describe((s_before-outside_before)[all_ticks, g]),
                              E_after=describe((s_after-outside_after)[all_ticks, g]))
        summaries.append(dict(scenario=sid, affected_groups=[f'a{g+1:02}' for g in seen_groups],
            baseline_positive_ticks=int((base_c[interval] == 1).sum()),
            perturbed_positive_ticks=int((c[interval] == 1).sum()), new_positive_ticks=int(extra_in.sum()),
            removed_positive_ticks=int(((base_c == 1) & (c != 1)).sum()),
            new_detection_delay_seconds=(all_ticks[int(first_extra[0])]-all_ticks[0])*10 if len(first_extra) else None,
            extra_positive_ticks_outside_groups=int(extra[:, outside].sum()),
            unknown_group_ticks=int((c < 0).sum()), per_group=groups,
            metrics=grouping_metrics(altered, changed_local),
            affected_event_intervals=[dict(group=f'a{g+1:02}', start=stamp(data['times'][a]),
                end_exclusive=stamp(data['times'][0]+end*10000000), ticks=end-a,
                right_censored_missing=end < 2880 and c[end, g] < 0)
                for g in seen_groups for a, end in segments(c[:, g] == 1)
                if a <= max(all_ticks)+1 and end > min(all_ticks)-1]))
    return summaries, detail_rows, len(probe_requests)


def run(args):
    output = args.output
    output.mkdir(parents=True, exist_ok=False)
    start = time.perf_counter()
    config_bytes = PROTOCOL.read_bytes()
    protocol_commit = subprocess.check_output(['git', 'log', '-1', '--format=%H', '--', str(PROTOCOL)], text=True).strip()
    if subprocess.check_output(['git', 'show', f'{protocol_commit}:{PROTOCOL.as_posix()}']) != config_bytes:
        raise ValueError('protocol must be committed before experiments')
    config = json.loads(config_bytes)
    protected = json.loads(Path(config['protection_manifest']).read_text(encoding='utf-8'))
    if sha(config['protection_manifest']) != config['protection_sha256']:
        raise ValueError('changed protection manifest')
    for name, expected in protected.items():
        if sha(name) != expected:
            raise ValueError(f'protected input changed: {name}')
    data = load_data(config)
    data['physical'] = data['u2'].reshape(2880, 16, 18, 5).mean(axis=2)
    hosts = data['hosts']; positions = {h:i for i, h in enumerate(hosts)}
    original_groups = [dict(id=p['group'], hosts=p['hosts']) for p in data['profile']['groups']]
    validate_partition(original_groups, hosts)
    original, parity = [], {}
    for g, p in enumerate(data['profile']['groups']):
        u1 = data['u1'][:, g*18:(g+1)*18]
        trained = fit_group(u1)
        for key in ['host_median', 'host_mad', 'host_scale', 'median', 'mad', 'scale', 'normalized_mean',
                    'covariance', 'pseudoinverse', 'r_q99', 'b_q99']:
            np.testing.assert_allclose(trained[key], p[key], rtol=1e-8, atol=1e-8)
            parity[key] = max(parity.get(key, 0), float(np.max(np.abs(np.asarray(trained[key])-p[key]))))
        trained_decisions, frozen_decisions = score_group(trained, u1), score_group(p, u1)
        assert np.array_equal(trained_decisions['r'], frozen_decisions['r'])
        assert np.array_equal(trained_decisions['b'], frozen_decisions['b'])
        original.append(score_group(p, data['u2'][:, g*18:(g+1)*18]))
    baseline = grouping_metrics(original, data['local_flags'].reshape(2880, 16, 18))
    for key, expected in config['baseline_expected'].items():
        assert baseline[key] == expected, (key, baseline[key], expected)
    with Path('docs/group-runtime-v1/d2/timeline.csv').open(encoding='utf-8', newline='') as stream:
        for i, row in enumerate(csv.DictReader(stream)):
            t, g = divmod(i, 16)
            assert row['timestamp'] == stamp(data['times'][t]) and row['group'] == f'a{g+1:02}'
            assert int(row['R_positive']) == original[g]['r'][t] and int(row['B_positive']) == original[g]['b'][t]
            np.testing.assert_allclose([float(row['R']), float(row['B_D2'])],
                [original[g]['r_score'][t], original[g]['b_score'][t]], rtol=1e-8, atol=1e-8)
        assert i+1 == 46080
    dump(output/'baseline.json', baseline)
    events, controls, support = real_analysis(data, original)
    dump(output/'events.json', events); dump(output/'matched-controls.json', controls); dump(output/'IF-support.json', support)
    csv_rows(output/'events.csv', events)
    active = np.stack([candidates(x['r'], x['b']) == 1 for x in original], axis=1).sum(axis=1)
    a, end = [index_of(s, data['times'][0]) for s in config['analysis']['known_episode']]
    episodes = [episode(data, original, a, end, 'predefined_12:24_to_12:31')]
    episodes += [episode(data, original, x, y, 'all_5plus_groups') for x, y in segments(active >= config['analysis']['multigroup_min_groups'])]
    dump(output/'episodes.json', episodes)
    summaries = []
    perm_start = time.perf_counter()
    for assignment in config['permutations']['assignments']:
        validate_partition(assignment['groups'], hosts)
        results, profiles = [], []
        indices = []
        for g in assignment['groups']:
            ix = [positions[h] for h in g['hosts']]; indices.append(ix)
            p = fit_group(data['u1'][:, ix])
            profiles.append(dict(group=g['id'], hosts=g['hosts'], profile=p))
            results.append(score_group(p, data['u2'][:, ix]))
        local = np.stack([data['local_flags'][:, ix] for ix in indices], axis=1)
        metric = grouping_metrics(results, local)
        metric.update(seed=assignment['seed'], minimum_rank=min(x['profile']['effective_rank'] for x in profiles),
                      conditions=describe([x['profile']['condition'] for x in profiles]),
                      invalid_B_groups=[x['group'] for x in profiles if x['profile']['b_reason']])
        name = f"profiles-{assignment['seed']}.json"
        dump(output/name, profiles); metric['profile_sha256'] = sha(output/name)
        summaries.append(metric)
        print(f"seed={assignment['seed']} R={metric['R']} B={metric['B']} RB={metric['RB']} events={metric['events']}", flush=True)
    permutation_seconds = time.perf_counter()-perm_start
    dump(output/'permutations.json', summaries)
    synthetic, details, probe_count = interventions(data, original, config, args.probe, output)
    dump(output/'interventions.json', synthetic); csv_rows(output/'intervention-details.csv', details)
    for name, expected in protected.items():
        if sha(name) != expected:
            raise ValueError(f'protected file changed after run: {name}')
    summary = dict(version=config['version'], baseline=baseline, D1_parity_max_errors=parity,
        permutations=summaries, IF_support=support, interventions=synthetic,
        zero_MAD_existing_comparison=json.loads(Path('docs/group-runtime-review-v1/comparison.json').read_text(encoding='utf-8')),
        episodes=len(episodes), protected_files=len(protected), protected_all_unchanged=True,
        protocol_commit=protocol_commit, protocol_sha256=sha(PROTOCOL),
        code_commit=subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip(),
        code_dirty=bool(subprocess.check_output(['git', 'status', '--porcelain'], text=True).strip()),
        python=sys.version, numpy=np.__version__, platform=platform.platform(),
        command=sys.argv, go_probe_sha256=sha(args.probe), Go_probe_requests=probe_count,
        permutation_seconds=permutation_seconds, total_seconds=time.perf_counter()-start,
        interpretation='Additional exploratory D2 research, no fault labels, no model replacement')
    dump(output/'summary.json', summary)
    dump(output/'artifact-sha256.json', {p.name:sha(p) for p in sorted(output.iterdir()) if p.is_file()})
    print(json.dumps(clean(dict(status='PASS', baseline={k:baseline[k] for k in ['R','B','RB','events']},
                                permutations=len(summaries), probe_count=probe_count, seconds=summary['total_seconds'])), indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--probe', type=Path, required=True)
    run(parser.parse_args())


if __name__ == '__main__':
    main()
