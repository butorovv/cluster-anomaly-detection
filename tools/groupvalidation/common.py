"""Research-only arbitrary partitions; production hostname validation is untouched."""
import hashlib
import json
import math
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from tools.groupdiagnostics.d1 import host_channels, group_vectors, robust, covariance_welford
from tools.groupdiagnostics.parity import DTYPE

CHANNELS = ['gpu_total_W', 'cpu_total_W', 'psu_ac_total_W', 'gpu_mean_C', 'cpu_mean_C']
PROTOCOL = Path('configs/group-validation-protocol-v1.json')


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def clean(value):
    if isinstance(value, np.ndarray):
        return clean(value.tolist())
    if isinstance(value, np.generic):
        return clean(value.item())
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, dict):
        return {str(k): clean(v) for k, v in value.items()}
    if isinstance(value, (tuple, list)):
        return [clean(x) for x in value]
    return value


def dump(path, value):
    with Path(path).open('x', encoding='utf-8', newline='\n') as stream:
        json.dump(clean(value), stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write('\n')


def stamp(microseconds):
    return datetime.fromtimestamp(int(microseconds)/1e6, timezone.utc).isoformat().replace('+00:00', 'Z')


def index_of(iso, origin):
    offset = int(datetime.fromisoformat(iso).timestamp()*1e6)-int(origin)
    if offset % 10000000:
        raise ValueError('10s grid required')
    return offset//10000000


def quantile(x):
    if not len(x):
        raise ValueError('nonempty calibration required')
    return float(np.sort(x)[math.ceil(.99*len(x))-1])


def validate_partition(groups, hosts):
    members = [h for group in groups for h in group['hosts']]
    if len(groups) != 16 or any(len(g['hosts']) != 18 for g in groups):
        raise ValueError('16 groups of 18 required')
    if len(set(members)) != 288 or set(members) != set(hosts):
        raise ValueError('each original host must occur exactly once')
    if len({g['id'] for g in groups}) != 16:
        raise ValueError('unique group IDs required')


def r_components(u, median, scale, threshold):
    z = (u-median)/scale
    # Column order preserves the frozen channel/sign tie-break.
    second = np.stack([np.partition(np.maximum(sign*z[:, :, k], 0), -2, axis=1)[:, -2]
                       for k in range(5) for sign in [-1, 1]], axis=1)
    winner = second.argmax(axis=1)
    channel, direction = winner//2, np.where(winner % 2 == 0, -1, 1)
    score = second[np.arange(len(u)), winner]
    selected = z[np.arange(len(u))[:, None], np.arange(18)[None, :], channel[:, None]]
    witnesses = direction[:, None]*selected > threshold
    witnesses &= (score > threshold)[:, None]
    return score, channel, direction, witnesses


def fit_group(u1):
    if u1.ndim != 3 or u1.shape[1:] != (18, 5) or not np.isfinite(u1).all():
        raise ValueError('complete fixed-composition D1 required')
    hm, hd, hs = robust(u1)
    train_r, _, _, _ = r_components(u1, hm, hs, np.inf)
    vector = group_vectors(u1)
    vm, vd, vs = robust(vector)
    w = (vector-vm)/vs
    mean, covariance = covariance_welford(w)
    eigen = np.linalg.eigvalsh(covariance)
    left, singular, right = np.linalg.svd(covariance)
    keep = singular > 1e-12*singular[0]
    rank = int(keep.sum())
    inverse = (right.T[:, keep]/singular[keep]) @ left.T[keep]
    reason = 'rank_deficient' if rank < 10 else ('not_psd' if eigen[0] < 0 else '')
    p = dict(host_median=hm, host_mad=hd, host_scale=hs, r_q99=quantile(train_r),
             median=vm, mad=vd, scale=vs, normalized_mean=mean, covariance=covariance,
             pseudoinverse=inverse, singular_values=singular, eigenvalues=eigen,
             effective_rank=rank, b_reason=reason, observations=len(u1),
             condition=float(singular[0]/singular[-1]) if singular[-1] > 0 else None,
             b_q99=None)
    if not reason:
        centered = w-mean
        distances = np.einsum('ti,ij,tj->t', centered, inverse, centered)
        if not np.isfinite(distances).all() or (distances < 0).any():
            raise ValueError('invalid full-rank distance')
        p['b_q99'] = quantile(distances)
    return p


def score_group(p, u):
    n = len(u)
    complete = np.isfinite(u).all(axis=(1, 2))
    r, b = np.full(n, -1, dtype=np.int8), np.full(n, -1, dtype=np.int8)
    rs, bs = np.full(n, np.nan), np.full(n, np.nan)
    channel, direction = np.full(n, -1), np.zeros(n, dtype=int)
    witnesses = np.zeros((n, 18), dtype=bool)
    if complete.any():
        rs[complete], channel[complete], direction[complete], witnesses[complete] = r_components(
            u[complete], p['host_median'], p['host_scale'], p['r_q99'])
        r[complete] = rs[complete] > p['r_q99']
        if p['b_q99'] is not None:
            v = group_vectors(u[complete])
            w = (v-p['median'])/p['scale']-p['normalized_mean']
            distances = np.einsum('ti,ij,tj->t', w, p['pseudoinverse'], w)
            valid = np.isfinite(distances) & (distances >= 0)
            ix = np.flatnonzero(complete)[valid]
            bs[ix] = distances[valid]
            b[ix] = distances[valid] > p['b_q99']
    return dict(r=r, b=b, r_score=rs, b_score=bs, channel=channel, direction=direction,
                witnesses=witnesses, complete=complete)


def candidates(r, b):
    return np.where((r < 0) | (b < 0), -1, ((r == 1) & (b == 1)).astype(np.int8))


def segments(positive):
    if np.asarray(positive).dtype != bool:
        raise ValueError('explicit positive bool mask required, unknown is not true')
    edges = np.diff(np.r_[False, positive, False].astype(int))
    return list(zip(np.flatnonzero(edges == 1).tolist(), np.flatnonzero(edges == -1).tolist(), strict=True))


def describe(x):
    values = np.asarray(x, dtype=float).ravel()
    values = values[np.isfinite(values)]
    if not len(values):
        return dict(n=0, min=None, median=None, mean=None, max=None)
    return dict(n=len(values), min=float(values.min()), median=float(np.median(values)),
                mean=float(values.mean()), max=float(values.max()))


def grouping_metrics(results, local_flags):
    r = np.stack([x['r'] for x in results], axis=1)
    b = np.stack([x['b'] for x in results], axis=1)
    c = candidates(r, b)
    counts, durations, support_fractions, witness_fractions = [], [], [], []
    per_group, channels, directions = [], np.zeros(5, dtype=int), {'negative': 0, 'positive': 0}
    if_supported_ticks = candidate_ticks = 0
    for g, x in enumerate(results):
        intervals = segments(c[:, g] == 1)
        counts.append(len(intervals)); durations.extend((end-a)*10 for a, end in intervals)
        for a, end in intervals:
            support_fractions.append(float(local_flags[a:end, g].any(axis=1).mean()))
        mask = x['r'] == 1
        witness_fractions.extend(x['witnesses'][mask].sum(axis=1)/18)
        channels += np.bincount(x['channel'][mask], minlength=5)
        directions['negative'] += int((x['direction'][mask] == -1).sum())
        directions['positive'] += int((x['direction'][mask] == 1).sum())
        eventmask = c[:, g] == 1
        supported = int(local_flags[eventmask, g].any(axis=1).sum())
        if_supported_ticks += supported; candidate_ticks += int(eventmask.sum())
        per_group.append(dict(index=g, R=int(mask.sum()), B=int((x['b'] == 1).sum()),
            R_unknown=int((x['r'] < 0).sum()), B_unknown=int((x['b'] < 0).sum()),
            RB=int(eventmask.sum()), events=len(intervals), duration_seconds=int(eventmask.sum()*10),
            IF_supported_ticks=supported, R_witness_fraction=describe(x['witnesses'][mask].sum(axis=1)/18)))
    total = sum(counts)
    p = np.asarray(counts, dtype=float)/total if total else np.zeros(len(counts))
    active = (c == 1).sum(axis=1)
    return dict(R=int((r == 1).sum()), B=int((b == 1).sum()), RB=candidate_ticks,
        R_unknown=int((r < 0).sum()), B_unknown=int((b < 0).sum()), events=total,
        duration_seconds=candidate_ticks*10, event_duration=describe(durations),
        duration_bins={'10s':sum(x == 10 for x in durations), '20-30s':sum(10 < x <= 30 for x in durations),
                       '40-120s':sum(30 < x <= 120 for x in durations), '>120s':sum(x > 120 for x in durations)},
        group_event_HHI=float((p*p).sum()) if total else None,
        group_event_entropy=float(-(p[p > 0]*np.log(p[p > 0])).sum()/np.log(len(p))) if total else None,
        simultaneous_groups=describe(active[active > 0]), multi_5plus_ticks=int((active >= 5).sum()),
        IF_supported_tick_fraction=if_supported_ticks/candidate_ticks if candidate_ticks else None,
        IF_event_support_fraction=describe(support_fractions), R_witness_fraction=describe(witness_fractions),
        R_channels=dict(zip(CHANNELS, channels.tolist(), strict=True)), R_directions=directions,
        per_group=per_group)


def load_data(config):
    for name, expected in config['input_sha256'].items():
        if sha(name) != expected:
            raise ValueError(f'changed input: {name}')
    profile = json.loads(Path('configs/group-profile.summit-v1.json').read_text(encoding='utf-8'))
    hosts = profile['binding']['hosts']
    exports = {}
    for name in ['D1', 'D2']:
        d = np.memmap(f'results/context-v1/{name}.bin', mode='r', dtype=DTYPE)
        if len(d) != 829440 or not (d['available'] == 262143).all():
            raise ValueError('complete frozen export required')
        times = d['timestamp'].reshape(2880, 288)
        if not (times == times[:, :1]).all() or not (np.diff(times[:, 0]) == 10000000).all():
            raise ValueError('inconsistent event-time grid')
        if not (d['host'].reshape(2880, 288) == np.arange(288)).all():
            raise ValueError('host order mismatch')
        expected_start = index_of(config['windows'][name][0], times[0, 0])
        if expected_start != 0:
            raise ValueError('window mismatch')
        exports[name] = d
    f1, f2 = [exports[w]['features'].reshape(2880, 288, 18) for w in ['D1', 'D2']]
    b1 = json.loads(Path('configs/local-b1.summit-20220118.json').read_text(encoding='utf-8'))
    local_scores = exports['D2']['scores'].reshape(2880, 288, 6)[:, :, 0]
    local_flags = local_scores > np.array([b1['thresholds'][h] for h in hosts])
    return dict(profile=profile, hosts=hosts, f1=f1, f2=f2, u1=host_channels(f1),
                u2=host_channels(f2), local_flags=local_flags, local_scores=local_scores,
                times=exports['D2']['timestamp'].reshape(2880, 288)[:, 0])
