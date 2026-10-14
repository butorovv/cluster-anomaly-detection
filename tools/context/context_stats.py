"""Research-only context statistics. Reuse the tracked stage 4.1 modules."""
import sys
from pathlib import Path
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
DEPENDENCY = ROOT / 'tools/diagnostics'
if not (DEPENDENCY / 'diagnostic_stats.py').is_file():
    raise RuntimeError('Tracked research 4.1 modules are required; see README')
sys.path.insert(0, str(DEPENDENCY))
from diagnostic_stats import linear_runs, empirical_tail, holm, coincidence_metrics


def quantile(x, q=.99, axis=None):
    x = np.asarray(x)
    if not x.size or not np.isfinite(x).all() or not 0 < q <= 1:
        raise ValueError('finite nonempty observations and 0<q<=1 required')
    return np.quantile(x, q, axis=axis, method='inverted_cdf')


def describe(x):
    x = np.asarray(x, dtype=float)
    x = x[np.isfinite(x)]
    if not len(x):
        return {'n': 0}
    return dict(n=int(x.size), mean=float(x.mean()), std=float(x.std()),
                min=float(x.min()), max=float(x.max()),
                **{f'q{int(q*100):02}':float(quantile(x,q)) for q in [.01,.5,.95,.99]})


def calibrate(scores, timestamps):
    """Reject any split other than D1, even if caller accidentally supplies D2."""
    timestamps = np.asarray(timestamps).astype('datetime64[us]')
    if (timestamps < np.datetime64('2022-01-18T00:00')).any() or (timestamps >= np.datetime64('2022-01-18T08:00')).any():
        raise ValueError('calibration requires D1 only')
    if len(timestamps) != len(scores):
        raise ValueError('timestamp/score shape mismatch')
    return float(quantile(scores)), quantile(scores,.99,axis=0)


def support(binary, available, groups):
    x, a = np.asarray(binary, bool), np.asarray(available, bool)
    groups = np.asarray(groups)
    if x.shape != a.shape or x.ndim != 2 or len(groups) != x.shape[1]:
        raise ValueError('time/host arrays required')
    x = x & a
    labels = np.unique(groups)
    k = np.stack([x[:,groups==g].sum(axis=1) for g in labels],axis=1)
    n = np.stack([a[:,groups==g].sum(axis=1) for g in labels],axis=1)
    outside_n = a.sum(axis=1)[:,None]-n
    outside_k = x.sum(axis=1)[:,None]-k
    s = np.divide(k,n,out=np.full(k.shape,np.nan),where=n>0)
    e = s-np.divide(outside_k,outside_n,out=np.full(k.shape,np.nan),where=outside_n>0)
    return k,n,s,e


def partition(rng, hosts=288, size=18):
    if hosts <= 0 or size <= 0 or hosts % size:
        raise ValueError('equal nonempty groups required')
    return rng.permutation(hosts).reshape(-1,size)


def topk(scores, fraction):
    scores = np.asarray(scores)
    if not 0 < fraction <= 1 or not np.isfinite(scores).all():
        raise ValueError('invalid ranking')
    order = np.argsort(-scores.ravel(),kind='stable')
    out = np.zeros(scores.size,bool)
    out[order[:int(np.floor(scores.size*fraction))]] = True
    return out.reshape(scores.shape)


def physical(x):
    return np.stack([x[:,:,4:10].sum(axis=2),x[:,:,2:4].sum(axis=2),
                     x[:,:,:2].sum(axis=2),x[:,:,12:18].mean(axis=2)],axis=2)


def increments(p):
    dp = np.full(p[:,:,:3].shape,np.nan)
    dt = np.full(p.shape[:2],np.nan)
    dp[6:] = p[6:,:,:3]-p[:-6,:,:3]
    dt[:-12] = p[12:,:,3]-p[:-12,:,3]
    return dp,dt


def physical_thresholds(p, timestamps):
    # Deliberately share the split guard, not any detector output.
    calibrate(np.zeros(p.shape[:2]),timestamps)
    dp,dt = increments(p)
    return {'power':quantile(np.abs(dp[6:]),.995,axis=(0,1)).tolist(),
            'temperature':float(quantile(np.abs(dt[:-12]),.995)),
            'power_quiet':quantile(np.abs(dp[6:]),.5,axis=(0,1)).tolist(),
            'temperature_quiet':float(quantile(np.abs(dt[:-12]),.5))}


def select_events(p, thresholds):
    dp,dt = increments(p)
    limits = np.asarray(thresholds['power'])
    # Zero threshold is valid for a constant D1 coordinate; any nonzero D2
    # increment is an exceedance. Ratios use +inf and earliest ties.
    ratio = np.divide(np.abs(dp),limits,out=np.where(np.abs(dp)>0,np.inf,0.),where=limits>0)
    candidate = (np.abs(dp)>limits).any(axis=2)
    candidate[:12] = False
    candidate[-19:] = False
    events=[]
    coverage=np.zeros(p.shape[:2],bool)
    for h in range(p.shape[1]):
        times=np.flatnonzero(candidate[:,h])
        chunks=np.split(times,np.flatnonzero(np.diff(times)>18)+1)
        for chunk in chunks:
            if not len(chunk): continue
            magnitude=ratio[chunk,h].max(axis=1)
            t=int(chunk[np.argmax(magnitude)])
            j=int(np.argmax(ratio[t,h]))
            thermal=bool(abs(dp[t,h,0])>limits[0] and abs(dt[t,h])>thresholds['temperature'] and dp[t,h,0]*dt[t,h]>0)
            events.append(dict(t=t,host=h,start=int(chunk[0]),end=int(chunk[-1]),
                               direction='rise' if dp[t,h,j]>0 else 'drop',thermal=thermal,
                               power_delta=dp[t,h].tolist(),temperature_delta=float(dt[t,h]),
                               component=j))
            # Cover the whole merged transition, not just its representative.
            coverage[max(0,int(chunk[0])-6):min(len(p),int(chunk[-1])+19),h]=True
    quiet=(np.abs(dp)<=thresholds['power_quiet']).all(axis=2)&(np.abs(dt)<=thresholds['temperature_quiet'])&~coverage
    events.sort(key=lambda e:(e['t'],e['host']))
    return events,coverage,quiet


def joint_events(events, groups):
    result=[]
    for g in np.unique(groups):
        rows=sorted([e for e in events if groups[e['host']]==g],key=lambda e:e['t'])
        blocks=[]
        for e in rows:
            if not blocks or e['t']-blocks[-1][-1]['t']>18: blocks.append([])
            blocks[-1].append(e)
        for block in blocks:
            hs=sorted({e['host'] for e in block})
            if len(hs)>=2:
                result.append(dict(group=str(g),start=block[0]['t'],end=block[-1]['t'],hosts=hs))
    return result


def runs_summary(mask):
    lengths=[b-a for a,b in linear_runs(mask)]
    return dict(runs=len(lengths),total_seconds=sum(lengths)*10,
                max_seconds=max(lengths,default=0)*10,
                median_seconds=float(np.median(lengths)*10) if lengths else 0.)
