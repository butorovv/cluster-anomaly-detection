"""Conservative free-space floor on the filesystem containing the destination."""
import shutil
from pathlib import Path

MIN_FREE = 5 * 1024**3


def guard(path, reserve=64 * 1024**2):
    if not isinstance(reserve, int) or reserve < 0:
        raise ValueError('Disk reserve must be a non-negative integer')
    destination = Path(path).resolve()
    # The drive anchor can miss a mounted filesystem below it. For a new output
    # find its nearest existing ancestor, which actually receives the writes.
    while not destination.exists():
        parent = destination.parent
        if parent == destination:
            raise FileNotFoundError(f'Destination filesystem unavailable: {destination}')
        destination = parent
    free = shutil.disk_usage(destination).free
    if free < MIN_FREE + reserve:
        raise OSError(f'Disk guard: free={free}, required={MIN_FREE + reserve}; committed data retained')
    return free
