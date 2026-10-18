"""Describe the frozen real D2 run; never fit models or select new thresholds."""
import argparse
import csv
import datetime as dt
import hashlib
import json
import math
from pathlib import Path
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

DELTAS = [0,10,30,60]
ZERO_HOSTS = ['a02n09','a02n10','a09n05','a11n12']


def dump(path, value):
    with path.open('x',encoding='utf-8',newline='\n') as f:
        json.dump(value,f,ensure_ascii=False,indent=2,allow_nan=False);f.write('\n')


def dependency(r,b):
    r,b=np.asarray(r,bool),np.asarray(b,bool)
    a,c=int((r&b).sum()),int((~r&b).sum())
    bb,d=int((r&~b).sum()),int((~r&~b).sum())
    n=a+bb+c+d; union=a+bb+c
    den=(a+bb)*(a+c)*(d+bb)*(d+c)
    return dict(joint=a,r_only=bb,b_only=c,neither=d,known=n,
                jaccard=a/union if union else None,
                phi=(a*d-bb*c)/math.sqrt(den) if den else None,
                joint_share=a/n if n else None,r_only_share=bb/n if n else None,b_only_share=c/n if n else None,
                p_b_given_r=a/(a+bb) if a+bb else None,p_r_given_b=a/(a+c) if a+c else None)


def analyze(run, output):
    output.mkdir(parents=True,exist_ok=False)
    figures=output/'figures';figures.mkdir()
    summary=json.loads((run/'summary.json').read_text(encoding='utf-8'))
    assert summary['groups']==16 and summary['ticks']==2880
    assert summary['window']['start']=='2022-01-18T08:00:00Z'
    shape=(2880,16)
    rs,bs,rt,bt,s,e=[np.empty(shape) for _ in range(6)]
    flags=np.zeros(shape+(2,),bool);v=np.empty(shape+(10,));times=[]
    zp=np.zeros(shape,bool);zero_values={h:np.empty(2880) for h in ZERO_HOSTS}
    zero_evidence=[];raw_rows=0
    witness_output=(output/'r-evidence.ndjson').open('x',encoding='utf-8',newline='\n')
    # All raw witnesses and per-host local IF scores remain in the immutable NDJSON.
    with (run/'raw.ndjson').open(encoding='utf-8',newline='\n') as f:
        for line in f:
            row=json.loads(line);t,g=divmod(raw_rows,16)
            assert row['group']==f'a{g+1:02}' and row['complete_hosts']==18
            assert row['y']['state']=='unknown' and row['y']['reason']=='no_approved_sensor_bounds'
            if g==0:times.append(row['timestamp'])
            rs[t,g],rt[t,g]=row['r']['score'],row['r']['threshold']
            bs[t,g],bt[t,g]=row['b']['score'],row['b']['threshold']
            flags[t,g]=[row['r']['state']=='positive',row['b']['state']=='positive']
            s[t,g],e[t,g]=row['if']['s'],row['if']['e'];v[t,g]=row['vector']
            pair=row['r'].get('defining_pair') or []
            zp[t,g]=any(w['zero_mad'] for w in pair) and flags[t,g,0]
            for host in ZERO_HOSTS:
                if host in row['host_values']:zero_values[host][t]=row['host_values'][host][3]
            if flags[t,g,0]:
                witness_output.write(json.dumps({k:row[k] for k in ['timestamp','group','r','b','if','local']},separators=(',',':'))+'\n')
                paired={w['hostname'] for w in pair if w['zero_mad']}
                for w in row['r'].get('zero_mad_above_threshold') or []:
                    zero_evidence.append(dict(timestamp=row['timestamp'],group=row['group'],
                        hostname=w['hostname'],value_C=w['value'],median_C=w['median'],
                        amplitude_C=w['amplitude'],scale_C=w['scale'],z=w['z'],
                        defining_pair=w['hostname'] in paired,selected_channel=row['r']['channel']))
            raw_rows+=1
    assert raw_rows==46080
    witness_output.close()
    temporal=np.zeros((4,)+shape,bool);candidate=np.zeros_like(temporal);temporal_b=np.zeros_like(temporal)
    r_times=np.empty((4,)+shape,dtype=object);b_times=np.empty_like(r_times)
    tr_count=0
    with (run/'temporal.ndjson').open(encoding='utf-8',newline='\n') as f:
        for line in f:
            row=json.loads(line);t=tr_count//64;g=(tr_count//4)%16;j=DELTAS.index(row['delta_seconds'])
            assert row['group']==f'a{g+1:02}' and row['timestamp']==times[t]
            temporal[j,t,g]=row['r']['state']=='positive';temporal_b[j,t,g]=row['b']['state']=='positive'
            candidate[j,t,g]=row['candidate']=='positive'
            r_times[j,t,g]=row['r']['witness_time'];b_times[j,t,g]=row['b']['witness_time']
            assert row['mode']=='preliminary' and row['criteria_incomplete'] and row['hardware_confirmation']=='insufficient_criteria'
            tr_count+=1
    assert tr_count==184320
    with (run/'events.ndjson').open(encoding='utf-8',newline='\n') as f:events=[json.loads(line) for line in f]
    assert len({x['id'] for x in events})==len(events)
    assert all(x['mode']=='preliminary' and x['criteria_incomplete'] and x['hardware_confirmation']=='insufficient_criteria' for x in events)
    for delta in DELTAS:
        spans=[x for x in events if x['delta_seconds']==delta]
        assert sum(x['positive_ticks'] for x in spans)==int(candidate[DELTAS.index(delta)].sum())
        assert all(0<=x['confirmation_delay_seconds']<=delta for x in spans)
    # Source CSVs retain exact float repr for numerical reproduction of figures.
    with (output/'timeline.csv').open('x',encoding='utf-8',newline='') as f:
        writer=csv.writer(f,lineterminator='\n');writer.writerow(['timestamp','group','R','R_threshold','B_D2','B_threshold','Y','R_positive','B_positive','IF_S','E','zero_MAD_pair']+[f'v{i}' for i in range(10)])
        for t in range(2880):
            for g in range(16):writer.writerow([times[t],f'a{g+1:02}',rs[t,g],rt[t,g],bs[t,g],bt[t,g],'unknown',int(flags[t,g,0]),int(flags[t,g,1]),s[t,g],e[t,g],int(zp[t,g]),*v[t,g]])
    with (output/'zero-mad-evidence.csv').open('x',encoding='utf-8',newline='') as f:
        fields=['timestamp','group','hostname','value_C','median_C','amplitude_C','scale_C','z','defining_pair','selected_channel']
        writer=csv.DictWriter(f,fieldnames=fields,lineterminator='\n');writer.writeheader();writer.writerows(zero_evidence)
    with (output/'zero-mad-series.csv').open('x',encoding='utf-8',newline='') as f:
        writer=csv.writer(f,lineterminator='\n');writer.writerow(['timestamp',*ZERO_HOSTS]);writer.writerows([times[t],*[zero_values[h][t] for h in ZERO_HOSTS]] for t in range(2880))
    with (output/'temporal.csv').open('x',encoding='utf-8',newline='') as f:
        writer=csv.writer(f,lineterminator='\n');writer.writerow(['timestamp','group','delta_seconds','temporal_R','temporal_B','preliminary_candidate','R_witness_time','B_witness_time'])
        for j,delta in enumerate(DELTAS):
            for t in range(2880):
                for g in range(16):writer.writerow([times[t],f'a{g+1:02}',delta,int(temporal[j,t,g]),int(temporal_b[j,t,g]),int(candidate[j,t,g]),r_times[j,t,g],b_times[j,t,g]])
    with (output/'events.json').open('x',encoding='utf-8',newline='\n') as f:json.dump(events,f,indent=2)
    with (output/'events.csv').open('x',encoding='utf-8',newline='') as f:
        fields=list(events[0]) if events else ['id','group','delta_seconds'];writer=csv.DictWriter(f,fieldnames=fields,lineterminator='\n');writer.writeheader()
        for event in events:writer.writerow({k:json.dumps(x) if isinstance(x,list) else x for k,x in event.items()})
    bygroup={f'a{g+1:02}':dependency(flags[:,g,0],flags[:,g,1]) for g in range(16)}
    bydelta={}
    for j,delta in enumerate(DELTAS):
        es=[x for x in events if x['delta_seconds']==delta]
        bydelta[str(delta)]=dict(candidate_ticks=int(candidate[j].sum()),events=len(es),
            duration_seconds=sum(x['duration_grid_seconds'] for x in es),
            maximum_duration_seconds=max((x['duration_grid_seconds'] for x in es),default=0),
            if_supported_events=sum(x['if_supported_ticks']>0 for x in es),
            no_if_support_events=sum(x['if_supported_ticks']==0 for x in es),
            zero_mad_pair_events=sum(x['zero_mad_pair_ticks']>0 for x in es),
            maximum_confirmation_delay_seconds=max((x['confirmation_delay_seconds'] for x in es),default=0),
            dependency=dependency(temporal[j],temporal_b[j]),
            simultaneous_groups_histogram=np.bincount(candidate[j].sum(axis=1),minlength=17).tolist())
    zsummary={}
    for host in ZERO_HOSTS:
        z=[x for x in zero_evidence if x['hostname']==host]
        zsummary[host]=dict(r_positive_above_threshold_ticks=len(z),defining_pair_ticks=sum(x['defining_pair'] for x in z),
            amplitude_C_min=min((x['amplitude_C'] for x in z),default=None),amplitude_C_max=max((x['amplitude_C'] for x in z),default=None),
            abs_z_max=max((abs(x['z']) for x in z),default=None),
            defining_pair_amplitude_abs_C_min=min((abs(x['amplitude_C']) for x in z if x['defining_pair']),default=None),
            defining_pair_amplitude_abs_C_median=float(np.median([abs(x['amplitude_C']) for x in z if x['defining_pair']])) if any(x['defining_pair'] for x in z) else None,
            series_min_C=float(zero_values[host].min()),series_max_C=float(zero_values[host].max()))
    base_events=[x for x in events if x['delta_seconds']==0]
    selected=min(base_events,key=lambda x:(-x['duration_grid_seconds'],x['group'],x['detected_event_time'])) if base_events else None
    result=dict(run_id=summary['run_id'],profile_sha256=summary['group_profile_sha256'],
                raw_dependency=dependency(flags[...,0],flags[...,1]),by_group=bygroup,by_delta=bydelta,
                zero_mad=zsummary,zero_mad_pair_r_ticks=int(zp.sum()),selected_event=selected,
                known_group_ticks=46080,Y_unknown_ticks=46080,
                event_audit='unique IDs; event ticks equal candidate ticks; causal delay <= delta; all preliminary',
                source_run_summary_sha256=hashlib.sha256((run/'summary.json').read_bytes()).hexdigest())
    dump(output/'analysis.json',result)
    colors={'R':'#d62728','B':'#1f77b4','Y':'#e6b800'};hours=np.arange(2880)/360+8
    plt.rcParams.update({'font.size':10,'figure.dpi':130,'svg.hashsalt':'summit-group-v1'})
    def save(fig,name):
        fig.tight_layout();fig.savefig(figures/(name+'.png'),bbox_inches='tight');fig.savefig(figures/(name+'.svg'),bbox_inches='tight');plt.close(fig)
        svg=figures/(name+'.svg')
        svg.write_bytes(('\n'.join(line.rstrip() for line in svg.read_text(encoding='utf-8').splitlines())+'\n').encode('utf-8'))
    fig,ax=plt.subplots(4,1,figsize=(12,10),sharex=True)
    ax[0].plot(hours,flags[...,0].sum(axis=1),color=colors['R'],label='R groups');ax[0].plot(hours,flags[...,1].sum(axis=1),color=colors['B'],label='B groups');ax[0].legend();ax[0].set_ylabel('Raw positives')
    ax[1].imshow(candidate[0].T,aspect='auto',interpolation='nearest',origin='lower',extent=[8,16,.5,16.5],cmap='Blues',vmin=0,vmax=1);ax[1].set_yticks(range(1,17));ax[1].set_ylabel('Group a01–a16');ax[1].set_title('Preliminary R+B activity; delta=0 s')
    ax[2].plot(hours,s.mean(axis=1),color='black');ax[2].set_ylabel('Cluster IF share')
    ax[3].axhspan(0,1,facecolor=colors['Y'],alpha=.15);ax[3].text(12,.5,'Y = UNKNOWN (no approved sensor bounds)',ha='center');ax[3].set_ylim(0,1);ax[3].set_yticks([]);ax[3].set_xlabel('Event time, hour (assumed UTC)')
    save(fig,'cluster-activity')
    fig,ax=plt.subplots(1,3,figsize=(13,4))
    for a,key,title in zip(ax,['events','candidate_ticks','duration_seconds'],['Events','Candidate group ticks','Total event duration (s)']):a.bar([str(x) for x in DELTAS],[bydelta[str(x)][key] for x in DELTAS],color='#536e9f');a.set_title(title);a.set_xlabel('Delta (s)')
    save(fig,'delta-sensitivity')
    fig,ax=plt.subplots(4,1,figsize=(12,10),sharex=True)
    for i,host in enumerate(ZERO_HOSTS):
        g=int(host[1:3])-1;ax[i].plot(hours,zero_values[host],color='#555555',lw=.8,label=host+' GPU mean °C')
        z=[x for x in zero_evidence if x['hostname']==host and x['defining_pair']]
        if z:
            xx=[(dt.datetime.fromisoformat(x['timestamp'].replace('Z','+00:00')).hour+dt.datetime.fromisoformat(x['timestamp'].replace('Z','+00:00')).minute/60+dt.datetime.fromisoformat(x['timestamp'].replace('Z','+00:00')).second/3600) for x in z]
            ax[i].scatter(xx,[x['value_C'] for x in z],s=8,color=colors['R'],label='Defining pair in positive R')
        ax[i].legend(loc='upper right');ax[i].set_ylabel('°C')
    ax[-1].set_xlabel('Event time, hour (assumed UTC)');save(fig,'zero-mad-channels')
    if selected:
        g=int(selected['group'][1:])-1;on=dt.datetime.fromisoformat(selected['detected_event_time'].replace('Z','+00:00'));end=dt.datetime.fromisoformat(selected['last_positive_time'].replace('Z','+00:00'))
        left=max(0,int((on.hour*3600+on.minute*60+on.second-8*3600)/10)-60);right=min(2880,int((end.hour*3600+end.minute*60+end.second-8*3600)/10)+61)
    else:
        t,g=np.unravel_index(np.argmax(rs/rt),rs.shape);left=max(0,t-60);right=min(2880,t+61)
    x=hours[left:right];fig,ax=plt.subplots(7,1,figsize=(12,15),sharex=True)
    for k,label in enumerate(['GPU total W','CPU total W','PSU AC total W']):ax[0].plot(x,v[left:right,g,k],label=label)
    ax[0].legend();ax[0].set_ylabel('Group mean W')
    ax[1].plot(x,v[left:right,g,3],label='GPU mean °C');ax[1].plot(x,v[left:right,g,4],label='CPU mean °C');ax[1].legend();ax[1].set_ylabel('°C')
    ax[2].plot(x,rs[left:right,g],color=colors['R'],label='R score');ax[2].axhline(rt[0,g],color=colors['R'],ls='--',label='D1 Q99');ax[2].legend()
    ax[3].plot(x,bs[left:right,g],color=colors['B'],label='Group B D²');ax[3].axhline(bt[0,g],color=colors['B'],ls='--',label='D1 Q99');ax[3].legend()
    ax[4].step(x,flags[left:right,g,0].astype(int)*.25+2,color=colors['R'],label='R raw');ax[4].step(x,flags[left:right,g,1].astype(int)*.25+1,color=colors['B'],label='B raw');ax[4].step(x,candidate[0,left:right,g].astype(int)*.25,color='black',label='Preliminary event');ax[4].set_yticks([0,1,2],['Event','B','R']);ax[4].legend(loc='upper right')
    ax[5].axhspan(0,1,facecolor=colors['Y'],alpha=.15);ax[5].text(float(x.mean()),.5,'Y unknown / hardware confirmation insufficient',ha='center');ax[5].set_yticks([])
    ax[6].plot(x,s[left:right,g],label='IF S');ax[6].plot(x,e[left:right,g],label='E (outside comparison)');ax[6].legend();ax[6].set_xlabel('Event time, hour (assumed UTC)')
    fig.suptitle(f'Deterministic example: a{g+1:02}; longest delta=0 event',y=1.002);save(fig,'event-example')
    fig,ax=plt.subplots(1,2,figsize=(12,4));idx=np.arange(16)
    ax[0].bar(idx-.2,flags[...,0].sum(axis=0),.4,color=colors['R'],label='R');ax[0].bar(idx+.2,flags[...,1].sum(axis=0),.4,color=colors['B'],label='B');ax[0].set_xticks(idx,[f'{g+1:02}' for g in idx]);ax[0].set_xlabel('Group aXX');ax[0].set_title('Raw positive ticks');ax[0].legend()
    ax[1].bar(idx,[sum(x['group']==f'a{g+1:02}' for x in base_events) for g in idx],color='black');ax[1].set_xticks(idx,[f'{g+1:02}' for g in idx]);ax[1].set_title('Preliminary events, delta=0');save(fig,'group-distribution')
    print(json.dumps(result,indent=2))


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--run',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    args=p.parse_args();analyze(args.run,args.output)
