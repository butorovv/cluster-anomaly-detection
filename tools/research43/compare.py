"""Approved stage II: frozen H1/H2, real D1/D2, no production or D3."""
import argparse
import hashlib
import importlib.metadata
import json
import platform
import sys
import time
from pathlib import Path
import numpy as np

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'tools/context'))
from context_stats import calibrate,physical,quantile,linear_runs,empirical_tail,holm
from channels import fit_h1,h1,deltas,fit_h2,h2
from stats import temporal,cluster_ci
from comparison_stats import onsets,group_arrays,cooccurrence,partition_pairs,pair_stats,equal_budget

DTYPE=np.dtype([('timestamp','<i8'),('host','<u4'),('available','<u4'),
                ('features','<f8',(18,)),('scores','<f8',(6,)),('distance','<f8')])
NAMES=['A0 historical','A0 D1-Q99','B1 / H1 context','B2','Power','H2+','H2-','H2 any']
WINDOWS={'30s':(0,3),'60s':(0,6),'120s':(0,12),'historical':(-3,18)}
METRIC=np.dtype([(k,'?') for k in ['valid','any','pre60','pre120','active_before','onset','fresh','continuous_known','continuous_only']]+
                [(k,'<f8') for k in ['latency','duration','score_delta']])


def sha(path):
    with Path(path).open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()


def dump(path,value):
    Path(path).write_text(json.dumps(value,indent=2,ensure_ascii=False,allow_nan=False),encoding='utf-8')


def describe(values):
    x=np.asarray(values,float).ravel();x=x[np.isfinite(x)]
    if not len(x):return dict(n=0)
    return dict(n=int(len(x)),mean=float(x.mean()),min=float(x.min()),max=float(x.max()),
                **{f'q{int(q*100):02}':float(np.quantile(x,q,method='inverted_cdf')) for q in [.01,.25,.5,.75,.95,.99]})


def load(root,window,start):
    data=np.memmap(root/f'{window}.bin',dtype=DTYPE,mode='r')
    if len(data)!=829440:raise ValueError('complete Summit window required')
    times=np.datetime64(start,'us')+np.arange(2880)*np.timedelta64(10,'s')
    assert np.array_equal(data['timestamp'].reshape(2880,288),np.broadcast_to(times.astype('int64')[:,None],(2880,288)))
    assert np.array_equal(data['host'].reshape(2880,288),np.broadcast_to(np.arange(288),(2880,288)))
    assert (data['available']==262143).all() and np.isfinite(data['features']).all()
    return data,data['features'].reshape(2880,288,18),data['scores'].reshape(2880,288,6),times


def evaluate(mask,valid,score,centers,hosts):
    out=np.zeros((len(WINDOWS),len(centers)),dtype=METRIC)
    for name in ['latency','duration','score_delta']:out[name]=np.nan
    for i,(center,host) in enumerate(zip(centers,hosts)):
        if center<0:continue
        t,h=int(center),int(host)
        for w,(left,right) in enumerate(WINDOWS.values()):
            fully_valid=valid[t-6:t+right+1,h].all() and valid[t+left:t+right+1,h].all()
            if not fully_valid:continue
            r=temporal(mask[:,h],t,left,right)
            for target,source in [('any','any'),('pre60','pre60'),('pre120','pre120'),('active_before','active_before'),('onset','post_onset'),('fresh','fresh_onset')]:
                out[target][w,i]=r[source]
            out['valid'][w,i]=True
            out['latency'][w,i]=r['latency_seconds'] if r['latency_seconds'] is not None else np.nan
            out['duration'][w,i]=r['onset_duration_seconds'] if r['onset_duration_seconds'] is not None else np.nan
            prior=score[t-12:t-5,h];post=score[t:t+right+1,h]
            if np.isfinite(prior).all() and np.isfinite(post).all():
                change=float(post.max()-np.median(prior))
                out['score_delta'][w,i]=change;out['continuous_known'][w,i]=True
                out['continuous_only'][w,i]=not r['any'] and abs(change)>1e-12
    return out


def paired(event,control,indices,host_labels,times):
    selected=np.asarray(indices,bool)&event['valid']&control['valid']
    ev=event['fresh'][selected];cv=control['fresh'][selected]
    differences=ev.astype(int)-cv.astype(int)
    return dict(n=int(selected.sum()),event=int(ev.sum()),control=int(cv.sum()),
                event_rate=float(ev.mean()) if len(ev) else None,control_rate=float(cv.mean()) if len(cv) else None,
                host_ci=cluster_ci(differences,host_labels[selected]),
                hour_ci=cluster_ci(differences,times[selected]//360),
                halfhour_ci=cluster_ci(differences,times[selected]//180))


def signal_summary(mask,valid,four):
    lengths=np.array([(b-a)*10 for h in range(mask.shape[1]) for a,b in linear_runs(mask[:,h])])
    rates=np.divide(mask.sum(axis=0),valid.sum(axis=0),out=np.zeros(mask.shape[1]),where=valid.sum(axis=0)>0)
    k,n,s,e,localized=group_arrays(mask,valid)
    start=onsets(mask,valid);_,_,_,_,local_start=group_arrays(start,valid)
    total=int(mask.sum());active=(mask.sum(axis=1)>0)
    reduced=mask.copy();reduced[:,four]=False
    topology=pair_stats(mask);without=pair_stats(reduced)
    cluster=mask.sum(axis=1);active_groups=(k>0).sum(axis=1)
    group_runs=[(b-a)*10 for g in range(16) for a,b in linear_runs(localized[:,g])]
    return dict(signals=total,valid_states=int(valid.sum()),rate=total/int(valid.sum()),runs=int(len(lengths)),
                duration=describe(lengths),onsets=int(start.sum()),host_rates=describe(rates),
                hosts_over50=int((rates>.5).sum()),hosts_over90=int((rates>.9).sum()),
                top4_share=float(np.sort(mask.sum(axis=0))[-4:].sum()/total) if total else None,
                four_signals=int(mask[:,four].sum()),four_share=float(mask[:,four].sum()/total) if total else None,
                within_pairs=topology,without_four_pairs=without,
                four_pair_contribution=topology['within']-without['within'],
                onset_pairs=pair_stats(start),cluster_activity=describe(cluster),
                active_cluster_activity=describe(cluster[active]),active_groups=describe(active_groups[active]),
                all_groups_active_timestamps=int((active_groups==16).sum()),all_hosts_active_timestamps=int((cluster==288).sum()),
                S=describe(s),E=describe(e),localized_group_states=int(localized.sum()),
                localized_group_run_duration=describe(group_runs),new_localized_group_states=int(local_start.sum()),
                per_group_signals=k.sum(axis=0).tolist(),per_group_localized_states=localized.sum(axis=0).tolist(),
                per_host_signals=mask.sum(axis=0).tolist(),hour_signals=mask.reshape(8,360,288).sum(axis=(1,2)).tolist())


def timing(fn,repeats=5):
    fn();values=[]
    for _ in range(repeats):
        t=time.perf_counter();fn();values.append(time.perf_counter()-t)
    return dict(seconds=values,median=float(np.median(values)),minimum=float(min(values)),maximum=float(max(values)))


def peak_memory():
    if sys.platform!='win32':return None
    import ctypes
    from ctypes import wintypes
    class Counters(ctypes.Structure):
        _fields_=[('cb',wintypes.DWORD),('PageFaultCount',wintypes.DWORD)]+[(k,ctypes.c_size_t) for k in
                   ['PeakWorkingSetSize','WorkingSetSize','QuotaPeakPagedPoolUsage','QuotaPagedPoolUsage',
                    'QuotaPeakNonPagedPoolUsage','QuotaNonPagedPoolUsage','PagefileUsage','PeakPagefileUsage']]
    c=Counters();c.cb=ctypes.sizeof(c)
    kernel=ctypes.WinDLL('kernel32');kernel.GetCurrentProcess.restype=wintypes.HANDLE
    psapi=ctypes.WinDLL('psapi');psapi.GetProcessMemoryInfo.argtypes=[wintypes.HANDLE,ctypes.POINTER(Counters),wintypes.DWORD]
    if not psapi.GetProcessMemoryInfo(kernel.GetCurrentProcess(),ctypes.byref(c),c.cb):return None
    return int(c.PeakWorkingSetSize)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--export',type=Path,default=Path('results/context-v1'))
    p.add_argument('--stage1',type=Path,default=Path('results/research43-v4'))
    p.add_argument('--output',type=Path,default=Path('results/research43-stage2-v1'))
    args=p.parse_args();args.output.mkdir(parents=True,exist_ok=False);started=time.perf_counter()
    old=json.loads((args.stage1/'summary.json').read_text());old_events=json.loads((args.stage1/'events.json').read_text())
    meta=json.loads((args.export/'metadata.json').read_text());hosts=meta['source']['hosts'];host_array=np.asarray(hosts)
    four=[hosts.index(h) for h in ['a02n09','a02n10','a02n11','a02n12']]
    hashes=dict(old['baseline']['input_sha256'])
    for filename in ['events.json','summary.json','audit.json','baseline.json']:hashes[str(args.stage1/filename)]=sha(args.stage1/filename)
    for filename in ['02-hypotheses-protocol.md','02-evaluation-protocol.md']:hashes['docs/research-4.3/'+filename]=sha('docs/research-4.3/'+filename)
    for path,expected in hashes.items():assert sha(path)==expected,path
    d1,x1,s1,ts1=load(args.export,'D1','2022-01-18T00:00')
    d2,x2,s2,ts2=load(args.export,'D2','2022-01-18T08:00')
    io_seconds=time.perf_counter()-started
    t=time.perf_counter();power1=physical(x1)[:,:,:3];power2=physical(x2)[:,:,:3]
    dp1,v1=deltas(power1,ts1);dp2,v2=deltas(power2,ts2)
    preprocessing_seconds=time.perf_counter()-t
    t=time.perf_counter();hp1=fit_h1(s1[:,:,0],ts1,hosts);hp2=fit_h2(dp1,v1,ts1,hosts)
    fit_seconds=time.perf_counter()-t
    linkage=dict(training_window=dict(start='2022-01-18T00:00:00Z',end_exclusive='2022-01-18T08:00:00Z'),
                 input_D1_sha256=meta['binary_sha256']['D1.bin'],source_sha256=meta['source']['prepared_sha256'])
    hp1.update(linkage,channel='H1',global_forest_sha256=old['baseline']['model_sha256']['results/isolation-20220118-v1.json'])
    hp2.update(linkage,channel='H2',power_order=['GPU','CPU','PSU'],lag_seconds=60,cadence_seconds=10,seed=None,
               quantile=.995,quantile_method='inverted_cdf',comparison='strict >',D1_valid_states=int(v1.sum()))
    t=time.perf_counter();h1out=h1(s2[:,:,0],hp1);h2out=h2(dp2,v2,hp2);application_seconds=time.perf_counter()-t
    assert np.array_equal(h1out['absolute'],s2[:,:,0])
    np.testing.assert_array_equal(hp1['host_threshold'],old['baseline']['thresholds']['b1'])
    q0,qh=calibrate(s1[:,:,0],ts1);q2,_=calibrate(s1[:,:,1],ts1)
    power_threshold=np.asarray(quantile(np.abs(dp1[v1]),.995,axis=0))
    np.testing.assert_array_equal(power_threshold,old['baseline']['physical_thresholds']['power'])
    power_flag=v2&(np.abs(dp2)>power_threshold).any(axis=2)
    power_rank=np.max(np.abs(dp2)/power_threshold,axis=2)
    masks=[s2[:,:,0]>.6850838848387528,s2[:,:,0]>q0,h1out['context'],s2[:,:,1]>q2,
           power_flag,h2out['positive_flag'],h2out['negative_flag'],h2out['positive_flag']|h2out['negative_flag']]
    valids=[np.ones(v2.shape,bool)]*4+[v2]*4
    ranks=[s2[:,:,0],s2[:,:,0],h1out['margin'],s2[:,:,1],power_rank,h2out['positive'],h2out['negative'],
           np.maximum(h2out['positive'],h2out['negative'])]
    assert [int(m.sum()) for m in masks[:4]]==[12847,8153,14341,14123]
    dump(args.output/'H1-profile.json',hp1);dump(args.output/'H2-profile.json',hp2)
    t=time.perf_counter()
    np.savez_compressed(args.output/'channels.npz',absolute=h1out['absolute'],absolute_flag=h1out['absolute_flag'],context=h1out['context'],
                        margin=h1out['margin'],u=h2out['u'],positive=h2out['positive'],negative=h2out['negative'],valid=v2)
    np.savez_compressed(args.output/'masks.npz',masks=np.stack(masks),valids=np.stack(valids))
    writing_seconds=time.perf_counter()-t
    events=[dict(index=r['index'],host_index=r['host_index'],host=r['host'],group=r['group'],t=r['t'],
                 component=r['component'],direction=r['direction'],control_t=r['control_t'],
                 relative_mismatch=r['control_power_mismatch']/max(abs(r['power_before'][['GPU','CPU','PSU'].index(r['component'])]),1.) if r['control_t'] is not None else None,
                 pre_power=r['power_before'][['GPU','CPU','PSU'].index(r['component'])],
                 delta=r['delta60'][['GPU','CPU','PSU'].index(r['component'])],representative_delay=r['representative_delay_seconds']) for r in old_events]
    del old_events
    assert len(events)==6978 and sum(e['control_t'] is None for e in events)==928
    dump(args.output/'event-index.json',events)
    centers=np.array([e['t'] for e in events]);ids=np.array([e['host_index'] for e in events]);labels=host_array[ids]
    controls=np.array([-1 if e['control_t'] is None else e['control_t'] for e in events]);matched=controls>=0
    quality=np.array([e['relative_mismatch'] if e['relative_mismatch'] is not None else np.nan for e in events])
    event_metrics=[];control_metrics=[]
    summaries={}
    for name,mask,valid,rank in zip(NAMES,masks,valids,ranks):
        event_metrics.append(evaluate(mask,valid,rank,centers,ids));control_metrics.append(evaluate(mask,valid,rank,controls,ids))
        summaries[name]=signal_summary(mask,valid,four)
        print(f'Full D2 and temporal metrics: {name}',flush=True)
    event_metrics=np.stack(event_metrics);control_metrics=np.stack(control_metrics)
    np.savez_compressed(args.output/'event-metrics.npz',event=event_metrics,control=control_metrics)
    categories={'all':np.ones(len(events),bool)}
    for comp in ['GPU','CPU','PSU']:
        for direction in ['drop','rise']:categories[f'{comp} {direction}']=np.array([e['component']==comp and e['direction']==direction for e in events])
    quality_strata={'all':matched,'<=1%':matched&(quality<=.01),'1-5%':matched&(quality>.01)&(quality<=.05),'>5%':matched&(quality>.05)}
    comparisons={};unmatched={}
    shared_risks=np.logical_and.reduce([~event_metrics[m]['pre60']&~control_metrics[m]['pre60']&event_metrics[m]['valid']&control_metrics[m]['valid'] for m in [2,3,4,7]])
    for category,chosen in categories.items():
        comparisons[category]={};unmatched[category]={}
        for m,name in enumerate(NAMES):
            result={}
            for w,key in enumerate(WINDOWS):
                ev,cv=event_metrics[m,w],control_metrics[m,w]
                whole=chosen&ev['valid'];missing=whole&~matched
                risk=(~ev['pre60'])&(~cv['pre60'])
                result[key]=dict(n=int(whole.sum()),any=int(ev['any'][whole].sum()),pre60=int(ev['pre60'][whole].sum()),
                    pre120=int(ev['pre120'][whole].sum()),active_before=int(ev['active_before'][whole].sum()),
                    onset=int(ev['onset'][whole].sum()),fresh=int(ev['fresh'][whole].sum()),
                    continuous_known=int(ev['continuous_known'][whole].sum()),continuous_only=int(ev['continuous_only'][whole].sum()),
                    score_delta=describe(ev['score_delta'][whole]),latency=describe(ev['latency'][whole]),duration=describe(ev['duration'][whole]),
                    primary=paired(ev,cv,chosen&matched,labels,centers),
                    risk=paired(ev,cv,chosen&matched&risk,labels,centers),
                    shared_risk=paired(ev,cv,chosen&matched&shared_risks[w],labels,centers),
                    unmatched=dict(n=int(missing.sum()),fresh=int(ev['fresh'][missing].sum()),pre60=int(ev['pre60'][missing].sum())))
                if key=='120s':
                    result[key]['quality']={q:dict(primary=paired(ev,cv,chosen&qset,labels,centers),
                        risk=paired(ev,cv,chosen&qset&risk,labels,centers)) for q,qset in quality_strata.items()}
            comparisons[category][name]=result
        for tag,subset in [('matched',chosen&matched),('unmatched',chosen&~matched)]:
            unmatched[category][tag]=dict(n=int(subset.sum()),hosts=len(set(labels[subset])),
                pre_power=describe([e['pre_power'] for i,e in enumerate(events) if subset[i]]),
                abs_delta=describe([abs(e['delta']) for i,e in enumerate(events) if subset[i]]),
                representative_delay=describe([e['representative_delay'] for i,e in enumerate(events) if subset[i]]))
    # Reproduce Stage I primary definition rather than silently replacing it.
    for stage2,stage1 in [(0,'A0 historical'),(1,'A0 D1-Q99'),(2,'B1'),(3,'B2'),(4,'Power increment')]:
        for category,chosen in categories.items():
            for key in WINDOWS:
                previous=old['aggregates'][category]['methods'][stage1]['windows'][key]
                actual=comparisons[category][NAMES[stage2]][key]
                assert actual['fresh']==previous['fresh_onset'] and actual['any']==previous['any']
                assert actual['primary']['event']==previous['paired']['event_fresh']
                assert actual['primary']['control']==previous['paired']['control_fresh']
    # Same random host assignments across all methods; no shifting/relabeling time.
    part=np.random.default_rng(4202);draws=np.empty((1999,8,2),np.int64);observed=np.empty((8,2),np.int64)
    matrices=[]
    for m,(mask,valid) in enumerate(zip(masks,valids)):
        matrices.append([cooccurrence(mask),cooccurrence(onsets(mask,valid))])
        observed[m]=[pair_stats(mask)['within'],pair_stats(onsets(mask,valid))['within']]
        for j in range(2):assert partition_pairs(matrices[m][j],np.arange(288).reshape(16,18))==observed[m,j]
    for r in range(1999):
        assignment=part.permutation(288).reshape(16,18)
        for m in range(8):
            for j in range(2):draws[r,m,j]=partition_pairs(matrices[m][j],assignment)
    tails=[empirical_tail(observed[m,j],draws[:,m,j]) for m in range(8) for j in range(2)]
    adjusted=holm([v['p_greater_equal'] for v in tails])
    for v,pv in zip(tails,adjusted):v['p_holm16']=float(pv)
    previous=np.load(args.export/'permutation-controls.npz')['primary']
    assert np.array_equal(draws[:,1:4,0],previous[:,:,0])
    np.savez_compressed(args.output/'topology-controls.npz',observed=observed,draws=draws,seed=4202)
    for m,name in enumerate(NAMES):summaries[name]['permutation']={'signal_pairs':tails[m*2],'onset_pairs':tails[m*2+1]}
    overlap={}
    for m,name in enumerate(NAMES):
        overlap[name]={}
        for j,other in enumerate(NAMES):
            intersection=int((masks[m]&masks[j]).sum());union=int((masks[m]|masks[j]).sum())
            overlap[name][other]=dict(intersection=intersection,union=union,jaccard=intersection/union if union else None,
                share_of_row=intersection/int(masks[m].sum()) if masks[m].any() else None,row_only=int((masks[m]&~masks[j]).sum()))
    budget={}
    for fraction in [.005,.01,.02]:
        budget[str(fraction)]={}
        # H2 any is the bidirectional comparison. Directional channels remain available above.
        for m in [1,2,3,4,7]:
            b,bmeta=equal_budget(ranks[m],v2,fraction)
            ev=evaluate(b,v2,ranks[m],centers,ids)[2];cv=evaluate(b,v2,ranks[m],controls,ids)[2]
            entry=dict(ranking=bmeta,summary=signal_summary(b,v2,four),event={})
            for category,chosen in categories.items():
                entry['event'][category]=dict(fresh=int(ev['fresh'][chosen].sum()),n=int(chosen.sum()),
                    primary=paired(ev,cv,chosen&matched,labels,centers),
                    risk=paired(ev,cv,chosen&matched&~ev['pre60']&~cv['pre60'],labels,centers))
            budget[str(fraction)][NAMES[m]]=entry
    seed_results={}
    for seed,offset in [(42,0),(43,2),(44,4)]:
        q,ht=calibrate(s1[:,:,offset],ts1);bq,_=calibrate(s1[:,:,offset+1],ts1)
        seed_results[str(seed)]={}
        for name,mask in [('A0 D1-Q99',s2[:,:,offset]>q),('B1 / H1 context',s2[:,:,offset]>ht),('B2',s2[:,:,offset+1]>bq)]:
            metric=evaluate(mask,np.ones(v2.shape,bool),s2[:,:,offset+1 if name=='B2' else offset],centers,ids)[2]
            seed_results[str(seed)][name]=dict(signals=int(mask.sum()),four_signals=int(mask[:,four].sum()),
                pairs=pair_stats(mask),fresh={cat:int(metric['fresh'][chosen].sum()) for cat,chosen in categories.items()})
    benchmark=dict(H1_fit=timing(lambda:fit_h1(s1[:,:,0],ts1,hosts)),H1_apply_cached_score=timing(lambda:h1(s2[:,:,0],hp1)),
                   H2_fit=timing(lambda:fit_h2(dp1,v1,ts1,hosts)),H2_apply_delta=timing(lambda:h2(dp2,v2,hp2)),
                   physical_preprocess_D2=timing(lambda:physical(x2)[:,:,:3]),delta_D2=timing(lambda:deltas(power2,ts2)),
                   power_fit=timing(lambda:quantile(np.abs(dp1[v1]),.995,axis=0)),
                   power_apply_delta=timing(lambda:v2&(np.abs(dp2)>power_threshold).any(axis=2)),
                   group_aggregation=timing(lambda:group_arrays(masks[7],v2)))
    stat=json.loads(Path('results/statistical-20220118-8h-v1.json').read_text())['statistical_profile']
    mahal=(d2['distance']>stat['mahalanobis_squared_threshold_q99']).reshape(v2.shape)
    four_info=[dict(host=hosts[h],absolute=describe(s2[:,h,0]),host_threshold=float(qh[h]),
                   absolute_flag_states=int(h1out['absolute_flag'][:,h].sum()),context_states=int(h1out['context'][:,h].sum()),
                   H2plus_states=int(masks[5][:,h].sum()),H2minus_states=int(masks[6][:,h].sum())) for h in four]
    for path,expected in hashes.items():assert sha(path)==expected,path
    report=dict(methods=summaries,comparisons=comparisons,matching=dict(n=6050,unmatched=928,quality=describe(quality),
               strata={k:int(v.sum()) for k,v in quality_strata.items()}),matched_unmatched=unmatched,overlap=overlap,
               budget=budget,seed_results=seed_results,four_hosts=four_info,
               auxiliary_mahalanobis=dict(signals=int(mahal.sum()),overlap={name:int((mask&mahal).sum()) for name,mask in zip(NAMES,masks)},
                                          note='statistical control only; no F1 selection or failure labels'),
               benchmark=benchmark,hashes_before_after=hashes,profile_hashes={n:sha(args.output/n) for n in ['H1-profile.json','H2-profile.json']},
               input_io_seconds=io_seconds,preprocessing_seconds=preprocessing_seconds,fit_seconds=fit_seconds,
               application_seconds=application_seconds,writing_seconds=writing_seconds,elapsed_seconds=time.perf_counter()-started,
               peak_working_set_bytes=peak_memory(),platform=platform.platform(),python=sys.version,
               versions={k:importlib.metadata.version(k) for k in ['numpy','matplotlib','pyarrow','pytest']},
               exported_windows=['D1','D2'],last_timestamp=str(ts2[-1]),H1_exact_score_and_B1_equality=True,
               stageI_primary_reproduced=True,topology_seed=4202,topology_repeats=1999,topology_family=16,
               old_permutation_pair_draws_equal=True)
    dump(args.output/'summary.json',report)
    print(json.dumps(dict(output=str(args.output),H2_thresholds=[hp2['positive_threshold'],hp2['negative_threshold']],
                          signals={n:s['signals'] for n,s in summaries.items()},elapsed_seconds=report['elapsed_seconds'],
                          peak_memory_bytes=report['peak_working_set_bytes']),indent=2))


if __name__=='__main__':main()
