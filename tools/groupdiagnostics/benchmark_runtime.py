"""Three process repeats at 4/8/16 groups, frozen model, no fitting or tuning."""
import argparse
import ctypes
from ctypes import wintypes
import hashlib
import json
import os
from pathlib import Path
import platform
import subprocess
import time


class Memory(ctypes.Structure):
    _fields_=[('cb',wintypes.DWORD),('PageFaultCount',wintypes.DWORD)]+[(x,ctypes.c_size_t) for x in
        ['PeakWorkingSetSize','WorkingSetSize','QuotaPeakPagedPoolUsage','QuotaPagedPoolUsage',
         'QuotaPeakNonPagedPoolUsage','QuotaNonPagedPoolUsage','PagefileUsage','PeakPagefileUsage']]


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--binary',type=Path,required=True);p.add_argument('--output',type=Path,required=True);p.add_argument('--full-only',action='store_true',help='one 16-group materialized run instead of 9 compact repeats')
    args=p.parse_args();args.output.mkdir(parents=True,exist_ok=False)
    rows=[]
    # Windows reports a process lifetime peak, unlike sampled Go heap.
    api=ctypes.WinDLL('psapi').GetProcessMemoryInfo if os.name=='nt' else None
    if api:api.argtypes=[wintypes.HANDLE,ctypes.POINTER(Memory),wintypes.DWORD];api.restype=wintypes.BOOL
    for n in ([16] if args.full_only else [4,8,16]):
        for repeat in range(1 if args.full_only else 3):
            out=args.output/f'g{n}-r{repeat+1}'
            command=[str(args.binary.resolve()),'--profile','configs/group-profile.summit-v1.json',
                     '--groups',str(n),'--window','D2','--output',str(out)]
            if not args.full_only:command.append('--summary-only')
            start=time.perf_counter()
            with (args.output/f'g{n}-r{repeat+1}.stdout.json').open('xb') as stdout:
                process=subprocess.Popen(command,stdout=stdout,stderr=subprocess.PIPE,creationflags=0x08000000 if os.name=='nt' else 0)
                _,error=process.communicate(timeout=180)
                elapsed=time.perf_counter()-start
                if process.returncode:raise RuntimeError(error.decode(errors='replace'))
                memory=Memory();memory.cb=ctypes.sizeof(memory)
                if api and not api(int(process._handle),ctypes.byref(memory),ctypes.sizeof(memory)):
                    raise ctypes.WinError()
            summary=json.loads((out/'summary.json').read_text(encoding='utf-8'))
            rows.append(dict(groups=n,repeat=repeat+1,wall_seconds=elapsed,exit_code=process.returncode,
                             peak_working_set_bytes=memory.PeakWorkingSetSize if api else None,
                             analysis_seconds=summary['analysis_seconds'],timing=summary['timing'],
                             sampled_peak_heap_bytes=summary['sampled_peak_heap_bytes'],
                             host_states_per_second=summary['host_states_per_second'],event_counts=summary['event_counts'],
                             run_id=summary['run_id'],profile_sha256=summary['group_profile_sha256'],command=command))
            print(json.dumps({k:rows[-1][k] for k in ['groups','repeat','wall_seconds','peak_working_set_bytes']}),flush=True)
    result=dict(platform=platform.platform(),processor=platform.processor(),
                binary_sha256=hashlib.sha256(args.binary.read_bytes()).hexdigest(),
                mode=('full materialized output; one run' if args.full_only else 'summary-only; three repeats')+'; warm OS cache; no cache eviction',repeats=1 if args.full_only else 3,rows=rows)
    with (args.output/'performance.json').open('x',encoding='utf-8',newline='\n') as f:json.dump(result,f,indent=2)


if __name__=='__main__':main()
