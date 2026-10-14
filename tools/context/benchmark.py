"""Separate threshold timing on the same real exports; no parameter search."""
import json,time
from pathlib import Path
import numpy as np
from analyze import load_window
from context_stats import quantile

def main():
    _,_,s1,_=load_window('results/context-v1/D1.bin','2022-01-18T00:00')
    _,_,s2,_=load_window('results/context-v1/D2.bin','2022-01-18T08:00')
    result={}
    for name,fit,values in [('A0',lambda:quantile(s1[:,:,0]),s2[:,:,0]),
                            ('B1',lambda:quantile(s1[:,:,0],axis=0),s2[:,:,0]),
                            ('B2',lambda:quantile(s1[:,:,1]),s2[:,:,1])]:
        fit();runs=[];apply=[]
        for _ in range(5):
            tic=time.perf_counter();threshold=fit();runs.append(time.perf_counter()-tic)
            tic=time.perf_counter();mask=values>threshold;apply.append(time.perf_counter()-tic)
        result[name]=dict(threshold_seconds=runs,threshold_median_seconds=float(np.median(runs)),
                          application_seconds=apply,application_median_seconds=float(np.median(apply)),
                          signals=int(mask.sum()),scalar_storage_bytes=int(np.asarray(threshold).nbytes))
    Path('results/context-v1/performance.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    print(json.dumps(result,indent=2))
if __name__=='__main__':main()
