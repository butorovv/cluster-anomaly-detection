"""Resumable single-file download; never overwrite a completed archive."""
import argparse
import http.client
import os
from pathlib import Path
import shutil
import time
import urllib.request

from common import file_hash

URL = 'https://huggingface.co/datasets/MachaParfait/ClusterWise/resolve/main/202201/20220118.parquet'
SHA = '7b6bcb905616865312fdd620d0f3aac9c82b1fcb23dfc1f547d068233cd18934'
MIN_FREE = 5 * 1024**3


def guard(path, reserve=0):
    free = shutil.disk_usage(Path(path).resolve().anchor).free
    if free < MIN_FREE + reserve:
        raise OSError(f'Disk guard: free={free}, required={MIN_FREE + reserve}; partial data retained')
    return free


def download(target):
    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    partial = target.with_suffix(target.suffix + '.part')
    if target.exists():
        if file_hash(target) != SHA:
            raise ValueError('Existing archive checksum differs; refusing overwrite')
        print('Existing archive SHA256 verified', flush=True)
        return
    if partial.exists() and file_hash(partial) == SHA:
        os.replace(partial, target)
        print('Completed partial archive SHA256 verified and published', flush=True)
        return
    for attempt in range(10):
        guard(target, 16 * 1024**2)
        offset = partial.stat().st_size if partial.exists() else 0
        request = urllib.request.Request(URL + '?download=true&resume=' + str(time.time_ns()),
                                        headers={'Range': f'bytes={offset}-', 'Accept-Encoding': 'identity'})
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                content_range = response.headers.get('Content-Range', '')
                if response.status != 206 or not content_range.startswith(f'bytes {offset}-'):
                    if offset or response.status != 200:
                        raise ValueError('Server did not honor resume range; partial retained')
                total = int(content_range.split('/')[-1]) if content_range else int(response.headers['Content-Length'])
                print(f'Download offset={offset} total={total}', flush=True)
                reported = offset
                with partial.open('ab') as stream:
                    while chunk := response.read(8 * 1024**2):
                        guard(target, len(chunk) + 16 * 1024**2)
                        stream.write(chunk)
                        offset += len(chunk)
                        if offset - reported >= 250 * 1024**2:
                            stream.flush()
                            os.fsync(stream.fileno())
                            print(f'Download bytes={offset}/{total} free={guard(target)}', flush=True)
                            reported = offset
                    stream.flush()
                    os.fsync(stream.fileno())
                if offset != total:
                    raise ConnectionError(f'Incomplete response {offset}/{total}')
            actual = file_hash(partial)
            if actual != SHA:
                raise ValueError(f'SHA256 mismatch: {actual}; partial retained')
            os.replace(partial, target)
            print(f'Complete bytes={total} SHA256={actual} free={guard(target)}', flush=True)
            return
        except (ConnectionError, TimeoutError, urllib.error.URLError, http.client.IncompleteRead) as exc:
            print(f'Retry {attempt + 1}: {type(exc).__name__}; partial retained', flush=True)
            time.sleep(2)
    raise ConnectionError('Retry limit reached; rerun to resume')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', default='data/raw/20220118.parquet')
    args = parser.parse_args()
    try:
        download(args.output)
    except KeyboardInterrupt:
        print('Stopped safely; rerun the same command to resume', flush=True)
        raise SystemExit(130)
