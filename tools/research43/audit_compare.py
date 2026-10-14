"""Independent numerical oracle for stage II, with descriptive channel decomposition."""
import argparse
import hashlib
import json
import math
from pathlib import Path
import numpy as np

DTYPE=np.dtype([('timestamp','<i8'),('host','<u4'),('available','<u4'),
                ('features','<f8',(18,)),('scores','<f8',(6,)),('distance','<f8')])
NAMES=['A0 historical','A0 D1-Q99','B1 / H1 context','B2','Power','H2+','H2-','H2 any']
WINDOWS=[(0,3),(0,6),(0,12),(-3,18)]


def sha(path):
    with Path(path).open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()


def median_sort(x):
    x=np.sort(x,axis=0);n=len(x)
    return (x[(n-1)//2]+x[n//2])/2


def nearest_rank(x,q):
    x=np.sort(x,axis=0)
    return x[math.ceil(q*len(x))-1]


def physical_raw(x):
    return np.stack([sum(x[:,:,j] for j in range(4,10)),x[:,:,2]+x[:,:,3],x[:,:,0]+x[:,:,1]],axis=2)


def describe(x):
    x=np.asarray(x,float);x=x[np.isfinite(x)]
    if not len(x):return dict(n=0)
    return dict(n=int(len(x)),q50=float(np.quantile(x,.5)),q95=float(np.quantile(x,.95)),min=float(x.min()),max=float(x.max()))


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output',type=Path,default=Path('results/research43-stage2-v1'))
    p.add_argument('--export',type=Path,default=Path('results/context-v1'))
    args=p.parse_args();s=json.loads((args.output/'summary.json').read_text())
    p1=json.loads((args.output/'H1-profile.json').read_text());p2=json.loads((args.output/'H2-profile.json').read_text())
    for path,expected in s['hashes_before_after'].items():assert sha(path)==expected,path
    d1=np.memmap(args.export/'D1.bin',mode='r',dtype=DTYPE);d2=np.memmap(args.export/'D2.bin',mode='r',dtype=DTYPE)
    x1=d1['features'].reshape(2880,288,18);x2=d2['features'].reshape(2880,288,18)
    score1=d1['scores'].reshape(2880,288,6);score2=d2['scores'].reshape(2880,288,6)
    channels=np.load(args.output/'channels.npz');saved_masks=np.load(args.output/'masks.npz');masks=saved_masks['masks'];valid=saved_masks['valids']
    threshold=nearest_rank(score1[:,:,0],.99);absolute_threshold=nearest_rank(score1[:,:,0].ravel(),.99)
    np.testing.assert_array_equal(threshold,p1['host_threshold']);assert absolute_threshold==p1['absolute_threshold']
    assert channels['absolute'].tobytes()==score2[:,:,0].copy().tobytes()
    np.testing.assert_array_equal(channels['context'],score2[:,:,0]>threshold)
    np.testing.assert_array_equal(channels['absolute_flag'],score2[:,:,0]>absolute_threshold)
    np.testing.assert_array_equal(channels['margin'],score2[:,:,0]-threshold)
    raw1,raw2=physical_raw(x1),physical_raw(x2)
    delta1=raw1[6:]-raw1[:-6];delta2=raw2[6:]-raw2[:-6]
    assert np.array_equal(np.diff(d1['timestamp'].reshape(2880,288)[:,0]),np.full(2879,10000000))
    med=median_sort(delta1);mad=median_sort(np.abs(delta1-med))
    eps=np.maximum(1.,nearest_rank(np.abs(delta1).reshape(-1,3),.5));scale=np.maximum(1.4826*mad,eps)
    for key,value in [('median',med),('MAD',mad),('epsilon',eps),('scale',scale)]:np.testing.assert_array_equal(value,p2[key])
    u1=(delta1-med)/scale;plus1=np.maximum(u1,0).max(axis=2);minus1=np.maximum(-u1,0).max(axis=2)
    qp=nearest_rank(plus1.ravel(),.995);qn=nearest_rank(minus1.ravel(),.995)
    assert qp==p2['positive_threshold'] and qn==p2['negative_threshold']
    u2=(delta2-med)/scale;pos=np.maximum(u2,0).max(axis=2);neg=np.maximum(-u2,0).max(axis=2)
    np.testing.assert_array_equal(channels['u'][6:],u2)
    np.testing.assert_array_equal(channels['positive'][6:],pos);np.testing.assert_array_equal(channels['negative'][6:],neg)
    assert np.isnan(channels['u'][:6]).all() and not valid[4:,:6].any()
    np.testing.assert_array_equal(masks[5,6:],pos>qp);np.testing.assert_array_equal(masks[6,6:],neg>qn)
    power_threshold=nearest_rank(np.abs(delta1).reshape(-1,3),.995)
    np.testing.assert_array_equal(masks[4,6:],(np.abs(delta2)>power_threshold).any(axis=2))
    np.testing.assert_array_equal(masks[7],masks[5]|masks[6])
    events=json.loads((args.output/'event-index.json').read_text());metrics=np.load(args.output/'event-metrics.npz')
    event,control=metrics['event'],metrics['control'];checks=0
    assert len(events)==6978 and sum(e['control_t'] is None for e in events)==928
    for m in range(8):
        for w,(left,right) in enumerate(WINDOWS):
            for i,e in enumerate(events):
                h=e['host_index']
                for t,r in [(e['t'],event[m,w,i])]+([(e['control_t'],control[m,w,i])] if e['control_t'] is not None else []):
                    assert valid[m,t-6:t+right+1,h].all()
                    x=masks[m,:,h];quiet=all(not x[k] for k in range(t-6,t))
                    starts=[k for k in range(t,t+right+1) if x[k] and not x[k-1]]
                    assert bool(starts and quiet)==r['fresh']
                    assert (not quiet)==bool(r['pre60']) and bool(x[t-1])==r['active_before']
                    assert any(x[k] for k in range(t+left,t+right+1))==r['any']
                    checks+=1
    cats={'all':np.ones(len(events),bool)}
    for c in ['GPU','CPU','PSU']:
        for dr in ['drop','rise']:cats[c+' '+dr]=np.array([e['component']==c and e['direction']==dr for e in events])
    matched=np.array([e['control_t'] is not None for e in events]);quality=np.array([e['relative_mismatch'] if e['relative_mismatch'] is not None else np.nan for e in events])
    shared=np.all(~event[[2,3,4,7],2]['pre60']&~control[[2,3,4,7],2]['pre60'],axis=0)&matched
    for cat,chosen in cats.items():
        for m,name in enumerate(NAMES):
            ev,cv=event[m,2],control[m,2];r=s['comparisons'][cat][name]['120s']
            for tag,subset in [('primary',chosen&matched),('risk',chosen&matched&~ev['pre60']&~cv['pre60']),('shared_risk',chosen&shared)]:
                actual=r[tag];assert actual['n']==int(subset.sum())
                assert actual['event']==int(ev['fresh'][subset].sum()) and actual['control']==int(cv['fresh'][subset].sum())
            for qtag,qset in [('<=1%',quality<=.01),('1-5%',(quality>.01)&(quality<=.05)),('>5%',quality>.05)]:
                subset=chosen&matched&qset
                assert r['quality'][qtag]['primary']['n']==int(subset.sum())
    draws=np.load(args.output/'topology-controls.npz');rng=np.random.default_rng(4202);partitions={}
    for r in range(1999):
        part=rng.permutation(288).reshape(16,18)
        if r in [0,1,2,17,1998]:partitions[r]=part
    starts=np.zeros_like(masks);starts[:,1:]=masks[:,1:]&~masks[:,:-1]&valid[:,1:]&valid[:,:-1]
    for r,part in partitions.items():
        for m in range(8):
            for j,x in enumerate([masks[m],starts[m]]):
                k=x[:,part].sum(axis=2)
                assert int((k*(k-1)//2).sum())==draws['draws'][r,m,j]
    pvalues=[]
    for m,name in enumerate(NAMES):
        for j,tag in enumerate(['signal_pairs','onset_pairs']):
            actual=int(draws['observed'][m,j]);ps=(1+int((draws['draws'][:,m,j]>=actual).sum()))/2000
            pvalues.append(ps);assert ps==s['methods'][name]['permutation'][tag]['p_greater_equal']
    order=np.argsort(pvalues);adjusted=np.empty(16);running=0.
    for rank,index in enumerate(order):running=max(running,pvalues[index]*(16-rank));adjusted[index]=min(1.,running)
    for m,name in enumerate(NAMES):
        assert adjusted[m*2]==s['methods'][name]['permutation']['signal_pairs']['p_holm16']
        assert adjusted[m*2+1]==s['methods'][name]['permutation']['onset_pairs']['p_holm16']
    # Descriptive audit of the observed direction/scaling, without changing any threshold.
    winners_plus=np.argmax(u2,axis=2);winners_minus=np.argmax(-u2,axis=2);winners=np.argmax(np.abs(u2),axis=2)
    any_h2=masks[7,6:];only=any_h2&~masks[4,6:];power_only=masks[4,6:]&~any_h2
    direction_decomposition={tag:{c:int((flag&(winner==j)).sum()) for j,c in enumerate(['GPU','CPU','PSU'])}
        for tag,flag,winner in [('H2+',masks[5,6:],winners_plus),('H2-',masks[6,6:],winners_minus),('H2-only',only,winners)]}
    coordinate_audit={c:dict(max_u_positive=float(np.maximum(u2[:,:,j],0).max()),
                            max_u_negative=float(np.maximum(-u2[:,:,j],0).max()),
                            positive_exceedances=int((u2[:,:,j]>qp).sum()),negative_exceedances=int((-u2[:,:,j]>qn).sum()),
                            floor_hosts=int((1.4826*mad[:,j]<=eps[j]).sum()),scale=describe(scale[:,j]))
                      for j,c in enumerate(['GPU','CPU','PSU'])}
    def localization(x):
        k=x.reshape(len(x),16,18).sum(axis=2);cluster=x.sum(axis=1);within=int((k*(k-1)//2).sum())
        expected=float((cluster*(cluster-1)//2).sum()*17/287)
        return dict(n=int(x.sum()),within_pairs=within,random_expected=expected,ratio=within/expected if expected else None)
    rawratio=np.max(np.abs(delta2)/power_threshold,axis=2)
    novel=dict(H2_only=localization(only),Power_only=localization(power_only),
               H2_only_raw_power_ratio=describe(rawratio[only]),Power_only_raw_power_ratio=describe(rawratio[power_only]),
               H2_only_B1_overlap=int((only&masks[2,6:]).sum()),H2_only_B2_overlap=int((only&masks[3,6:]).sum()),
               normalized_scale_to_power_q995=describe(power_threshold[None,:]/scale))
    # Adjacent changes describe real trajectories; they are not another H2 lag.
    adjacent=raw2[6:]-raw2[5:-1]
    positive=masks[5];negative=masks[6]
    positive_starts=np.zeros_like(positive);positive_starts[1:]=positive[1:]&~positive[:-1]&valid[5,1:]&valid[5,:-1]
    paired_echo=positive[6:]&negative[:-6]
    paired_echo_starts=positive_starts[6:]&negative[:-6]
    temporal_echo=dict(positive_states=int(positive.sum()),positive_with_negative_60s_before=int(paired_echo.sum()),
                       positive_onsets=int(positive_starts.sum()),positive_onsets_with_negative_60s_before=int(paired_echo_starts.sum()),
                       positive_PSU_delta60=describe(delta2[:,:,2][positive[6:]]),
                       positive_PSU_adjacent_change=describe(adjacent[:,:,2][positive[6:]]),
                       positive_adjacent_over_delta60=describe(np.abs(adjacent[:,:,2][positive[6:]])/np.maximum(np.abs(delta2[:,:,2][positive[6:]]),1)),
                       note='descriptive echo timing, not independently labelled jobs/failures or an extra detector')
    # Equal budget independently ranked with lexsort (rather than stable argsort helper).
    rank_scores=[score2[:,:,0],score2[:,:,0],channels['margin'],score2[:,:,1],np.r_[np.full((6,288),np.nan),rawratio],
                 channels['positive'],channels['negative'],np.maximum(channels['positive'],channels['negative'])]
    valid_indices=np.flatnonzero(valid[7].ravel());budget_checks=0
    for frac,methods in s['budget'].items():
        for name,entry in methods.items():
            m=NAMES.index(name);scores=rank_scores[m].ravel();order=np.lexsort((valid_indices,-scores[valid_indices]))
            count=math.floor(len(valid_indices)*float(frac));selected=valid_indices[order[:count]]
            assert count==entry['ranking']['count'] and scores[selected[-1]]==entry['ranking']['cutoff']
            b=np.zeros(scores.size,bool);b[selected]=True;b=b.reshape(2880,288)
            assert int(b.sum())==entry['summary']['signals'];budget_checks+=1
    audit=dict(independent_H1_absolute_exact=True,independent_H1_B1_exact=True,independent_H2_parameters_exact=True,
               independent_H2_all_defined_scores_exact=True,independent_power_threshold_and_mask_exact=True,
               temporal_checks=checks,paired_risk_sizes_and_counts_exact=True,quality_strata_counts_exact=True,
               direct_permutation_checks=len(partitions)*8*2,holm16_exact=True,equal_budget_lexsort_checks=budget_checks,
               matched=6050,unmatched=928,direction_decomposition=direction_decomposition,coordinate_audit=coordinate_audit,
               novel=novel,temporal_echo=temporal_echo,
               input_hashes_unchanged=True,inputs=['D1.bin','D2.bin'],latest_timestamp='2022-01-18T15:59:50Z')
    for path,expected in s['hashes_before_after'].items():assert sha(path)==expected,path
    (args.output/'audit.json').write_text(json.dumps(audit,indent=2),encoding='utf-8')
    print(json.dumps(audit,indent=2))


if __name__=='__main__':main()
