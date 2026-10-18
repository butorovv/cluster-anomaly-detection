"""Frozen-protocol analysis on real D1/D2 Go exports; no fit or D3 access."""
import argparse,hashlib,json,time,sys,importlib.metadata
from pathlib import Path
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from tools.context.context_stats import (quantile,describe,calibrate,support,partition,topk,physical,
    physical_thresholds,select_events,joint_events,runs_summary,linear_runs,holm,empirical_tail,increments)
from tools.diagnostics.diagnostic_stats import pearson

DTYPE=np.dtype([('timestamp','<i8'),('host','<u4'),('available','<u4'),
                ('features','<f8',(18,)),('scores','<f8',(6,)),('distance','<f8')])
METHODS=['A0 historical','A0 D1-Q99','B1','B2']
FOUR=['a02n09','a02n10','a02n11','a02n12']

def dump(path,x):
    Path(path).write_text(json.dumps(x,indent=2,ensure_ascii=False,allow_nan=False),encoding='utf-8')

def load_window(path,start):
    data=np.memmap(path,mode='r',dtype=DTYPE)
    if len(data)!=829440: raise ValueError('unexpected state count')
    host=data['host'].reshape(2880,288)
    ts=data['timestamp'].reshape(2880,288)
    assert np.array_equal(host,np.broadcast_to(np.arange(288),host.shape))
    expected=np.datetime64(start,'us').astype('int64')+np.arange(2880)*10_000_000
    assert np.array_equal(ts,np.broadcast_to(expected[:,None],ts.shape))
    assert (data['available']==(1<<18)-1).all() and np.isfinite(data['scores']).all()
    assert np.isfinite(data['features']).all()
    return data,data['features'].reshape(2880,288,18),data['scores'].reshape(2880,288,6),expected

def reaction(events,binary,scores,groups):
    result=[]
    # No IID hypothesis test: shared hosts/windows are dependent.
    for event in events:
        t,h=event['t'],event['host'];a,b=t-3,t+19
        mask=binary[a:b,h];pre=float(scores[t-12:t-5,h].mean())
        first=np.flatnonzero(mask)
        durations=[(end-start)*10 for start,end in linear_runs(binary[:,h]) if start<b and end>a]
        local=binary[a:b,groups==groups[h]].sum(axis=1)
        k=binary[a:b].reshape(b-a,16,18).sum(axis=2)
        result.append(dict(detected=bool(mask.any()),latency_seconds=int((first[0]-3)*10) if len(first) else None,
            delta_max_score=float(scores[a:b,h].max()-pre),pre_score=pre,
            max_group_hosts=int(local.max()),max_cluster_hosts=int(k.sum(axis=1).max()),
            max_active_groups=int((k>0).sum(axis=1).max()),max_signal_run_seconds=max(durations,default=0),
            persists_at_180s=bool(binary[t+18,h])))
    return result

def aggregate_reactions(events,rows):
    out={}
    for category in ['all','drop','rise','thermal']:
        selected=[r for e,r in zip(events,rows) if category=='all' or e['direction']==category or (category=='thermal' and e['thermal'])]
        out[category]=dict(events=len(selected),detected=sum(r['detected'] for r in selected),
            detection_fraction=sum(r['detected'] for r in selected)/len(selected) if selected else None,
            latency=describe([r['latency_seconds'] for r in selected if r['latency_seconds'] is not None]),
            score_change=describe([r['delta_max_score'] for r in selected]),
            max_group_hosts=describe([r['max_group_hosts'] for r in selected]),
            max_active_groups=describe([r['max_active_groups'] for r in selected]),
            duration=describe([r['max_signal_run_seconds'] for r in selected]),
            persists=sum(r['persists_at_180s'] for r in selected))
    return out

def method_summary(b1,b2,score,old,four,transition,quiet,control):
    total=int(b2.sum());tp=int((b2&control).sum())
    runs=[r for h in range(b2.shape[1]) for r in linear_runs(b2[:,h])]
    lengths=np.array([end-start for start,end in runs])*10
    return dict(d1_signals=int(b1.sum()),d1_rate=float(b1.mean()),d2_signals=total,d2_rate=float(b2.mean()),
        delta_rate=float(b2.mean()-b1.mean()),host_over50=int((b2.mean(axis=0)>.5).sum()),
        host_over90=int((b2.mean(axis=0)>.9).sum()),host_over99=int((b2.mean(axis=0)>.99).sum()),
        four_signals=int(b2[:,four].sum()),four_share=float(b2[:,four].sum()/total) if total else None,
        historical_retained=int((b2&old).sum()),historical_lost=int((old&~b2).sum()),new_signals=int((b2&~old).sum()),
        transition_signals=int((b2&transition).sum()),transition_share=float((b2&transition).sum()/total) if total else None,
        quiet_signals=int((b2&quiet).sum()),quiet_share=float((b2&quiet).sum()/total) if total else None,
        other_signals=int((b2&~quiet&~transition).sum()),score_distribution=describe(score),
        runs=len(runs),run_seconds=describe(lengths),
        precision_ref=tp/total if total else None,recall_ref=tp/int(control.sum()),
        f1_ref=2*tp/(total+int(control.sum())),tp_ref=tp)

def topology_controls(binary,repeats=1999,seed=4202):
    if repeats<1999: raise ValueError('protocol requires at least1999 permutations')
    observed=[];primary=[];xb=[]
    for x in binary:
        y=x.astype(np.int16);k=y.reshape(len(y),16,18).sum(axis=2)
        s=k/18;e=s-(y.sum(axis=1)[:,None]-k)/270
        pairs=(k*(k-1)//2).sum(axis=0)
        observed.append(np.stack([s.max(axis=0),pairs,e.max(axis=0)],axis=1))
        primary.append([pairs.sum(),pairs[11:].sum(),(e*e).sum()])
        xb.append(y)
    draws=np.empty((repeats,len(binary),16,3));pdraws=np.empty((repeats,len(binary),3))
    rng=np.random.default_rng(seed)
    for r in range(repeats):
        part=partition(rng)
        for m,y in enumerate(xb):
            k=y[:,part].sum(axis=2,dtype=np.int32)
            s=k/18;e=s-(y.sum(axis=1)[:,None]-k)/270
            pairs=(k*(k-1)//2).sum(axis=0)
            draws[r,m]=np.stack([s.max(axis=0),pairs,e.max(axis=0)],axis=1)
            pdraws[r,m]=[pairs.sum(),pairs[11:].sum(),(e*e).sum()]
        if (r+1)%250==0: print(f'Topology permutations {r+1}/{repeats}',flush=True)
    primary=np.asarray(primary);observed=np.asarray(observed)
    tails=[empirical_tail(v,pdraws[:,m,j]) for m,row in enumerate(primary) for j,v in enumerate(row)]
    adj=holm([t['p_greater_equal'] for t in tails])
    for t,p in zip(tails,adj):t['p_holm9']=float(p)
    secondary=[empirical_tail(observed[m,g,j],draws[:,m,g,j]) for m in range(3) for g in range(16) for j in range(3)]
    adj2=holm([t['p_greater_equal'] for t in secondary])
    for t,p in zip(secondary,adj2):t['p_holm144']=float(p)
    return dict(repeats=repeats,seed=seed,primary=tails,secondary=secondary),draws,pdraws

def savefig(fig,folder,name):
    fig.tight_layout();fig.savefig(folder/f'{name}.png',dpi=150,bbox_inches='tight');plt.close(fig)

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--export',type=Path,default=Path('results/context-v1'))
    parser.add_argument('--figures',type=Path,default=Path('docs/figures/context'))
    args=parser.parse_args();started=time.perf_counter();root=args.export
    meta=json.loads((root/'metadata.json').read_text(encoding='utf-8'))
    assert meta['record_bytes']==DTYPE.itemsize==216
    assert meta['score_order']==['a0-42','b2-42','a0-43','b2-43','a0-44','b2-44']
    for path,expected in meta['input_sha256_before'].items():
        with Path(path).open('rb') as f:assert hashlib.file_digest(f,'sha256').hexdigest()==expected,path
    d1,x1,s1,ts1=load_window(root/'D1.bin','2022-01-18T00:00')
    d2,x2,s2,ts2=load_window(root/'D2.bin','2022-01-18T08:00')
    hosts=meta['source']['hosts'];groups=np.array([h[:3] for h in hosts]);four=[hosts.index(h) for h in FOUR]
    baseline=json.loads(Path('results/context-baseline.json').read_text())
    # Entire original D2 export must reproduce, not just a sampled score.
    from baseline import DTYPE as OLD_DTYPE
    olddata=np.memmap('results/d2-diagnostics-v1/states.bin',mode='r',dtype=OLD_DTYPE)
    assert np.array_equal(olddata['score'],d2['scores'][:,0])
    assert np.array_equal(olddata['features'],d2['features'])
    stat=json.loads(Path('results/statistical-20220118-8h-v1.json').read_text())['statistical_profile']
    control=(d2['distance']>stat['mahalanobis_squared_threshold_q99']).reshape(2880,288)
    tic=time.perf_counter()
    q0,qh=calibrate(s1[:,:,0],ts1);q2,_=calibrate(s1[:,:,1],ts1)
    calibration_seconds=time.perf_counter()-tic
    thresholds={'A0 historical':.6850838848387528,'A0 D1-Q99':q0,'B1':dict(zip(hosts,qh.tolist())),'B2':q2}
    tic=time.perf_counter()
    b1=[s1[:,:,0]>.6850838848387528,s1[:,:,0]>q0,s1[:,:,0]>qh,s1[:,:,1]>q2]
    b2=[s2[:,:,0]>.6850838848387528,s2[:,:,0]>q0,s2[:,:,0]>qh,s2[:,:,1]>q2]
    application_seconds=time.perf_counter()-tic
    continuous=[s2[:,:,0],s2[:,:,0],s2[:,:,0],s2[:,:,1]]
    p1,p2=physical(x1),physical(x2)
    tic=time.perf_counter();pt=physical_thresholds(p1,ts1);physical_fit_seconds=time.perf_counter()-tic
    events,transition,quiet=select_events(p2,pt);joints=joint_events(events,groups)
    dp,dt=increments(p2)
    rows=[reaction(events,b,sc,groups) for b,sc in zip(b2,continuous)]
    print(f'Physical events={len(events)} joint={len(joints)}; computing fixed comparisons',flush=True)
    report=dict(metadata=meta,baseline=baseline,thresholds=thresholds,physical_thresholds=pt,
                versions={m:importlib.metadata.version(m) for m in ['numpy','matplotlib','pyarrow','pytest']},
                calibration_seconds=calibration_seconds,application_seconds=application_seconds,
                physical_fit_seconds=physical_fit_seconds,physical_event_count=len(events),joint_event_count=len(joints),
                transition_state_count=int(transition.sum()),quiet_state_count=int(quiet.sum()),methods={},hosts=[],groups=[],
                seed_results={},topk={},events=events,joint_events=joints)
    for m,(name,b,sc) in enumerate(zip(METHODS,b2,continuous)):
        summary=method_summary(b1[m],b,sc,b2[0],four,transition,quiet,control)
        summary['reactions']=aggregate_reactions(events,rows[m])
        summary['signal_changes']={}
        for category,selected in [('retained',b&b2[0]),('lost',b2[0]&~b),('new',b&~b2[0])]:
            summary['signal_changes'][category]=dict(states=int(selected.sum()),
                A0_score=describe(s2[:,:,0][selected]),B2_score=describe(s2[:,:,1][selected]),
                GPU_power=describe(p2[:,:,0][selected]),GPU_temperature=describe(p2[:,:,3][selected]),
                abs_GPU_power_delta60=describe(np.abs(dp[:,:,0][selected])),
                transition_states=int((selected&transition).sum()),quiet_states=int((selected&quiet).sum()))
        joint_rows=[]
        for e in joints:
            a=max(0,e['start']-3);z=min(2880,e['end']+19)
            k=b[a:z][:,e['hosts']].sum(axis=1)
            joint_rows.append(dict(max_hosts=int(k.max()),detected=bool((k>=2).any())))
        summary['joint_detected']=sum(r['detected'] for r in joint_rows)
        summary['joint_max_hosts']=describe([r['max_hosts'] for r in joint_rows])
        report['methods'][name]=summary
    for h,host in enumerate(hosts):
        report['hosts'].append(dict(host=host,group=host[:3],
            physical_d1_medians=np.median(x1[:,h],axis=0).tolist(),
            physical_d2_medians=np.median(x2[:,h],axis=0).tolist(),
            global_d1_max_abs_median_z=float(np.max(np.abs((np.median(x1[:,h],axis=0)-stat['median'])/stat['effective_scale']))),
            methods={name:dict(d1=int(b1[m][:,h].sum()),d2=int(b2[m][:,h].sum()),
                score=describe(continuous[m][:,h]),runs=runs_summary(b2[m][:,h]),
                retained=int((b2[m][:,h]&b2[0][:,h]).sum()),lost=int((b2[0][:,h]&~b2[m][:,h]).sum())) for m,name in enumerate(METHODS)}))
    for g in np.unique(groups):
        item=dict(group=str(g),methods={})
        for m,name in enumerate(METHODS):
            k,n,s,e=support(b2[m],np.ones(b2[m].shape,bool),groups)
            k1,n1,s_1,e1=support(b1[m],np.ones(b1[m].shape,bool),groups)
            gi=list(np.unique(groups)).index(g);sq=float(quantile(s_1[:,gi]));eq=float(quantile(e1[:,gi]))
            pair=int((k[:,gi]*(k[:,gi]-1)//2).sum())
            item['methods'][name]=dict(signals=int(b2[m][:,groups==g].sum()),
                d1_signals=int(b1[m][:,groups==g].sum()),S=describe(s[:,gi]),E=describe(e[:,gi]),
                S_d1q99=sq,E_d1q99=eq,S_excess=runs_summary(s[:,gi]>sq),E_excess=runs_summary(e[:,gi]>eq),
                joint=runs_summary(k[:,gi]>=2),pair_bins=pair)
        report['groups'].append(item)
    # Pair contributions include pairs touching at least one of the four hosts.
    for m,name in enumerate(METHODS):
        y=b2[m];k=y.reshape(2880,16,18).sum(axis=2);allpairs=(y.sum(axis=1)*(y.sum(axis=1)-1)//2).sum()
        pairs=(k*(k-1)//2).sum(axis=0);reduced=y.copy();reduced[:,four]=False
        rk=reduced.reshape(2880,16,18).sum(axis=2);rp=(rk*(rk-1)//2).sum(axis=0)
        s=report['methods'][name];s.update(pair_bins=int(pairs.sum()),a02_pair_bins=int(pairs[1]),
            a12_a16_pair_bins=int(pairs[11:].sum()),four_pair_contribution=int(pairs.sum()-rp.sum()),
            within_pairs_without_four=int(rp.sum()),cross_group_pair_bins=int(allpairs-pairs.sum()),
            cluster_activity=describe(y.sum(axis=1)),conditional_cluster_activity=[dict(K=int(v),
                timestamps=int((y.sum(axis=1)==v).sum()),within_pairs_mean=float((k*(k-1)//2).sum(axis=1)[y.sum(axis=1)==v].mean())) for v in np.unique(y.sum(axis=1))])
    for seed,offset in [(42,0),(43,2),(44,4)]:
        a,ht=calibrate(s1[:,:,offset],ts1);b,_=calibrate(s1[:,:,offset+1],ts1)
        predictions=[s2[:,:,offset]>a,s2[:,:,offset]>ht,s2[:,:,offset+1]>b]
        training=[s1[:,:,offset]>a,s1[:,:,offset]>ht,s1[:,:,offset+1]>b]
        report['seed_results'][str(seed)]={}
        for i,(name,sc,mask) in enumerate(zip(['A0 D1-Q99','B1','B2'],[s2[:,:,offset],s2[:,:,offset],s2[:,:,offset+1]],predictions)):
            summary=method_summary(training[i],mask,sc,b2[0],four,transition,quiet,control)
            summary['reactions']=aggregate_reactions(events,reaction(events,mask,sc,groups))
            k=mask.reshape(2880,16,18).sum(axis=2)
            summary['pair_bins']=int((k*(k-1)//2).sum())
            cluster=mask.sum(axis=1)
            summary['random_group_pair_expectation']=float((cluster*(cluster-1)//2).sum()*17/287)
            summary['pair_topology_ratio']=summary['pair_bins']/summary['random_group_pair_expectation'] if summary['random_group_pair_expectation'] else None
            reference=b2[i+1];union=int((mask|reference).sum())
            summary['jaccard_seed42']=int((mask&reference).sum())/union if union else None
            summary['score_pearson_seed42']=pearson(sc.ravel(),continuous[i+1].ravel())
            summary['host_rate_pearson_seed42']=pearson(mask.mean(axis=0),reference.mean(axis=0))
            report['seed_results'][str(seed)][name]=summary
    for frac in [.005,.01,.02]:
        report['topk'][str(frac)]={}
        for name,rank,sc in zip(METHODS[1:],[s2[:,:,0],s2[:,:,0]-qh,s2[:,:,1]],continuous[1:]):
            mask=topk(rank,frac)
            report['topk'][str(frac)][name]=dict(signals=int(mask.sum()),four_share=float(mask[:,four].sum()/mask.sum()),
                reactions=aggregate_reactions(events,reaction(events,mask,sc,groups)))
    topology,draws,pdraws=topology_controls(b2[1:]);report['topology']=topology
    np.savez_compressed(root/'permutation-controls.npz',secondary=draws,primary=pdraws)
    # Additional diagnostic excludes these hosts only from counts, never fitting.
    reduced=[x.copy() for x in b2[1:]]
    for x in reduced:x[:,four]=False
    # Pair-only Gram oracle: cheap extra control with identical group draws.
    grams=[x.astype(float).T@x.astype(float) for x in reduced]
    rng=np.random.default_rng(4202);obs=[];ctrl=np.zeros((1999,3))
    for x in reduced:
        k=x.reshape(2880,16,18).sum(axis=2);obs.append(int((k*(k-1)//2).sum()))
    for r in range(1999):
        part=partition(rng)
        for m,gram in enumerate(grams):
            ctrl[r,m]=(sum(gram[np.ix_(g,g)].sum() for g in part)-np.trace(gram))/2
    report['topology_without_four']=[empirical_tail(v,ctrl[:,m]) for m,v in enumerate(obs)]
    adjusted=holm([r['p_greater_equal'] for r in report['topology_without_four']])
    for r,p in zip(report['topology_without_four'],adjusted):r['p_holm3']=float(p)
    # Illustrative known case uses original endpoint inclusively.
    a=int((np.datetime64('2022-01-18T12:24:40','us').astype('int64')-ts2[0])//10_000_000);z=a+32
    known=dict(start='2022-01-18T12:24:40Z',end_inclusive='2022-01-18T12:29:50Z',groups=[])
    for gi,g in enumerate(np.unique(groups)):
        hs=groups==g;before=p2[a-12:a-5,hs].mean(axis=(0,1));after=p2[z-6:z,hs].mean(axis=(0,1))
        item=dict(group=str(g),physical_before=before.tolist(),physical_after=after.tolist(),physical_delta=(after-before).tolist(),methods={})
        for m,name in enumerate(METHODS):
            k,n,s,e=support(b2[m],np.ones(b2[m].shape,bool),groups)
            item['methods'][name]=dict(signals=int(b2[m][a:z,hs].sum()),max_hosts=int(k[a:z,gi].max()),
                max_S=float(s[a:z,gi].max()),max_E=float(e[a:z,gi].max()),
                mean_score=float(continuous[m][a:z,hs].mean()),before_score=float(continuous[m][a-12:a-5,hs].mean()))
        known['groups'].append(item)
    known['methods']={name:dict(signals=int(mask[a:z].sum()),max_hosts=int(mask[a:z].sum(axis=1).max()),
        max_active_groups=int((mask[a:z].reshape(32,16,18).sum(axis=2)>0).sum(axis=1).max())) for name,mask in zip(METHODS,b2)}
    report['known_interval']=known
    report['events_with_reactions']=[dict(e,hostname=hosts[e['host']],timestamp=str(np.datetime64(int(ts2[e['t']]),'us')),
        methods={name:rows[m][i] for m,name in enumerate(METHODS)}) for i,e in enumerate(events)]
    args.figures.mkdir(parents=True,exist_ok=True)
    fig,axes=plt.subplots(2,2,figsize=(12,8))
    for m,name in enumerate(METHODS):
        axes[0,0].hist(continuous[m].ravel(),bins=100,histtype='step',label=name)
        axes[0,1].plot(b2[m].mean(axis=0)*100,label=name)
        axes[1,0].plot(np.arange(2880)/360+8,b2[m].sum(axis=1),label=name)
        axes[1,1].plot(np.arange(16)+1,[g['methods'][name]['signals'] for g in report['groups']],marker='.',label=name)
    for ax in axes.ravel():ax.legend(fontsize=7);ax.grid(alpha=.2)
    axes[0,0].set(xlabel='IF score D2',ylabel='States',yscale='log');axes[0,1].set(xlabel='Host (manifest order)',ylabel='Signals %')
    axes[1,0].set(xlabel='UTC hour',ylabel='Cluster active hosts');axes[1,1].set(xlabel='Group a01-a16',ylabel='Signals')
    savefig(fig,args.figures,'overview')
    fig,axes=plt.subplots(3,2,figsize=(12,10));tt=np.arange(a-18,z+18)/360+8
    for gi in range(11,16):
        hs=groups==f'a{gi+1:02}';sl=slice(a-18,z+18)
        axes[0,0].plot(tt,p2[sl,hs,0].mean(axis=1),label=f'a{gi+1:02}')
        axes[0,1].plot(tt,p2[sl,hs,3].mean(axis=1),label=f'a{gi+1:02}')
    for m,name in enumerate(METHODS):
        k,n,s,e=support(b2[m],np.ones(b2[m].shape,bool),groups)
        axes[1,0].plot(tt,continuous[m][sl,groups>='a12'].mean(axis=1),label=name)
        axes[1,1].plot(tt,b2[m][sl,groups>='a12'].sum(axis=1),label=name)
        axes[2,0].plot(tt,s[sl,11:].max(axis=1),label=name)
        axes[2,1].plot(tt,e[sl,11:].max(axis=1),label=name)
    for ax in axes.ravel():ax.axvspan(12+24/60+40/3600,12+29/60+50/3600,color='grey',alpha=.15);ax.legend(fontsize=7);ax.grid(alpha=.2);ax.set_xlabel('UTC hour')
    for ax,label in zip(axes.ravel(),['GPU power W (group mean)','GPU temp C (group mean)','IF mean score a12-a16','Active hosts a12-a16','Max S a12-a16','Max E a12-a16']):ax.set_ylabel(label)
    savefig(fig,args.figures,'known-interval')
    fig,axes=plt.subplots(1,3,figsize=(12,4))
    for m,name in enumerate(METHODS[1:]):
        axes[m].hist(pdraws[:,m,0],bins=40,label='Random groups');axes[m].axvline(topology['primary'][m*3]['actual'],color='red',label='Original groups')
        axes[m].set(title=name,xlabel='Within-group pair-bins',ylabel='Permutations');axes[m].legend(fontsize=8)
    savefig(fig,args.figures,'topology-control')
    fig,axes=plt.subplots(1,2,figsize=(11,4))
    cats=['drop','rise','thermal'];pos=np.arange(3)
    for m,name in enumerate(METHODS):
        axes[0].bar(pos+(m-1.5)*.18,[report['methods'][name]['reactions'][c]['detection_fraction'] or 0 for c in cats],width=.18,label=name)
    axes[0].set_xticks(pos,cats);axes[0].set_ylabel('Fraction with signal in fixed window');axes[0].legend(fontsize=7)
    for name in METHODS[1:]:axes[1].plot([42,43,44],[report['seed_results'][str(s)][name]['d2_rate']*100 for s in [42,43,44]],marker='o',label=name)
    axes[1].set(xlabel='Seed',ylabel='D2 signals %');axes[1].legend(fontsize=8)
    savefig(fig,args.figures,'transitions-seeds')
    report['analysis_elapsed_seconds']=time.perf_counter()-started
    dump(root/'summary.json',report)
    dump(root/'thresholds.json',thresholds)
    print(json.dumps({name:{k:v for k,v in r.items() if k in ['d1_rate','d2_signals','d2_rate','four_share','f1_ref']} for name,r in report['methods'].items()},indent=2),flush=True)

if __name__=='__main__':main()
