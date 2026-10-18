"""Read-only regression of saved research 4.3; no training, exports or D3."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from tools.research43.comparison_stats import cooccurrence, onsets, pair_stats, partition_pairs

NAMES = ['A0 historical', 'A0 D1-Q99', 'B1 / H1 context', 'B2',
         'Power', 'H2+', 'H2-', 'H2 any']


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--export', type=Path, default=Path('results/context-v1'))
    parser.add_argument('--stage1', type=Path, default=Path('results/research43-v4'))
    parser.add_argument('--stage2', type=Path, default=Path('results/research43-stage2-v1'))
    args = parser.parse_args()
    if not __debug__:
        raise SystemExit('Assertions must be enabled for numerical regression')
    for name in ['export', 'stage1', 'stage2']:
        setattr(args, name, getattr(args, name).resolve())
    summary = json.loads((args.stage2/'summary.json').read_text())
    paths = [args.export/name for name in ['D1.bin', 'D2.bin', 'metadata.json', 'thresholds.json']]
    paths += [p for folder in [args.stage1, args.stage2] for p in folder.iterdir() if p.is_file()]
    paths += [ROOT/'configs/local-b1.summit-20220118.json']
    before = {str(p): sha(p) for p in paths}
    for path, expected in summary['hashes_before_after'].items():
        assert sha(ROOT/path) == expected, path
    audits = {}
    for script, folder in [('audit.py', args.stage1), ('audit_compare.py', args.stage2)]:
        result = subprocess.run([sys.executable, str(ROOT/'tools/research43'/script),
                                 '--output', str(folder), '--export', str(args.export)],
                                cwd=ROOT, capture_output=True, text=True, timeout=180)
        if result.returncode:
            raise RuntimeError(result.stderr or result.stdout)
        actual = json.loads(result.stdout)
        assert actual == json.loads((folder/'audit.json').read_text()), script
        audits[script] = 'exact match with historical audit'
    with np.load(args.stage2/'masks.npz') as saved:
        masks, valid = saved['masks'], saved['valids']
    with np.load(args.stage2/'topology-controls.npz') as saved:
        draws, observed = saved['draws'], saved['observed']
    starts = np.stack([onsets(mask, available) for mask, available in zip(masks, valid)])
    matrices = []
    for index, name in enumerate(NAMES):
        for j, (mask, key) in enumerate([(masks[index], 'within_pairs'), (starts[index], 'onset_pairs')]):
            actual = pair_stats(mask)
            assert actual == summary['methods'][name][key], (name, key)
            assert actual['within'] == observed[index, j]
            matrices.append(cooccurrence(mask))
    rng = np.random.default_rng(4202)
    assert draws.shape == (1999, 8, 2)
    for repeat in range(1999):
        partition = rng.permutation(288).reshape(16, 18)
        for i, matrix in enumerate(matrices):
            assert partition_pairs(matrix, partition) == draws[repeat, i//2, i%2]
    counts = {name: int(mask.sum()) for name, mask in zip(NAMES, masks)}
    assert counts['B1 / H1 context'] == 14341
    assert [counts[name] for name in ['H2+', 'H2-', 'H2 any']] == [6012, 5895, 11907]
    b1 = json.loads((ROOT/'configs/local-b1.summit-20220118.json').read_text())
    h1 = json.loads((args.stage2/'H1-profile.json').read_text())
    assert [b1['thresholds'][host] for host in h1['hosts']] == h1['host_threshold']
    assert {path: sha(path) for path in before} == before
    print(json.dumps(dict(counts=counts, audits=audits, topology_checks=1999*8*2,
                          B1_thresholds_exact=True, inputs_unchanged=True,
                          inputs=['D1', 'D2'], D3_scored=False), indent=2))


if __name__ == '__main__':
    main()
