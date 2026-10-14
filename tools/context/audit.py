"""Independent numerical oracle, immutable-input audit, and conservation checks."""
import hashlib,json,math
from pathlib import Path
import numpy as np
from analyze import DTYPE,load_window
from context_stats import quantile

def sha(path):
    with Path(path).open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()

def correction(n):
    return 0. if n<2 else 2*math.fsum(1/k for k in range(1,n))-2*(n-1)/n

def tree(node,z):
    depth=0
    while node['feature']>=0:
        node=node['left'] if z[node['feature']]<node['split'] else node['right'];depth+=1
    return depth+correction(node['size'])

def main():
    root=Path('results/context-v1');meta=json.loads((root/'metadata.json').read_text())
    report=json.loads((root/'summary.json').read_text());hosts=meta['source']['hosts']
    med=np.asarray([meta['context_profile']['host_medians'][h] for h in hosts])
    files=['results/isolation-20220118-v1.json','results/context-v1/b2-42.json',
           'results/context-v1/a0-43.json','results/context-v1/b2-43.json',
           'results/context-v1/a0-44.json','results/context-v1/b2-44.json']
    forests=[json.loads(Path(p).read_text())['isolation_forest'] for p in files]
    for m,f in enumerate(forests):
        assert f['training_window']=={'start':'2022-01-18T00:00:00Z','end_exclusive':'2022-01-18T08:00:00Z'}
        assert f['observations']==829440
        assert f['config']==dict(trees=100,sample_size=256,max_depth=8,seed=[42,42,43,43,44,44][m])
    errors={};indices=np.random.default_rng(123).choice(829440,1024,replace=False)
    for window,start in [('D1','2022-01-18T00:00'),('D2','2022-01-18T08:00')]:
        data,x,s,ts=load_window(root/f'{window}.bin',start)
        assert sha(root/f'{window}.bin')==meta['binary_sha256'][f'{window}.bin']
        if window=='D1':
            # Compute coordinate medians by independent column-wise sorting.
            actual=np.sort(np.asarray(x),axis=0)
            actual=(actual[1439]+actual[1440])/2
            median_error=float(np.max(np.abs(actual-med)))
            assert median_error<1e-12
            q0=float(np.sort(s[:,:,0].ravel())[math.ceil(.99*829440)-1])
            q2=float(np.sort(s[:,:,1].ravel())[math.ceil(.99*829440)-1])
            qh=np.sort(s[:,:,0],axis=0)[math.ceil(.99*2880)-1]
            assert q0==report['thresholds']['A0 D1-Q99'] and q2==report['thresholds']['B2']
            assert np.array_equal(qh,[report['thresholds']['B1'][h] for h in hosts])
        for m,forest in enumerate(forests):
            err=0.
            for i in indices:
                row=data[i];raw=row['features'];h=int(row['host'])
                # Direct formula, bypassing the Go adapter and its global centering.
                z=(raw-(med[h] if m%2 else forest['median']))/forest['effective_scale']
                score=2**(-math.fsum(tree(t,z) for t in forest['trees'])/len(forest['trees'])/correction(forest['effective_sample_size']))
                err=max(err,abs(score-float(row['scores'][m])))
            assert err<1e-14,(window,m,err)
            errors[f'{window}:{m}']=err
    for name,r in report['methods'].items():
        assert sum(h['methods'][name]['d2'] for h in report['hosts'])==r['d2_signals']
        assert sum(g['methods'][name]['signals'] for g in report['groups'])==r['d2_signals']
        assert r['historical_retained']+r['historical_lost']==12847
        assert r['transition_signals']+r['quiet_signals']+r['other_signals']==r['d2_signals']
    expected=json.loads(Path('results/context-baseline.json').read_text())['input_sha256']
    hashes={p:sha(p) for p in expected}
    assert hashes==expected==meta['input_sha256_before']==meta['input_sha256_after']
    extra={p.as_posix():sha(p) for p in [Path('data/raw/20220118.parquet'),
        Path('../НИР7_Буторов_РПЗ_07_10_2026_компонентная_модель.docx'),
        Path('../НИР7_Буторов_РПЗ_итоговая_07_10_2026_уточненная.docx')]}
    # Baseline report already recorded the raw and component RPZ hashes.
    assert extra['data/raw/20220118.parquet']=='7b6bcb905616865312fdd620d0f3aac9c82b1fcb23dfc1f547d068233cd18934'
    assert extra['../НИР7_Буторов_РПЗ_07_10_2026_компонентная_модель.docx']=='8f982d8852e8d79ec3b7a40d8a519eaf6da0a73b98f6ee7bbf16bb2e511be510'
    out=dict(sampled_states_per_model_per_window=1024,score_absolute_errors=errors,
             median_max_absolute_error=median_error,quantiles_independent_sort=True,
             counters_conserved=True,input_hashes_unchanged=hashes,additional_input_hashes=extra,
             experimental_model_hashes={p:sha(p) for p in files[1:]})
    (root/'audit.json').write_text(json.dumps(out,indent=2,ensure_ascii=False),encoding='utf-8')
    print(json.dumps({k:v for k,v in out.items() if k not in ['input_hashes_unchanged','experimental_model_hashes','additional_input_hashes']},indent=2))
if __name__=='__main__':main()
