"""Additional evidence/IF-interval tables from saved D2 CSVs, without inference."""
import argparse
import csv
import datetime as dt
import json
from pathlib import Path
import numpy as np


def tick(s):
    t=dt.datetime.fromisoformat(s.replace('Z','+00:00'))
    return (t.hour*3600+t.minute*60+t.second-8*3600)//10


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--input',type=Path,required=True);args=p.parse_args();root=args.input
    events=json.loads((root/'events.json').read_text(encoding='utf-8'))
    s=np.empty((2880,16));ex=np.empty_like(s);r=np.zeros_like(s,bool);b=np.zeros_like(r)
    times=[]
    with (root/'timeline.csv').open(encoding='utf-8',newline='') as f:
        for i,row in enumerate(csv.DictReader(f)):
            t,g=divmod(i,16)
            if g==0:times.append(row['timestamp'])
            s[t,g]=float(row['IF_S']);ex[t,g]=float(row['E']);r[t,g]=row['R_positive']=='1';b[t,g]=row['B_positive']=='1'
    pairs={}
    with (root/'r-evidence.ndjson').open(encoding='utf-8',newline='\n') as f:
        for line in f:
            row=json.loads(line);pairs[(row['timestamp'],row['group'])]=[w['hostname'] for w in row['r']['defining_pair'] if w['zero_mad']]
    mapping={};zero={e['id']:set() for e in events};temporal={d:np.zeros_like(r) for d in [0,10,30,60]}
    for e in events:
        g=int(e['group'][1:])-1
        for t in range(tick(e['detected_event_time']),tick(e['last_positive_time'])+1):mapping[e['delta_seconds'],t,g]=e
    with (root/'temporal.csv').open(encoding='utf-8',newline='') as f:
        for row in csv.DictReader(f):
            if row['preliminary_candidate']!='1':continue
            t,g,d=tick(row['timestamp']),int(row['group'][1:])-1,int(row['delta_seconds'])
            temporal[d][t,g]=True;e=mapping[d,t,g]
            zero[e['id']].update(pairs.get((row['R_witness_time'],row['group']),[]))
    with (root/'event-context.csv').open('x',encoding='utf-8',newline='') as f:
        names=['event_id','group','delta_seconds','witness_host_count','zero_mad_hosts','zero_mad_pair_ticks','IF_S_min','IF_S_mean','IF_S_max','E_min','E_mean','E_max','IF_supported_ticks','max_simultaneous_groups']
        w=csv.DictWriter(f,fieldnames=names,lineterminator='\n');w.writeheader()
        for e in events:
            g=int(e['group'][1:])-1;a,bend=tick(e['detected_event_time']),tick(e['last_positive_time'])+1
            w.writerow(dict(event_id=e['id'],group=e['group'],delta_seconds=e['delta_seconds'],witness_host_count=len(e['witness_hosts']),zero_mad_hosts=','.join(sorted(zero[e['id']])),zero_mad_pair_ticks=e['zero_mad_pair_ticks'],IF_S_min=float(s[a:bend,g].min()),IF_S_mean=float(s[a:bend,g].mean()),IF_S_max=float(s[a:bend,g].max()),E_min=float(ex[a:bend,g].min()),E_mean=float(ex[a:bend,g].mean()),E_max=float(ex[a:bend,g].max()),IF_supported_ticks=e['if_supported_ticks'],max_simultaneous_groups=int(temporal[e['delta_seconds']][a:bend].sum(axis=1).max())))
    with (root/'if-overlap-intervals.csv').open('x',encoding='utf-8',newline='') as f:
        w=csv.writer(f,lineterminator='\n');w.writerow(['group','criterion','delta_seconds','first_tick','last_tick','duration_grid_seconds'])
        masks=[('raw_R',0,r),('raw_B',0,b)]+[('preliminary',d,m) for d,m in temporal.items()]
        for label,delta,mask in masks:
            for g in range(16):
                x=mask[:,g]&(s[:,g]>0);edges=np.diff(np.r_[False,x,False].astype(int))
                for a,bend in zip(np.flatnonzero(edges==1),np.flatnonzero(edges==-1),strict=True):w.writerow([f'a{g+1:02}',label,delta,times[a],times[bend-1],int(bend-a)*10])
    result={'zero_mad_events_by_host':{host:{str(delta):sum(host in zero[e['id']] for e in events if e['delta_seconds']==delta) for delta in [0,10,30,60]} for host in ['a02n09','a02n10','a09n05','a11n12']},
            'witness_count_delta0':{'min':min(len(e['witness_hosts']) for e in events if e['delta_seconds']==0),'max':max(len(e['witness_hosts']) for e in events if e['delta_seconds']==0)},
            'spatial_delta0':{'positive_E_candidate_ticks':int((temporal[0]&(ex>0)).sum()),'nonpositive_E_candidate_ticks':int((temporal[0]&(ex<=0)).sum())}}
    with (root/'context-analysis.json').open('x',encoding='utf-8',newline='\n') as f:json.dump(result,f,indent=2)
    print(json.dumps(result,indent=2))


if __name__=='__main__':main()
