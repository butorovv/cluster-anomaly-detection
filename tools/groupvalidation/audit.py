"""Independent saved-control regression using sorted scores and direct covariance.

Does not call fit_group/score_group or update any model. Numerical differences
from Welford are diagnostics; they never become new inference thresholds.
"""
import argparse
import json
import math
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from tools.groupdiagnostics.parity import DTYPE
from tools.groupvalidation.common import PROTOCOL, dump, sha


def physical(binary):
    data = np.memmap(binary, mode='r', dtype=DTYPE)
    assert len(data) == 829440 and (data['available'] == 262143).all()
    x = data['features'].reshape(2880, 288, 18)
    return np.stack([x[:, :, 4:10].sum(-1), x[:, :, 2:4].sum(-1), x[:, :, :2].sum(-1),
                     x[:, :, 12:18].mean(-1), x[:, :, 10:12].mean(-1)], axis=-1)


def r_sorted(u, med, scale):
    z = (u-med)/scale
    positive = np.sort(np.maximum(z, 0), axis=1)[:, -2]
    negative = np.sort(np.maximum(-z, 0), axis=1)[:, -2]
    return np.maximum(positive, negative).max(axis=1)


def vector(u):
    return np.concatenate([u.mean(axis=1), np.sqrt(np.var(u, axis=1, ddof=0))], axis=1)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    config = json.loads(PROTOCOL.read_text(encoding='utf-8'))
    for path in ['results/context-v1/D1.bin', 'results/context-v1/D2.bin']:
        assert sha(path) == config['input_sha256'][path]
    u1, u2 = [physical(f'results/context-v1/{window}.bin') for window in ['D1', 'D2']]
    frozen = json.loads(Path('configs/group-profile.summit-v1.json').read_text(encoding='utf-8'))
    positions = {h:i for i,h in enumerate(frozen['binding']['hosts'])}
    summaries = json.loads((args.input/'permutations.json').read_text(encoding='utf-8'))
    errors = {}; checked = 0
    def check(name, actual, expected):
        np.testing.assert_allclose(actual, expected, rtol=1e-8, atol=1e-8, err_msg=name)
        errors[name] = max(errors.get(name, 0), float(np.max(np.abs(np.asarray(actual)-expected))))
    for assignment, summary in zip(config['permutations']['assignments'], summaries, strict=True):
        assert summary['seed'] == assignment['seed']
        path = args.input/f"profiles-{assignment['seed']}.json"
        assert sha(path) == summary['profile_sha256']
        profiles = json.loads(path.read_text(encoding='utf-8'))
        for g, (membership, saved) in enumerate(zip(assignment['groups'], profiles, strict=True)):
            assert saved['group'] == membership['id'] and saved['hosts'] == membership['hosts']
            ix = [positions[h] for h in membership['hosts']]
            train, inference = u1[:, ix], u2[:, ix]
            p = saved['profile']
            med = np.median(train, axis=0); mad = np.median(np.abs(train-med), axis=0)
            scale = np.maximum(1.4826*mad, 1e-4)
            for name, x in [('host_median', med), ('host_mad', mad), ('host_scale', scale)]:
                check(name, x, np.array(p[name]))
            r1, r2 = r_sorted(train, med, scale), r_sorted(inference, med, scale)
            q = math.ceil(.99*len(train))-1
            check('r_q99', np.sort(r1)[q], p['r_q99'])
            v = vector(train)
            vm = np.median(v, axis=0); vs = np.maximum(1.4826*np.median(np.abs(v-vm), axis=0), 1e-4)
            check('median', vm, np.array(p['median'])); check('scale', vs, np.array(p['scale']))
            w = (v-vm)/vs; center = w.mean(axis=0)
            covariance = np.cov(w, rowvar=False, ddof=1)
            inverse = np.linalg.pinv(covariance, rcond=1e-12)
            check('center', center, np.array(p['normalized_mean']))
            check('covariance', covariance, np.array(p['covariance']))
            check('inverse', inverse, np.array(p['pseudoinverse']))
            singular = np.linalg.svd(covariance, compute_uv=False)
            rank = int((singular > singular[0]*1e-12).sum())
            assert rank == p['effective_rank'] == 10 and p['b_reason'] == ''
            d1 = np.einsum('ti,ij,tj->t', w-center, inverse, w-center)
            check('b_q99', np.sort(d1)[q], p['b_q99'])
            normalized = (vector(inference)-vm)/vs-center
            d2 = np.einsum('ti,ij,tj->t', normalized, inverse, normalized)
            r, b = r2 > p['r_q99'], d2 > p['b_q99']
            expected = summary['per_group'][g]
            joint = r & b
            events = int((np.diff(np.r_[False, joint, False].astype(int)) == 1).sum())
            assert (int(r.sum()), int(b.sum()), int(joint.sum()), events) == (
                expected['R'], expected['B'], expected['RB'], expected['events'])
            checked += 1
    dump(args.output, dict(status='PASS', control_profiles=checked, control_D2_group_ticks=checked*2880,
        reference='full sorting, direct NumPy covariance/mean and pinv; no inference recalibration',
        binary_counts_and_event_counts='all exact per group/seed', maximum_absolute_errors=errors,
        rtol=1e-8, atol=1e-8, protocol_sha256=sha(PROTOCOL)))
    print(json.dumps(dict(status='PASS', profiles=checked, maximum_absolute_errors=errors), indent=2))


if __name__ == '__main__':
    main()
