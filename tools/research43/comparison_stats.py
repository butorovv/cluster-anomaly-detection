"""Descriptive group statistics, exact permutation arithmetic, equal budgets."""
import numpy as np


def onsets(mask,valid):
    x,v=np.asarray(mask,bool),np.asarray(valid,bool)
    if x.shape!=v.shape or x.ndim!=2:raise ValueError('time/host arrays required')
    out=np.zeros_like(x)
    out[1:]=x[1:] & ~x[:-1] & v[1:] & v[:-1]
    return out


def group_arrays(mask,valid,size=18):
    x,v=np.asarray(mask,bool),np.asarray(valid,bool)
    if x.shape!=v.shape or x.ndim!=2 or x.shape[1]%size:raise ValueError('equal groups required')
    k=(x&v).reshape(len(x),-1,size).sum(axis=2)
    n=v.reshape(len(v),-1,size).sum(axis=2)
    outside_n=n.sum(axis=1)[:,None]-n
    outside_k=k.sum(axis=1)[:,None]-k
    s=np.divide(k,n,out=np.full(k.shape,np.nan),where=n>0)
    e=s-np.divide(outside_k,outside_n,out=np.full(k.shape,np.nan),where=outside_n>0)
    localized=(k>=2)&(e>0)&np.isfinite(e)
    return k,n,s,e,localized


def cooccurrence(mask):
    x=np.asarray(mask,bool).astype(float)
    return np.rint(x.T@x).astype(np.int64)


def partition_pairs(matrix,part):
    c=np.asarray(matrix,dtype=np.int64);p=np.asarray(part,dtype=int)
    if c.shape!=(p.size,p.size) or not np.array_equal(np.sort(p.ravel()),np.arange(p.size)):
        raise ValueError('partition must preserve every host')
    blocks=c[p[:,:,None],p[:,None,:]]
    diagonals=c[p,p].sum(axis=1)
    return ((blocks.sum(axis=(1,2))-diagonals)//2).sum().item()


def pair_stats(mask,size=18):
    x=np.asarray(mask,bool);k=x.reshape(len(x),-1,size).sum(axis=2)
    cluster=x.sum(axis=1)
    within=int((k*(k-1)//2).sum())
    total=int((cluster*(cluster-1)//2).sum())
    expected=total*(size-1)/(x.shape[1]-1)
    return dict(within=within,cross=total-within,all_pairs=total,
                random_expectation=expected,ratio=within/expected if expected else None)


def equal_budget(scores,valid,fraction):
    values=np.asarray(scores,float);v=np.asarray(valid,bool)
    if values.shape!=v.shape or not 0<fraction<=1 or np.isnan(values[v]).any():
        raise ValueError('defined ranking on common valid observations required')
    indices=np.flatnonzero(v.ravel());flat=values.ravel()
    count=int(np.floor(len(indices)*fraction));order=np.argsort(-flat[indices],kind='stable')
    out=np.zeros(values.size,bool);out[indices[order[:count]]]=True
    cutoff=flat[indices[order[count-1]]] if count else None
    ties=int((flat[indices]==cutoff).sum()) if count else 0
    return out.reshape(values.shape),dict(eligible=len(indices),count=count,cutoff=float(cutoff) if count else None,
                                        tied_at_cutoff=ties,stable_tie_order='timestamp then host')
