"""Read-only independent D2 regression: math, B1 and causal temporal segmentation."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import numpy as np

ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
from tools.groupdiagnostics.d1 import host_channels,group_vectors
from tools.groupdiagnostics.parity import DTYPE


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--run',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    args=p.parse_args();meta=json.loads(Path('results/context-v1/metadata.json').read_text(encoding='utf-8'))
    binary=Path('results/context-v1/D2.bin')
    with binary.open('rb') as f:assert hashlib.file_digest(f,'sha256').hexdigest()==meta['binary_sha256']['D2.bin']
    data=np.memmap(binary,mode='r',dtype=DTYPE);assert len(data)==829440
    local_score=np.empty((2880,288));local_flag=np.empty((2880,288),bool)
    u=host_channels(data['features'].reshape(2880,288,18)).reshape(2880,16,18,5)
    profile=json.loads(Path('configs/group-profile.summit-v1.json').read_text(encoding='utf-8'))
    expected_r=np.empty((2880,16));expected_b=np.empty((2880,16));rr=np.empty_like(expected_r);bb=np.empty_like(rr)
    vectors=np.stack([group_vectors(u[:,g]) for g in range(16)],axis=1)
    for g,pr in enumerate(profile['groups']):
        z=(u[:,g]-pr['host_median'])/pr['host_scale']
        expected_r[:,g]=np.maximum(np.partition(np.maximum(z,0),-2,axis=1)[:,-2,:],np.partition(np.maximum(-z,0),-2,axis=1)[:,-2,:]).max(axis=1)
        w=(vectors[:,g]-pr['median'])/pr['scale']-pr['normalized_mean']
        expected_b[:,g]=np.einsum('ti,ij,tj->t',w,pr['pseudoinverse'],w)
    rflags=np.empty_like(rr,dtype=bool);bflags=np.empty_like(rr,dtype=bool);index=0
    with (args.run/'raw.ndjson').open(encoding='utf-8',newline='\n') as f:
        for line in f:
            row=json.loads(line);t,g=divmod(index,16)
            np.testing.assert_allclose(row['vector'],vectors[t,g],rtol=1e-8,atol=1e-8)
            rr[t,g],bb[t,g]=row['r']['score'],row['b']['score']
            rflags[t,g]=row['r']['state']=='positive';bflags[t,g]=row['b']['state']=='positive'
            for h,result in enumerate(row['local']):
                assert result['is_available'] and result['hostname']==meta['source']['hosts'][g*18+h]
                local_score[t,g*18+h]=result['anomaly_score'];local_flag[t,g*18+h]=result['is_anomaly']
            index+=1
    assert index==46080
    np.testing.assert_allclose(rr,expected_r,rtol=1e-8,atol=1e-8);np.testing.assert_allclose(bb,expected_b,rtol=1e-8,atol=1e-8)
    rth=np.array([g['r_q99'] for g in profile['groups']]);bth=np.array([g['b_q99'] for g in profile['groups']])
    assert np.array_equal(rflags,expected_r>rth) and np.array_equal(bflags,expected_b>bth)
    assert np.array_equal(local_score,data['scores'].reshape(2880,288,6)[:,:,0])
    b1=json.loads(Path('configs/local-b1.summit-20220118.json').read_text())
    thresholds=np.array([b1['thresholds'][h] for h in meta['source']['hosts']])
    assert np.array_equal(local_flag,local_score>thresholds) and int(local_flag.sum())==14341
    candidates={}
    for delta in [0,10,30,60]:
        r=np.zeros_like(rflags);b=np.zeros_like(bflags)
        for t in range(2880):
            r[t]=rflags[max(0,t-delta//10):t+1].any(axis=0)
            b[t]=bflags[max(0,t-delta//10):t+1].any(axis=0)
        candidates[delta]=r&b
    i=0
    with (args.run/'temporal.ndjson').open(encoding='utf-8',newline='\n') as f:
        for line in f:
            row=json.loads(line);t=i//64;g=(i//4)%16
            assert (row['candidate']=='positive')==candidates[row['delta_seconds']][t,g]
            i+=1
    assert i==184320
    events=[json.loads(line) for line in (args.run/'events.ndjson').read_text().splitlines()]
    for delta,c in candidates.items():
        for g in range(16):
            edges=np.diff(np.r_[False,c[:,g],False].astype(int));starts=np.flatnonzero(edges==1);ends=np.flatnonzero(edges==-1)
            actual=sorted([e for e in events if e['delta_seconds']==delta and e['group']==f'a{g+1:02}'],key=lambda x:x['detected_event_time'])
            assert len(actual)==len(starts)
            for event,a,b in zip(actual,starts,ends,strict=True):
                assert event['positive_ticks']==b-a and event['duration_grid_seconds']==(b-a)*10
                assert event['if_supported_ticks']==int(local_flag[a:b,g*18:(g+1)*18].any(axis=1).sum())
    result=dict(status='PASS',D2_group_ticks=46080,local_B1_states=829440,local_B1_scores='all exact versus preserved export',
                local_B1_anomalies=14341,R_B_binary='exact versus NumPy replay',
                max_abs_R_error=float(np.abs(rr-expected_r).max()),max_abs_B_error=float(np.abs(bb-expected_b).max()),
                temporal_candidates='all 184320 exact versus independent causal trailing-window OR',
                event_segmentation='all contiguous runs exactly match; duration and IF support verified')
    with args.output.open('x',encoding='utf-8',newline='\n') as f:json.dump(result,f,indent=2)
    print(json.dumps(result,indent=2))


if __name__=='__main__':main()
