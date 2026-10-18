"""Checkpoint 1 only: diagnose the proposed 10D group model on D1, never D2/D3.

No detector, inference profile, parameter search, or replacement of historical data.
Run from the repository root; output must be a new directory.
"""
import argparse
import collections
import datetime as dt
import hashlib
import importlib.metadata
import json
import platform
import subprocess
import sys
from pathlib import Path

import numpy as np
import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from tools.context.context_stats import quantile

EPSILON = 1e-4
RCOND = 1e-12
START = dt.datetime(2022, 1, 18, tzinfo=dt.timezone.utc)
END = START + dt.timedelta(hours=8)
CHANNELS = ['gpu_total_W', 'cpu_total_W', 'psu_ac_total_W',
            'gpu_mean_C', 'cpu_mean_C']


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def host_channels(x):
    x = np.asarray(x, dtype=float)
    if x.shape[-1] != 18:
        raise ValueError('F18 required')
    return np.stack([x[..., 4:10].sum(axis=-1), x[..., 2:4].sum(axis=-1),
                     x[..., :2].sum(axis=-1), x[..., 12:18].mean(axis=-1),
                     x[..., 10:12].mean(axis=-1)], axis=-1)


def group_vectors(u):
    u = np.asarray(u, dtype=float)
    if u.ndim != 3 or u.shape[1:] != (18, 5):
        raise ValueError('fixed 18 hosts and 5 channels required')
    return np.concatenate([u.mean(axis=1), u.std(axis=1, ddof=0)], axis=1)


def robust(x):
    if not np.isfinite(x).all() or len(x) == 0:
        raise ValueError('complete finite D1 required')
    median = np.median(x, axis=0)
    mad = np.median(np.abs(x - median), axis=0)
    return median, mad, np.maximum(1.4826 * mad, EPSILON)


def covariance_welford(x):
    mean = np.zeros(x.shape[1])
    moment = np.zeros((x.shape[1], x.shape[1]))
    for n, row in enumerate(x, 1):
        delta = row - mean
        mean += delta / n
        moment += np.outer(delta, row - mean)
    c = moment / (len(x) - 1)
    # Mirror the lower triangle, as in existing Go FitStatistical.
    return mean, np.tril(c) + np.tril(c, -1).T


def covariance_diagnostics(v):
    if len(v) < 11 or v.shape[1] != 10 or not np.isfinite(v).all():
        return {'status': 'unknown', 'reason': 'insufficient_complete_D1'}
    median, mad, scale = robust(v)
    w = (v - median) / scale
    mean, c = covariance_welford(w)
    raw_mean, raw_c = covariance_welford(v)
    eigen = np.linalg.eigvalsh(c)
    left, singular, right = np.linalg.svd(c)
    keep = singular > RCOND * singular[0]
    rank = int(keep.sum())
    inverse = (right.T[:, keep] / singular[keep]) @ left.T[keep]
    identity_error = np.linalg.norm(c @ inverse - np.eye(10), ord='fro')
    norm = np.linalg.norm(c, ord='fro')
    reconstruction = np.linalg.norm(c @ inverse @ c - c, ord='fro') / norm if norm else 0.
    centered = w - mean
    distance = np.einsum('ti,ij,tj->t', centered, inverse, centered)
    # Alternative direct centered computation checks Welford + quadratic form.
    direct_c = np.cov(w, rowvar=False, ddof=1)
    direct_norm = np.linalg.norm(direct_c)
    relative_cov_error = np.linalg.norm(direct_c - c) / direct_norm if direct_norm else 0.
    status = 'algebraically_usable' if rank == 10 and eigen[0] >= 0 and np.isfinite(distance).all() else 'unknown'
    q = float(quantile(distance)) if status == 'algebraically_usable' else None
    return dict(status=status, observations=len(v), median=median.tolist(), mad=mad.tolist(),
                scale=scale.tolist(), floored=int((1.4826 * mad < EPSILON).sum()),
                raw_mean=raw_mean.tolist(), raw_covariance=raw_c.tolist(),
                normalized_mean=mean.tolist(), covariance=c.tolist(),
                eigenvalues_ascending=eigen.tolist(), singular_values=singular.tolist(),
                effective_rank=rank, condition=float(singular[0] / singular[-1]) if singular[-1] > 0 else None,
                pseudoinverse=inverse.tolist(), reconstruction_relative_frobenius=float(reconstruction),
                identity_frobenius_error=float(identity_error),
                covariance_crosscheck_relative_error=float(relative_cov_error),
                q99_mahalanobis_squared=q,
                d1_positive_ticks=int((distance > q).sum()) if q is not None else None,
                distance_range=[float(distance.min()), float(distance.max())])


def describe(x):
    x = np.asarray(x).ravel()
    x = x[np.isfinite(x)]
    return dict(n=len(x), min=float(x.min()), q01=float(quantile(x, .01)),
                median=float(np.median(x)), q99=float(quantile(x)), max=float(x.max()))


def raw_d1_info(path, hosts):
    file = pq.ParquetFile(path)
    columns = ['timestamp', 'hostname', 'node_state', 'label', 'xid']
    start, end = START.replace(tzinfo=None), END.replace(tzinfo=None)
    counts = {c: collections.Counter() for c in columns[2:]}
    selected = 0
    for i in range(file.metadata.num_row_groups):
        stats = file.metadata.row_group(i).column(0).statistics
        if stats and stats.has_min_max and (stats.max < start or stats.min >= end):
            continue
        for batch in file.iter_batches(batch_size=65536, row_groups=[i], columns=columns):
            mask = pc.and_(pc.and_(pc.greater_equal(batch.column(0), pa.scalar(start)),
                                  pc.less(batch.column(0), pa.scalar(end))),
                           pc.is_in(batch.column(1), value_set=pa.array(hosts)))
            values = batch.filter(mask).to_pydict()
            selected += len(values['hostname'])
            for c in counts:
                counts[c].update(str(v) for v in values[c])
    return {'schema': str(file.schema_arrow), 'columns': file.schema_arrow.names,
            'selected_D1_records': selected, 'D1_counts': counts,
            'absent_configuration_fields': [s for s in ['threshold', 'alarm', 'serial', 'fru', 'power_cap', 'power_limit']
                                            if not any(s in c.lower() for c in file.schema_arrow.names)]}


def run(output):
    manifest_path = Path('data/prepared/summit-D1-pilot/manifest.json')
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    meta = json.loads(Path('results/context-v1/metadata.json').read_text(encoding='utf-8'))
    paths = dict(meta['input_sha256_before'])
    paths['data/raw/20220118.parquet'] = manifest['source_file_hashes'][0]
    paths['configs/local-b1.summit-20220118.json'] = sha('configs/local-b1.summit-20220118.json')
    paths['results/context-v1/D1.bin'] = meta['binary_sha256']['D1.bin']
    before = {p: sha(p) for p in paths}
    if before != paths:
        raise ValueError('immutable input SHA differs from historical manifest')
    hosts, names = manifest['selected_hosts'], manifest['feature_order']
    if hosts != [f'a{g:02}n{h:02}' for g in range(1, 17) for h in range(1, 19)]:
        raise ValueError('fixed inventory changed')
    table = pq.read_table('data/prepared/summit-D1-pilot/D1.parquet',
                          filters=[('timestamp', '>=', START), ('timestamp', '<', END)])
    table = table.sort_by([('timestamp', 'ascending'), ('hostname', 'ascending')])
    tick = np.arange(2880, dtype=np.int64) * 10_000_000 + int(START.timestamp()) * 1_000_000
    if not np.array_equal(table['timestamp'].cast(pa.int64()).to_numpy(), np.repeat(tick, 288)):
        raise ValueError('D1 grid incomplete, duplicated, or out of window')
    if table['hostname'].to_pylist() != hosts * 2880:
        raise ValueError('D1 inventory mismatch')
    x = np.column_stack([table[k].to_numpy() for k in names]).reshape(2880, 288, 18)
    # Independently bind the historical D1 export back to current prepared values.
    dtype = np.dtype([('timestamp', '<i8'), ('host', '<u4'), ('available', '<u4'),
                      ('features', '<f8', (18,)), ('scores', '<f8', (6,)), ('distance', '<f8')])
    exported = np.memmap('results/context-v1/D1.bin', mode='r', dtype=dtype)
    if len(exported) != 829440 or not np.array_equal(x.reshape(-1, 18), exported['features'], equal_nan=True):
        raise ValueError('prepared D1 does not match historical export')
    if not np.array_equal(exported['timestamp'], np.repeat(tick, 288)):
        raise ValueError('export time binding mismatch')
    available = (np.isfinite(x).all(axis=2)
                 & table['is_valid'].to_numpy().reshape(2880, 288)
                 & (table['availability_mask'].to_numpy().reshape(2880, 288) == 262143))
    u = host_channels(x).reshape(2880, 16, 18, 5)
    groups = []
    for g in range(16):
        complete = available[:, g*18:(g+1)*18].all(axis=1)
        ug = u[complete, g]
        base = dict(group=f'a{g+1:02}', full_ticks=int(complete.sum()), expected_ticks=2880,
                    coverage=float(complete.mean()))
        if len(ug) < 11:
            groups.append({**base, 'R_status': 'unknown', 'B': {'status': 'unknown'}})
            continue
        median, mad, scale = robust(ug)
        z = (ug - median) / scale
        # The second order statistic is across distinct hosts, for each sign/channel.
        r = np.maximum(np.partition(np.maximum(z, 0), -2, axis=1)[:, -2, :],
                       np.partition(np.maximum(-z, 0), -2, axis=1)[:, -2, :]).max(axis=1)
        v = group_vectors(ug)
        b = covariance_diagnostics(v)
        acf = []
        for j in range(10):
            a, c = v[:-1, j], v[1:, j]
            acf.append(float(np.corrcoef(a, c)[0, 1]) if np.std(a) > 0 and np.std(c) > 0 else None)
        floor_details = []
        for h, k in np.argwhere(1.4826 * mad < EPSILON):
            vals = ug[:, h, k]
            differences = np.diff(np.unique(vals))
            floor_details.append(dict(host=hosts[g*18+int(h)], channel=CHANNELS[k],
                                      median=float(median[h, k]), mad=float(mad[h, k]),
                                      min=float(vals.min()), max=float(vals.max()),
                                      unique_values=len(np.unique(vals)),
                                      fraction_at_median=float((vals == median[h, k]).mean()),
                                      minimum_observed_positive_spacing=float(differences.min()) if len(differences) else None,
                                      maximum_absolute_z=float(np.abs(z[:, h, k]).max())))
        base.update(R_status='algebraically_usable', host_median=median.tolist(), host_mad=mad.tolist(),
                    host_scale=scale.tolist(), zero_host_mad=int((mad == 0).sum()),
                    floored_host_scales=int((1.4826*mad < EPSILON).sum()),
                    minimum_host_scale=float(scale.min()), floor_details=floor_details,
                    R_q99=float(quantile(r)),
                    R_d1_positive_ticks=int((r > quantile(r)).sum()),
                    group_vector_lag1_correlation=acf, B=b)
        groups.append(base)
    info = raw_d1_info('data/raw/20220118.parquet', hosts)
    after = {p: sha(p) for p in paths}
    if before != after:
        raise ValueError('protected inputs changed during diagnostics')
    result = dict(version='group-checkpoint1-diagnostics-v1', status='checkpoint_not_approved_model',
                  base_commit=subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip(),
                  script_sha256=sha(__file__), source_spec_sha256=sha('docs/group-detection-mathematical-spec.md'),
                  command=sys.argv, platform=platform.platform(), python=sys.version,
                  packages={p: importlib.metadata.version(p) for p in ['numpy', 'pyarrow']},
                  window=[START.isoformat(), END.isoformat()], D2_D3_analyzed=False,
                  timezone_verified=False, epsilon=EPSILON, rcond=RCOND, ddof=1,
                  channel_order=CHANNELS, feature_order=names, hosts=hosts,
                  input_sha256_before=before, input_sha256_after=after,
                  host_states=829440, complete_host_states=int(available.sum()),
                  feature_distributions={k: describe(x[..., j]) for j, k in enumerate(names)},
                  channel_distributions={k: describe(u[..., j]) for j, k in enumerate(CHANNELS)},
                  gpu_300W_reference_only={'device_samples': int(x[..., 4:10].size),
                                           'above_300W': int((x[..., 4:10] > 300).sum()),
                                           'host_states_with_any': int((x[..., 4:10] > 300).any(axis=2).sum()),
                                           'interpretation': 'reference comparison only; not a Y signal or fault label'},
                  raw=info, groups=groups)
    output.mkdir(parents=True, exist_ok=False)
    with (output / 'diagnostics.json').open('x', encoding='utf-8') as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write('\n')
    print(json.dumps({'groups': [{k: v[k] for k in ['group', 'coverage', 'floored_host_scales']}
                                 | {'rank': v['B'].get('effective_rank'), 'condition': v['B'].get('condition')}
                                 for v in groups], 'output': str(output)}, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    run(parser.parse_args().output)
