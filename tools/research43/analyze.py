"""Frozen stage I: immutable real D1/D2 exports; no model fitting or D3."""
import argparse
import hashlib
import importlib.metadata
import json
import math
import sys
import time
from pathlib import Path
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from tools.context.context_stats import calibrate, physical, physical_thresholds, select_events, increments, linear_runs
from tools.diagnostics.diagnostic_stats import coincidence_metrics, empirical_tail, holm
from tools.research43.stats import temporal, regime_duration, cluster_ci, control_center
from tools.research43.output_paths import new_directory

DTYPE = np.dtype([('timestamp','<i8'),('host','<u4'),('available','<u4'),
                  ('features','<f8',(18,)),('scores','<f8',(6,)),('distance','<f8')])
NAMES = ['A0 historical','A0 D1-Q99','B1','B2','Power increment']
COMP = ['GPU','CPU','PSU']
WINDOWS = {'30s':(0,3),'60s':(0,6),'120s':(0,12),'historical':(-3,18)}


def sha(path):
    with Path(path).open('rb') as f:
        return hashlib.file_digest(f,'sha256').hexdigest()


def dump(path, data):
    Path(path).write_text(json.dumps(data,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')


def describe(values):
    x=np.asarray(values,dtype=float).ravel(); x=x[np.isfinite(x)]
    if not len(x): return dict(n=0)
    return dict(n=len(x),mean=float(x.mean()),min=float(x.min()),max=float(x.max()),
                **{f'q{int(q*100):02}':float(np.quantile(x,q,method='inverted_cdf'))
                   for q in [.01,.25,.5,.75,.95,.99]})


def read_window(root, name, start):
    data=np.memmap(root/f'{name}.bin',dtype=DTYPE,mode='r')
    if len(data)!=829440: raise ValueError('full 288x2880 window required')
    ts=np.datetime64(start,'us').astype('int64')+np.arange(2880)*10_000_000
    assert np.array_equal(data['timestamp'].reshape(2880,288),np.broadcast_to(ts[:,None],(2880,288)))
    assert np.array_equal(data['host'].reshape(2880,288),np.broadcast_to(np.arange(288),(2880,288)))
    assert (data['available']==262143).all()
    assert np.isfinite(data['features']).all() and np.isfinite(data['scores']).all()
    return data,data['features'].reshape(2880,288,18),data['scores'].reshape(2880,288,6),ts


def means_before(x):
    # 7 closed samples [-120,-60], matching the protocol's pre-state.
    out=np.full(x.shape,np.nan)
    for t in range(12,len(x)):
        out[t]=np.median(x[t-12:t-5],axis=0)
    return out


def oracle_score(node,z):
    depth=0
    while node['feature']>=0:
        node=node['left'] if z[node['feature']]<node['split'] else node['right']
        depth+=1
    n=node['size']
    correction=0 if n<2 else 2*math.fsum(1/k for k in range(1,n))-2*(n-1)/n
    return depth+correction


def reproduce(root, meta, d1, d2, x1, s1, s2, ts1, output):
    old=json.loads((root/'summary.json').read_text())
    paths=dict(meta['input_sha256_before'])
    paths.update({str(root/k):v for k,v in meta['binary_sha256'].items()})
    original_meta=json.loads(Path('results/d2-diagnostics-v1/metadata.json').read_text())
    paths['results/d2-diagnostics-v1/states.bin']=original_meta['binary_sha256']
    extra=['permutation-controls.npz','a0-43.json','a0-44.json','b2-42.json','b2-43.json','b2-44.json',
           'context-profile.json','summary.json','metadata.json','thresholds.json']
    paths.update({str(root/f):sha(root/f) for f in extra})
    paths['results/d2-diagnostics-v1/shift_controls.npz']=sha('results/d2-diagnostics-v1/shift_controls.npz')
    for p,expected in paths.items():
        assert sha(p)==expected,p
    assert meta['input_sha256_before']==meta['input_sha256_after']
    q0,qh=calibrate(s1[:,:,0],ts1);q2,_=calibrate(s1[:,:,1],ts1)
    hosts=meta['source']['hosts']; four=[hosts.index(h) for h in ['a02n09','a02n10','a02n11','a02n12']]
    assert q0==old['thresholds']['A0 D1-Q99'] and q2==old['thresholds']['B2']
    assert np.array_equal(qh,[old['thresholds']['B1'][h] for h in hosts])
    stat=json.loads(Path('results/statistical-20220118-8h-v1.json').read_text())['statistical_profile']
    b=[s2[:,:,0]>.6850838848387528,s2[:,:,0]>q0,s2[:,:,0]>qh,s2[:,:,1]>q2]
    original_dtype=np.dtype([('timestamp','<i8'),('host','<u4'),('available','<u4'),
                  ('features','<f8',(18,)),('score','<f8'),('distance','<f8')])
    original=np.memmap('results/d2-diagnostics-v1/states.bin',mode='r',dtype=original_dtype)
    # Stage 4.1 stores boolean availability (1); stage 4.2 stores F18 bitmask.
    assert (original['available']==1).all() and (d2['available']==262143).all()
    for field in ['timestamp','host','features','distance']:
        assert np.array_equal(original[field],d2[field]),field
    assert np.array_equal(original['score'],d2['scores'][:,0])
    mahal=(d2['distance']>stat['mahalanobis_squared_threshold_q99']).reshape(2880,288)
    assert int(mahal.sum())==9880
    np.testing.assert_array_equal(np.sort(s1[:,:,0],axis=0)[math.ceil(.99*2880)-1],qh)
    med=np.asarray([meta['context_profile']['host_medians'][h] for h in hosts])
    sort=np.sort(np.asarray(x1),axis=0)
    median_error=float(np.max(np.abs((sort[1439]+sort[1440])/2-med)))
    assert median_error<1e-12
    del sort
    models=['results/isolation-20220118-v1.json',*[str(root/f) for f in ['b2-42.json','a0-43.json','b2-43.json','a0-44.json','b2-44.json']]]
    indices=np.random.default_rng(4301).choice(829440,1024,replace=False)
    errors={};mahal_error=0.
    for m,path in enumerate(models):
        forest=json.loads(Path(path).read_text())['isolation_forest']
        assert forest['training_window']==dict(start='2022-01-18T00:00:00Z',end_exclusive='2022-01-18T08:00:00Z')
        assert forest['observations']==829440
        n=forest['effective_sample_size'];c=2*math.fsum(1/k for k in range(1,n))-2*(n-1)/n
        for window,data in [('D1',d1),('D2',d2)]:
            error=0.
            for i in indices:
                row=data[i];h=int(row['host'])
                z=(row['features']-(med[h] if m%2 else forest['median']))/forest['effective_scale']
                score=2**(-math.fsum(oracle_score(t,z) for t in forest['trees'])/len(forest['trees'])/c)
                error=max(error,abs(score-row['scores'][m]))
                if m==0:
                    centered=(row['features']-np.asarray(stat['median']))/np.asarray(stat['effective_scale'])-np.asarray(stat['normalized_mean'])
                    ds=float(centered@np.asarray(stat['pseudoinverse'])@centered)
                    mahal_error=max(mahal_error,abs(ds-row['distance']))
            assert error<1e-14,(window,m,error)
            errors[f'{window}:{m}']=error
    assert mahal_error<1e-8,mahal_error
    p1,p2=physical(x1),physical(d2['features'].reshape(2880,288,18))
    pt=physical_thresholds(p1,ts1); events,coverage,quiet=select_events(p2,pt)
    assert events==old['events'] and pt==old['physical_thresholds']
    controls=np.load(root/'permutation-controls.npz')['primary']
    counts={}; topology=[]
    for m,mask in enumerate(b):
        total=int(mask.sum()); assert total==[12847,8153,14341,14123][m]
        reactions=sum(bool(mask[e['t']-3:e['t']+19,e['host']].any()) for e in events)
        assert reactions==[110,1,2352,2625][m]
        assert int(mask[:,four].sum())==old['methods'][NAMES[m]]['four_signals']
        counts[NAMES[m]]=dict(signals=total,four_signals=int(mask[:,four].sum()),four_share=float(mask[:,four].sum()/total),
                             physical_coincidences=reactions,physical_fraction=reactions/len(events))
        if m:
            k=mask.reshape(2880,16,18).sum(axis=2); within=int((k*(k-1)//2).sum())
            tail=empirical_tail(within,controls[:,m-1,0])
            assert within==old['topology']['primary'][(m-1)*3]['actual']
            assert tail['control_mean']==old['topology']['primary'][(m-1)*3]['control_mean']
            cluster=mask.sum(axis=1); expectation=float((cluster*(cluster-1)//2).sum()*17/287)
            topology.append(dict(method=NAMES[m],**tail,exact_random_expectation=expectation,exact_ratio=within/expectation))
    shifted=np.load('results/d2-diagnostics-v1/shift_controls.npz')
    obs=coincidence_metrics(b[0].reshape(2880,16,18)); assert np.array_equal(obs,shifted['observed'])
    ps=[empirical_tail(obs[g,j],shifted['metrics'][:,g,j])['p_greater_equal'] for g in range(16) for j in range(4)]
    adjusted=holm(ps).reshape(16,4)
    assert (adjusted[11:,0]<.05).all()
    result=dict(input_sha256=paths,model_sha256={p:sha(p) for p in models},thresholds=dict(a0=q0,b2=q2,b1=qh.tolist()),
                counts=counts,mahalanobis_signals=int(mahal.sum()),mahalanobis_max_error=mahal_error,
                score_max_errors=errors,median_max_error=median_error,score_oracle_samples_per_model_window=1024,
                full_original_export_equality=True,events=len(events),physical_thresholds=pt,
                topology=topology,shift_holm_a12_a16=adjusted[11:,0].tolist(),
                reproduction='replayed hashed exports, re-evaluated saved controls; no new training or new permutations')
    dump(output/'baseline.json',result)
    print('Baseline reproduced; independent scores and Mahalanobis verified',flush=True)
    return result,b,p1,p2,events,coverage,stat


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--export',type=Path,default=Path('results/context-v1'))
    parser.add_argument('--output',type=Path,default=Path('results/research43-replay'))
    parser.add_argument('--figures',type=Path,help='new figure directory; default: OUTPUT/figures')
    args=parser.parse_args(); started=time.perf_counter()
    args.output=new_directory(args.output)
    args.figures=new_directory(args.figures or args.output/'figures')
    meta=json.loads((args.export/'metadata.json').read_text()); assert meta['record_bytes']==DTYPE.itemsize==216
    assert meta['score_order']==['a0-42','b2-42','a0-43','b2-43','a0-44','b2-44']
    d1,x1,s1,ts1=read_window(args.export,'D1','2022-01-18T00:00')
    d2,x2,s2,ts2=read_window(args.export,'D2','2022-01-18T08:00')
    baseline,binary,p1,p2,events,coverage,stat=reproduce(args.export,meta,d1,d2,x1,s1,s2,ts1,args.output)
    hosts=meta['source']['hosts']; qh=np.asarray(baseline['thresholds']['b1'])
    dp,_=increments(p2);limits=np.asarray(baseline['physical_thresholds']['power'])
    binary.append((np.abs(dp)>limits).any(axis=2))
    # Event selection excludes edge representatives; a quiet control must also
    # exclude strong *raw* increments there. D1 supplies the first 60s lookback.
    matching_dp=dp.copy();matching_dp[:6]=p2[:6,:,:3]-p1[-6:,:,:3]
    control_coverage=coverage | (np.abs(matching_dp)>limits).any(axis=2)
    before=means_before(p2[:,:,:3]); edges={}
    for h in range(288):
        for j in range(3):edges[h,j]=np.quantile(p1[:,h,j],np.arange(.1,1,.1),method='inverted_cdf')
    scale=np.asarray(stat['effective_scale']);median=np.asarray(stat['median'])
    physical_scale=1.4826*np.median(np.abs(p1[:,:,:3]-np.median(p1[:,:,:3],axis=(0,1))),axis=(0,1))
    physical_scale=np.maximum(physical_scale,1e-4)
    physical_median=np.median(p1[:,:,:3],axis=(0,1))
    global_power_sorted=[np.sort(p1[:,:,j].ravel()) for j in range(3)]
    host_power_sorted=np.sort(p1[:,:,:3],axis=0)
    host_scores_sorted=np.sort(s1[:,:,:2],axis=0)
    raw_min=x1.min(axis=0);raw_max=x1.max(axis=0)
    pre_raw=means_before(x2); rows=[];used=set()
    for index,event in enumerate(events):
        t,h,j=event['t'],event['host'],event['component']; direction=event['direction']
        post_raw=np.median(x2[t:t+4,h],axis=0);pre=pre_raw[t,h]
        post_power=np.median(p2[t:t+4,h,:3],axis=0);pre_power=before[t,h]
        nearest=lambda x: float(np.sqrt(np.min(np.sum(((x1[::6,h]-x)/scale)**2,axis=1))))
        rawmin=raw_min[h];rawmax=raw_max[h]
        pre_score=float(np.median(s2[t-12:t-5,h,0])); post_score=float(np.median(s2[t:t+4,h,0]))
        pre_b2=float(np.median(s2[t-12:t-5,h,1]));post_b2=float(np.median(s2[t:t+4,h,1]))
        rank=lambda values,v: float(np.searchsorted(values,v,side='right')/len(values))
        control=control_center(t,h,j,before,edges[h,j],control_coverage,used)
        if control is not None:used.add((control,h))
        same_host=[e for e in events if e['host']==h and e['t']!=t]
        overlap=sum(abs(e['t']-t)<=21 for e in same_host)
        ratios=dp[t,h]/limits; signs=np.sign(dp[t,h][np.abs(ratios)>1])
        row=dict(index=index,host=hosts[h],host_index=h,group=hosts[h][:3],t=t,
                 timestamp=str(np.datetime64(int(ts2[t]),'us')),component=COMP[j],direction=direction,
                 merged_start=event['start'],merged_end=event['end'],representative_delay_seconds=(t-event['start'])*10,
                 overlap_events=overlap,mixed_strong_directions=bool((signs>0).any() and (signs<0).any()),
                 power_before=pre_power.tolist(),power_after=post_power.tolist(),
                 power_at_t_minus60=p2[t-6,h,:3].tolist(),power_at_t=p2[t,h,:3].tolist(),
                 a0_at_t_minus60=float(s2[t-6,h,0]),a0_at_t=float(s2[t,h,0]),
                 b2_at_t_minus60=float(s2[t-6,h,1]),b2_at_t=float(s2[t,h,1]),
                 both_directions_in_merged_component=bool(
                     (dp[event['start']:event['end']+1,h,j]>limits[j]).any() and
                     (dp[event['start']:event['end']+1,h,j]<-limits[j]).any()),
                 delta60=dp[t,h].tolist(),relative_delta=(dp[t,h]/np.maximum(abs(p2[t-6,h,:3]),1)).tolist(),
                 power_z_before=((pre_power-physical_median)/physical_scale).tolist(),
                 power_z_after=((post_power-physical_median)/physical_scale).tolist(),
                 cpu_temp_before=float(pre[10:12].mean()),cpu_temp_after=float(post_raw[10:12].mean()),
                 gpu_temp_before=float(pre[12:].mean()),gpu_temp_after=float(post_raw[12:].mean()),
                 a0_before=pre_score,a0_after=post_score,b2_before=pre_b2,b2_after=post_b2,
                 b1_margin_before=pre_score-qh[h],b1_margin_after=post_score-qh[h],
                 a0_host_D1_percentile_before=rank(host_scores_sorted[:,h,0],pre_score),a0_host_D1_percentile_after=rank(host_scores_sorted[:,h,0],post_score),
                 b2_host_D1_percentile_before=rank(host_scores_sorted[:,h,1],pre_b2),b2_host_D1_percentile_after=rank(host_scores_sorted[:,h,1],post_b2),
                 power_host_D1_percentile_before=rank(host_power_sorted[:,h,j],pre_power[j]),
                 power_host_D1_percentile_after=rank(host_power_sorted[:,h,j],post_power[j]),
                 power_global_D1_percentile_after=rank(global_power_sorted[j],post_power[j]),
                 nearest_D1_before=nearest(pre),nearest_D1_after=nearest(post_raw),
                 outside_host_D1_range_before=int(((pre<rawmin)|(pre>rawmax)).sum()),
                 outside_host_D1_range_after=int(((post_raw<rawmin)|(post_raw>rawmax)).sum()),
                 f18_z_before=((pre-median)/scale).tolist(),f18_z_after=((post_raw-median)/scale).tolist(),
                 regime=regime_duration(p2[:,h,j],t,pre_power[j],post_power[j],direction),
                 control_t=control,control_power_mismatch=float(abs(before[control,h,j]-pre_power[j])) if control is not None else None,
                 methods={})
        for m,name in enumerate(NAMES):
            windows={key:temporal(binary[m][:,h],t,*bounds) for key,bounds in WINDOWS.items()}
            controls={key:temporal(binary[m][:,h],control,*bounds) for key,bounds in WINDOWS.items()} if control is not None else None
            mask=binary[m][t:t+13, h//18*18:(h//18+1)*18]
            item=dict(windows=windows,control=controls,max_group_fraction=float(mask.sum(axis=1).max()/18))
            if m<4:
                score=s2[:,:,1 if m==3 else 0];pre_s=np.median(score[t-12:t-5,h])
                item['delta_score_max120']=float(score[t:t+13,h].max()-pre_s)
                item['score_change_without_crossing']=bool(not windows['120s']['any'] and abs(item['delta_score_max120'])>1e-12)
            row['methods'][name]=item
        rows.append(row)
        if (index+1)%1000==0:print(f'Events {index+1}/{len(events)}; matched={len(used)}',flush=True)
    categories={f'{comp} {direction}':[r for r in rows if r['component']==comp and r['direction']==direction]
                for comp in COMP for direction in ['drop','rise']}
    assert [len(v) for v in categories.values()]==[1337,1447,1430,1490,550,724]
    aggregate={}
    fields=['a0_before','a0_after','b2_before','b2_after','b1_margin_before','b1_margin_after',
            'cpu_temp_before','cpu_temp_after','gpu_temp_before','gpu_temp_after','nearest_D1_before','nearest_D1_after',
            'a0_host_D1_percentile_before','a0_host_D1_percentile_after','b2_host_D1_percentile_before','b2_host_D1_percentile_after',
            'power_host_D1_percentile_before','power_host_D1_percentile_after','power_global_D1_percentile_after',
            'outside_host_D1_range_before','outside_host_D1_range_after','representative_delay_seconds']
    for category,selected in {'all':rows,**categories}.items():
        item=dict(n=len(selected),matched=sum(r['control_t'] is not None for r in selected),
                  mixed_directions=sum(r['mixed_strong_directions'] for r in selected),
                  both_directions_in_merged_component=sum(r['both_directions_in_merged_component'] for r in selected),
                  overlapping=sum(r['overlap_events']>0 for r in selected),
                  distributions={k:describe([r[k] for r in selected]) for k in fields},methods={})
        for k in ['power_before','power_after','power_at_t_minus60','power_at_t','delta60','relative_delta','power_z_before','power_z_after']:
            for j,c in enumerate(COMP):item['distributions'][f'{k}_{c}']=describe([r[k][j] for r in selected])
        for field in ['a0_at_t_minus60','a0_at_t','b2_at_t_minus60','b2_at_t']:
            item['distributions'][field]=describe([r[field] for r in selected])
        item['regime']=dict(duration=describe([r['regime']['seconds'] for r in selected if r['regime']['seconds'] is not None]),
                            undefined=sum(r['regime']['seconds'] is None for r in selected),censored=sum(r['regime']['censored'] for r in selected))
        for name in NAMES:
            mr={}
            for key in WINDOWS:
                rs=[r['methods'][name]['windows'][key] for r in selected]
                stats={flag:sum(r[flag] for r in rs) for flag in ['any','pre120','pre60','active_before','post_onset','fresh_onset','pre_only']}
                stats['latency']=describe([r['latency_seconds'] for r in rs if r['latency_seconds'] is not None])
                stats['onset_duration']=describe([r['onset_duration_seconds'] for r in rs if r['onset_duration_seconds'] is not None])
                stats['censored_runs']=sum(r['onset_run_censored'] for r in rs)
                paired=[r for r in selected if r['control_t'] is not None]
                differences=[int(r['methods'][name]['windows'][key]['fresh_onset'])-int(r['methods'][name]['control'][key]['fresh_onset']) for r in paired]
                stats['paired']=dict(event_fresh=sum(r['methods'][name]['windows'][key]['fresh_onset'] for r in paired),
                                     control_fresh=sum(r['methods'][name]['control'][key]['fresh_onset'] for r in paired),
                                     host_ci=cluster_ci(differences,[r['host'] for r in paired]),
                                     hour_ci=cluster_ci(differences,[r['t']//360 for r in paired]),
                                     halfhour_ci=cluster_ci(differences,[r['t']//180 for r in paired]))
                mr[key]=stats
            item['methods'][name]=dict(windows=mr,max_group_fraction=describe([r['methods'][name]['max_group_fraction'] for r in selected]))
            if name!='Power increment':
                item['methods'][name]['delta_score_max120']=describe([r['methods'][name]['delta_score_max120'] for r in selected])
                item['methods'][name]['continuous_without_crossing']=sum(r['methods'][name]['score_change_without_crossing'] for r in selected)
        aggregate[category]=item
    by_host=[];by_group=[]
    for key,labels,target in [('host',hosts,by_host),('group',sorted({h[:3] for h in hosts}),by_group)]:
        for label in labels:
            rs=[r for r in rows if r[key]==label]
            target.append(dict(label=label,events=len(rs),matched=sum(r['control_t'] is not None for r in rs),
                **{f'{name}_{direction}':dict(n=sum(r['direction']==direction for r in rs),
                    new=sum(r['direction']==direction and r['methods'][name]['windows']['120s']['fresh_onset'] for r in rs))
                   for name in ['B1','B2'] for direction in ['drop','rise']}))
    examples=[]
    for category,rs in categories.items():
        chosen=[max(rs,key=lambda r:abs(r['delta60'][COMP.index(r['component'])])/limits[COMP.index(r['component'])])]
        disagree=[r for r in rs if r['methods']['B1']['windows']['120s']['any']!=r['methods']['B2']['windows']['120s']['any']]
        missed=[r for r in rs if not r['methods']['B1']['windows']['120s']['any'] and not r['methods']['B2']['windows']['120s']['any']]
        chosen.extend(disagree[:1]);chosen.extend(missed[:1])
        examples.extend(dict(category=category,index=r['index']) for r in chosen)
    report=dict(protocol='docs/research-4.3/01-analysis-protocol.md',protocol_sha256=sha('docs/research-4.3/01-analysis-protocol.md'),
                versions={m:importlib.metadata.version(m) for m in ['numpy','matplotlib','pyarrow','pytest']},
                baseline=baseline,aggregates=aggregate,hosts=by_host,groups=by_group,examples=examples,
                bootstrap_seed=4301,bootstrap_repeats=1999,matched=len(used),events=len(rows),
                exported_windows=['D1','D2'],latest_timestamp=str(np.datetime64(int(ts2[-1]),'us')))
    dump(args.output/'events.json',rows)
    dump(args.output/'summary.json',report)
    # Stage I scientific plots: same axes across drop/rise; all real events.
    fig,axes=plt.subplots(3,2,figsize=(11,10))
    for j,c in enumerate(COMP):
        for k,method in enumerate(['B1','B2']):
            ax=axes[j,k]
            for direction in ['drop','rise']:
                values=np.sort([r['a0_after']-r['a0_before'] if method=='B1' else r['b2_after']-r['b2_before'] for r in categories[f'{c} {direction}']])
                ax.plot(values,np.arange(1,len(values)+1)/len(values),label=direction)
            ax.set_title(f'{c} {method}');ax.set_xlabel('post minus pre score');ax.set_ylabel('ECDF');ax.legend();ax.grid(alpha=.2)
    fig.tight_layout();fig.savefig(args.figures/'score-change-ecdf.png',dpi=150);plt.close(fig)
    fig,axes=plt.subplots(1,2,figsize=(12,4))
    for ax,flag in zip(axes,['any','fresh_onset']):
        for method in ['B1','B2']:
            for direction in ['drop','rise']:
                selected=[r for r in rows if r['direction']==direction]
                values=[np.mean([r['methods'][method]['windows'][key][flag] for r in selected])*100 for key in WINDOWS]
                ax.plot(list(WINDOWS),values,'o-',label=f'{method} {direction}')
        ax.set_title(flag);ax.set_ylabel('% physical events');ax.legend();ax.grid(alpha=.2)
    fig.tight_layout();fig.savefig(args.figures/'window-sensitivity.png',dpi=150);plt.close(fig)
    fig,axes=plt.subplots(3,2,figsize=(11,9))
    for j,c in enumerate(COMP):
        for k,direction in enumerate(['drop','rise']):
            ax=axes[j,k];rs=categories[f'{c} {direction}']
            for field in ['a0_host_D1_percentile_before','a0_host_D1_percentile_after','b2_host_D1_percentile_after']:
                v=np.sort([r[field] for r in rs]);ax.plot(v,np.arange(1,len(v)+1)/len(v),label=field.replace('_host_D1_percentile',''))
            ax.set_title(f'{c} {direction}');ax.set_xlabel('host D1 score ECDF percentile');ax.legend(fontsize=7);ax.grid(alpha=.2)
    fig.tight_layout();fig.savefig(args.figures/'d1-representation.png',dpi=150);plt.close(fig)
    for ex in examples:
        row=rows[ex['index']];h,t=row['host_index'],row['t'];a=max(0,t-30);z=min(2880,t+61)
        fig,axes=plt.subplots(3,1,figsize=(10,7),sharex=True);seconds=(np.arange(a,z)-t)*10
        for j,c in enumerate(COMP):axes[0].plot(seconds,p2[a:z,h,j],label=c)
        axes[1].plot(seconds,x2[a:z,h,10:12].mean(axis=1),label='CPU T');axes[1].plot(seconds,p2[a:z,h,3],label='GPU T')
        axes[2].plot(seconds,s2[a:z,h,0],label='A0');axes[2].plot(seconds,s2[a:z,h,1],label='B2')
        axes[2].axhline(qh[h],color='C0',linestyle='--',label='B1 threshold');axes[2].axhline(baseline['thresholds']['b2'],color='C1',linestyle='--',label='B2 threshold')
        for ax in axes:ax.axvline(0,color='black',linestyle=':');ax.legend();ax.grid(alpha=.2)
        axes[0].set_ylabel('W');axes[1].set_ylabel('C');axes[2].set_ylabel('IF score');axes[2].set_xlabel('seconds from representative t')
        fig.suptitle(f"{row['host']} {row['timestamp']} {row['component']} {row['direction']}")
        fig.tight_layout();fig.savefig(args.figures/f"event-{ex['index']}.png",dpi=130);plt.close(fig)
    for path,expected in baseline['input_sha256'].items():assert sha(path)==expected,path
    report['input_hashes_unchanged_after']=True;report['elapsed_seconds']=time.perf_counter()-started
    dump(args.output/'summary.json',report)
    print(json.dumps(dict(events=len(rows),matched=len(used),elapsed_seconds=report['elapsed_seconds'],output=str(args.output)),indent=2))


if __name__=='__main__':main()
