"""Conservative C: floor shared by long-running dataset operations."""
import shutil
from pathlib import Path

MIN_FREE = 5 * 1024**3


def guard(path, reserve=64 * 1024**2):
    free = shutil.disk_usage(Path(path).resolve().anchor).free
    if free < MIN_FREE + reserve:
        raise OSError(f'Disk guard: free={free}, required={MIN_FREE + reserve}; committed data retained')
    return free
