"""Run the opt-in D1 Go benchmark with Windows process memory/I/O accounting.

Build first: go test -c ./internal/experiment -o .cache/statistical-audit.test.exe
Outputs are new files only; prepared data and profiles are opened read-only.
"""
import argparse
import ctypes as c
import json
import os
import subprocess
import time
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--binary', type=Path, default=Path('.cache/statistical-audit.test.exe'))
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--parquet', default='data/prepared/summit-D1-pilot/D1.parquet')
    parser.add_argument('--manifest', default='data/prepared/summit-D1-pilot/manifest.json')
    parser.add_argument('--profile', default='results/statistical-20220118-8h-v1.json')
    args = parser.parse_args()
    if args.output.exists():
        raise ValueError('Refusing to overwrite measurements')
    if os.name != 'nt':
        raise ValueError('Windows counters required; use Go benchmem directly elsewhere')
    class Memory(c.Structure):
        _fields_ = [('cb', c.c_ulong), ('faults', c.c_ulong)] + [(n, c.c_size_t) for n in
            ['peak_ws', 'ws', 'peak_paged', 'paged', 'peak_nonpaged', 'nonpaged', 'pagefile', 'peak_pagefile']]
    class IO(c.Structure):
        _fields_ = [(n, c.c_ulonglong) for n in ['read_ops', 'write_ops', 'other_ops', 'read_bytes', 'write_bytes', 'other_bytes']]
    kernel, psapi = c.WinDLL('kernel32', use_last_error=True), c.WinDLL('psapi', use_last_error=True)
    kernel.OpenProcess.restype = c.c_void_p
    kernel.OpenProcess.argtypes = [c.c_ulong, c.c_int, c.c_ulong]
    kernel.CloseHandle.argtypes = [c.c_void_p]
    kernel.GetProcessIoCounters.argtypes = [c.c_void_p, c.POINTER(IO)]
    psapi.GetProcessMemoryInfo.argtypes = [c.c_void_p, c.POINTER(Memory), c.c_ulong]
    env = {**os.environ, 'NIR_AUDIT_PARQUET': str(Path(args.parquet).resolve()),
           'NIR_AUDIT_MANIFEST': str(Path(args.manifest).resolve()), 'NIR_AUDIT_PROFILE': str(Path(args.profile).resolve())}
    command = [str(args.binary.resolve()), '-test.run=^$', '-test.bench=BenchmarkFitStatisticalAudit',
               '-test.benchtime=1x', '-test.benchmem', '-test.v']
    start = time.perf_counter()
    # Redirect to a disposable file to avoid pipe backpressure during polling.
    log = Path('.cache/statistical-audit-benchmark.log')
    with log.open('w', encoding='utf-8') as stream:
        process = subprocess.Popen(command, env=env, stdout=stream, stderr=subprocess.STDOUT,
                                   creationflags=subprocess.CREATE_NO_WINDOW)
        handle = kernel.OpenProcess(0x410, False, process.pid)
        if not handle:
            process.terminate()
            raise c.WinError(c.get_last_error())
        memory, io = Memory(), IO()
        memory.cb = c.sizeof(memory)
        peak = 0
        while True:
            if psapi.GetProcessMemoryInfo(handle, c.byref(memory), c.sizeof(memory)):
                peak = max(peak, memory.peak_ws)
            kernel.GetProcessIoCounters(handle, c.byref(io))
            if process.poll() is not None:
                break
            time.sleep(0.1)
        kernel.CloseHandle(handle)
    result = dict(wall_seconds_including_verification=time.perf_counter()-start,
        peak_working_set_bytes=peak, io_counters={n:getattr(io,n) for n,_ in IO._fields_},
        io_semantics='Windows process transfer counters, include cached reads; not physical disk bytes',
        peak_semantics='100ms sampled OS peak working set, includes both fits and parity verification',
        command=command, exit_code=process.returncode, go_benchmark_output=log.read_text(encoding='utf-8'))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2)+'\n', encoding='utf-8')
    print(json.dumps(result))
    raise SystemExit(process.returncode)


if __name__ == '__main__':
    main()
