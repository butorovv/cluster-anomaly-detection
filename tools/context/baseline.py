"""Reproduce stage 4.1 from immutable export and previously fixed control."""
import hashlib,json
from pathlib import Path
import numpy as np
from context_stats import coincidence_metrics,holm,empirical_tail

DTYPE=np.dtype([('timestamp','<i8'),('host','<u4'),('available','<u4'),
                ('features','<f8',(18,)),('score','<f8'),('distance','<f8')])

def main():
    root=Path('results/d2-diagnostics-v1')
    meta=json.loads((root/'metadata.json').read_text())
    hashes={}
    for path,expected in meta['input_sha256'].items():
        with Path(path).open('rb') as f: hashes[path]=hashlib.file_digest(f,'sha256').hexdigest()
        assert hashes[path]==expected,path
    with (root/'states.bin').open('rb') as f:
        assert hashlib.file_digest(f,'sha256').hexdigest()==meta['binary_sha256']
    data=np.memmap(root/'states.bin',dtype=DTYPE,mode='r')
    x=(data['score']>0.6850838848387528).reshape(2880,288)
    y=(data['distance']>77.70489690680702).reshape(x.shape)
    count=int(x.sum());tp=int((x&y).sum());f1=2*tp/(count+y.sum())
    top=np.argsort(-x.sum(axis=0),kind='stable')[:4]
    observed=coincidence_metrics(x.reshape(2880,16,18))
    saved=np.load(root/'shift_controls.npz')
    assert np.array_equal(saved['observed'],observed)
    controls=saved['metrics']
    assert int(saved['seed'])==42 and str(saved['binary_sha256'])==meta['binary_sha256']
    assert len(controls)==1999
    tails=[[empirical_tail(observed[g,j],controls[:,g,j])['p_greater_equal'] for j in range(4)] for g in range(16)]
    adjusted=holm(np.asarray(tails).ravel()).reshape(16,4)
    assert count==12847 and abs(f1-.2294187530250363)<1e-15
    assert int(x[:,top].sum())==11219
    assert (adjusted[11:16,0]<.05).all()
    out=dict(count=count,four_hosts=[meta['source']['hosts'][i] for i in top],
             four_signals=int(x[:,top].sum()),four_share=float(x[:,top].sum()/count),
             f1_ref=float(f1),a12_a16_pair_holm=adjusted[11:16,0].tolist(),
             control_repeats=len(controls),input_sha256=hashes,
             control_note='Recomputed observed statistics and inference using preserved stage4.1 shift draws; not a new draw run')
    Path('results/context-baseline.json').write_text(json.dumps(out,indent=2),encoding='utf-8')
    print(json.dumps(out,indent=2))
if __name__=='__main__':main()
