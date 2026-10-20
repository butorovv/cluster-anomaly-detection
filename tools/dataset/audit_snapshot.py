"""Read-only byte provenance for the dataset/statistical audit (run at repo root)."""
import argparse
import csv
import hashlib
import json
import subprocess
from pathlib import Path


def git(*args):
    return subprocess.check_output(['git', '-c', f'safe.directory={Path.cwd().as_posix()}', *args])


def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=['save', 'verify'])
    parser.add_argument('manifest', type=Path)
    args = parser.parse_args()
    if args.mode == 'save':
        if args.manifest.exists():
            raise ValueError('Refusing to overwrite baseline')
        names = set(git('ls-files', '-z').decode().split('\0')) - {''}
        # Include ignored raw/prepared/model artifacts recorded by the prior run.
        names.update(json.loads(Path('docs/group-validation-v1/protected-sha256.json').read_text()))
        files = {name: digest(name) for name in sorted(names)}
        args.manifest.parent.mkdir(parents=True, exist_ok=True)
        args.manifest.write_text(json.dumps(dict(base_commit=git('rev-parse', 'HEAD').decode().strip(),
            files=files), indent=2) + '\n', encoding='utf-8')
        print(json.dumps(dict(files=len(files), bytes=sum(Path(n).stat().st_size for n in files))))
    else:
        baseline = json.loads(args.manifest.read_text())['files']
        changes = [name for name, expected in baseline.items() if digest(name) != expected]
        allowed = {'tools/dataset/build_dataset.py', 'tools/dataset/common.py', 'tools/dataset/disk_guard.py'}
        unexpected = [name for name in changes if name not in allowed]
        events = json.loads(Path('docs/group-runtime-v1/d2/events.json').read_text(encoding='utf-8'))
        events = [event for event in events if event['delta_seconds'] == 0]
        with Path('docs/group-runtime-v1/d2/timeline.csv').open(encoding='utf-8', newline='') as stream:
            ticks = list(csv.DictReader(stream))
        counts = dict(R=sum(int(row['R_positive']) for row in ticks), B=sum(int(row['B_positive']) for row in ticks),
                      RB=sum(int(row['R_positive'])*int(row['B_positive']) for row in ticks), events=len(events))
        assert counts == dict(R=899, B=3260, RB=682, events=285)
        assert sum(event['positive_ticks'] for event in events) == 682
        assert all(row['Y'] == 'unknown' for row in ticks)
        print(json.dumps(dict(checked=len(baseline), changed=changes, unexpected=unexpected, baseline=counts)))
        if unexpected:
            raise SystemExit(1)


if __name__ == '__main__':
    main()
