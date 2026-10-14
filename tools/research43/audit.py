"""Independent arithmetic checks of stage I; never fits a model."""
import argparse
import hashlib
import json
import sys
from pathlib import Path
import numpy as np

sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'tools/context'))
from context_stats import physical, increments

DTYPE=np.dtype([('timestamp','<i8'),('host','<u4'),('available','<u4'),
                ('features','<f8',(18,)),('scores','<f8',(6,)),('distance','<f8')])
OLD=np.dtype([('timestamp','<i8'),('host','<u4'),('available','<u4'),
             ('features','<f8',(18,)),('score','<f8'),('distance','<f8')])


def sha(path):
    with Path(path).open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output',type=Path,default=Path('results/research43-v4'))
    p.add_argument('--export',type=Path,default=Path('results/context-v1'))
    p.add_argument('--go-replay',type=Path,default=Path('results/research43-go-replay-v1'))
    args=p.parse_args()
    rows=json.loads((args.output/'events.json').read_text())
    summary=json.loads((args.output/'summary.json').read_text())
    d1=np.memmap(args.export/'D1.bin',mode='r',dtype=DTYPE)
    d2=np.memmap(args.export/'D2.bin',mode='r',dtype=DTYPE)
    s1=d1['scores'].reshape(2880,288,6);s2=d2['scores'].reshape(2880,288,6)
    q0=np.sort(s1[:,:,0].ravel())[821145];q2=np.sort(s1[:,:,1].ravel())[821145]
    qh=np.sort(s1[:,:,0],axis=0)[2851]
    assert q0==summary['baseline']['thresholds']['a0']
    assert q2==summary['baseline']['thresholds']['b2']
    x1=d1['features'].reshape(2880,288,18);x2=d2['features'].reshape(2880,288,18)
    dp,_=increments(physical(x2));thresholds=np.asarray(summary['baseline']['physical_thresholds']['power'])
    masks=[s2[:,:,0]>.6850838848387528,s2[:,:,0]>q0,s2[:,:,0]>qh,s2[:,:,1]>q2,(np.abs(dp)>thresholds).any(axis=2)]
    names=['A0 historical','A0 D1-Q99','B1','B2','Power increment']
    windows={'30s':(0,3),'60s':(0,6),'120s':(0,12),'historical':(-3,18)}
    counters=0;matches=set();max_match_diff=0.
    # Independent interval union from the preserved merged candidates.
    coverage=np.zeros((2880,288),bool)
    for r in rows:
        coverage[max(0,r['merged_start']-6):min(2880,r['merged_end']+19),r['host_index']]=True
    power1=physical(x1);power2=physical(x2)
    full_dp=dp.copy();full_dp[:6]=power2[:6,:,:3]-power1[-6:,:,:3]
    coverage |= (np.abs(full_dp)>thresholds).any(axis=2)
    for r in rows:
        h,t=r['host_index'],r['t'];c=r['control_t']
        assert 12<=t<2861
        if c is not None:
            assert 12<=c<2861 and t//360==c//360
            assert (c,h) not in matches;matches.add((c,h))
            assert not coverage[c-12:c+19,h].any()
            j=['GPU','CPU','PSU'].index(r['component'])
            e=np.sort(power1[:,h,j])
            edges=np.array([e[int(np.ceil(q*len(e)))-1] for q in np.arange(.1,1,.1)])
            pc=float(np.median(power2[c-12:c-5,h,j]));pt=float(np.median(power2[t-12:t-5,h,j]))
            assert sum(pc>=edges)==sum(pt>=edges)
            assert abs(pc-pt)==r['control_power_mismatch']
            max_match_diff=max(max_match_diff,abs(pc-pt))
        for m,name in enumerate(names):
            for key,(left,right) in windows.items():
                for center,saved in [(t,r['methods'][name]['windows'][key])]+([(c,r['methods'][name]['control'][key])] if c is not None else []):
                    x=masks[m][:,h];a=center+left;b=center+right
                    any_signal=any(bool(x[i]) for i in range(a,b+1))
                    onsets=[i for i in range(center,b+1) if x[i] and not x[i-1]]
                    quiet=all(not x[i] for i in range(center-6,center))
                    assert any_signal==saved['any']
                    assert bool(onsets)==saved['post_onset']
                    assert bool(onsets and quiet)==saved['fresh_onset']
                    assert bool(x[center-1])==saved['active_before']
                    if onsets:
                        first=onsets[0];end=first
                        while end<len(x) and x[end]:end+=1
                        assert (first-center)*10==saved['latency_seconds']
                        assert (end-first)*10==saved['onset_duration_seconds']
                    counters+=1
    for path,expected in summary['baseline']['input_sha256'].items():assert sha(path)==expected,path
    go_equal=None;go_sha=None
    if args.go_replay.exists():
        replay=np.memmap(args.go_replay/'states.bin',mode='r',dtype=OLD)
        original=np.memmap('results/d2-diagnostics-v1/states.bin',mode='r',dtype=OLD)
        go_sha=sha(args.go_replay/'states.bin')
        go_equal=bool(np.array_equal(replay,original));assert go_equal
        assert go_sha==sha('results/d2-diagnostics-v1/states.bin')
    result=dict(independent_temporal_checks=counters,unique_matched_controls=len(matches),
                matching_hour_host_decile_coverage_verified=True,max_power_mismatch_W=max_match_diff,
                input_hashes_unchanged=True,full_fresh_go_D2_replay_equal=go_equal,fresh_go_binary_sha256=go_sha,
                latest_D2_timestamp=str(np.datetime64(int(d2['timestamp'][-1]),'us')),
                inspected_exports=['D1.bin','D2.bin'],no_D3_scoring=True)
    (args.output/'audit.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    print(json.dumps(result,indent=2))


if __name__=='__main__':main()
