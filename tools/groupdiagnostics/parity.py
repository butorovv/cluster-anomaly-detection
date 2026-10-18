"""Numerical regression of the Go D1 runtime against the frozen checkpoint.

Does not fit an alternative model, read D2/D3, or alter any historical artifact.
"""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from tools.groupdiagnostics.d1 import host_channels, group_vectors

DTYPE = np.dtype([('timestamp','<i8'),('host','<u4'),('available','<u4'),
                  ('features','<f8',(18,)),('scores','<f8',(6,)),('distance','<f8')])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    reference = json.loads(Path('docs/group-detection-d1-final/diagnostics.json').read_text(encoding='utf-8'))
    profile = json.loads((args.run/'profile.json').read_text(encoding='utf-8'))
    summary = json.loads((args.run/'summary.json').read_text(encoding='utf-8'))
    assert summary['window']['start'].startswith('2022-01-18T00:00:00')
    maximum = {}

    def check(name, actual, expected):
        a, b = np.asarray(actual), np.asarray(expected)
        np.testing.assert_allclose(a, b, rtol=1e-8, atol=1e-8, err_msg=name)
        maximum[name] = max(maximum.get(name, 0), float(np.max(np.abs(a-b))))

    for p, r in zip(profile['groups'], reference['groups'], strict=True):
        assert p['group'] == r['group']
        assert p['observations'] == r['full_ticks'] == 2880
        for name in ['host_median','host_mad','host_scale']:
            check(name, p[name], r[name])
        for name in ['median','mad','scale','normalized_mean','covariance','pseudoinverse','singular_values']:
            check(name, p[name], r['B'][name])
        assert p['effective_rank'] == r['B']['effective_rank'] == 10
        check('r_threshold', p['r_q99'], r['R_q99'])
        check('b_threshold', p['b_q99'], r['B']['q99_mahalanobis_squared'])

    binary = Path('results/context-v1/D1.bin')
    with binary.open('rb') as stream:
        assert hashlib.file_digest(stream,'sha256').hexdigest() == reference['input_sha256_before'][binary.as_posix()]
    data = np.memmap(binary, mode='r', dtype=DTYPE)
    assert len(data) == 829440 and (data['available'] == 262143).all()
    u = host_channels(data['features'].reshape(2880,288,18)).reshape(2880,16,18,5)
    vectors, rs, bs = [], [], []
    for g, r in enumerate(reference['groups']):
        v = group_vectors(u[:,g])
        z = (u[:,g] - r['host_median']) / r['host_scale']
        score = np.maximum(np.partition(np.maximum(z,0),-2,axis=1)[:,-2,:],
                           np.partition(np.maximum(-z,0),-2,axis=1)[:,-2,:]).max(axis=1)
        w = (v-r['B']['median'])/r['B']['scale']-r['B']['normalized_mean']
        distance = np.einsum('ti,ij,tj->t',w,r['B']['pseudoinverse'],w)
        vectors.append(v);rs.append(score);bs.append(distance)
    vectors, rs, bs = np.stack(vectors,axis=1),np.stack(rs,axis=1),np.stack(bs,axis=1)
    count = 0
    with (args.run/'raw.ndjson').open(encoding='utf-8') as stream:
        for line in stream:
            row = json.loads(line); t,g = divmod(count,16)
            assert row['group'] == f'a{g+1:02}'
            check('vectors',row['vector'],vectors[t,g])
            check('r_score',row['r']['score'],rs[t,g])
            check('b_distance',row['b']['score'],bs[t,g])
            assert (row['r']['state']=='positive') == (rs[t,g]>reference['groups'][g]['R_q99'])
            assert (row['b']['state']=='positive') == (bs[t,g]>reference['groups'][g]['B']['q99_mahalanobis_squared'])
            assert row['y']['state']=='unknown'
            count += 1
    assert count == 46080
    result = dict(status='PASS',window='D1 only',group_ticks=count,host_states=829440,
                  rtol=1e-8,atol=1e-8,maximum_absolute_errors=maximum,
                  binary_R_B_decisions='exact for all 46080 group ticks',
                  reference_sha256=hashlib.sha256(Path('docs/group-detection-d1-final/diagnostics.json').read_bytes()).hexdigest(),
                  group_profile_sha256=summary['group_profile_sha256'])
    with args.output.open('x',encoding='utf-8') as stream:
        json.dump(result,stream,indent=2,allow_nan=False);stream.write('\n')
    print(json.dumps(result,indent=2))


if __name__ == '__main__':
    main()
