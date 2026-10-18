"""Read-only reproduction using clean tracked modules and existing D1/D2 exports."""
import argparse
import hashlib
import json
import sys
from pathlib import Path
import numpy as np

clean = Path(__file__).resolve().parents[2]
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--export', type=Path, default=Path('results/context-v1'))
args = parser.parse_args()
sys.path.insert(0, str(clean))
from tools.context.analyze import load_window, METHODS, FOUR
from tools.context.context_stats import calibrate, physical, physical_thresholds, select_events, joint_events, linear_runs
from tools.diagnostics import diagnostic_stats
assert Path(diagnostic_stats.__file__).resolve() == clean / 'tools/diagnostics/diagnostic_stats.py'
export = args.export.resolve()
meta = json.loads((export / 'metadata.json').read_text())
report = json.loads((export / 'summary.json').read_text())
saved_thresholds = json.loads((export / 'thresholds.json').read_text())
before = {}
for name in ['D1.bin', 'D2.bin', 'metadata.json', 'summary.json', 'thresholds.json']:
    with (export / name).open('rb') as stream:
        before[name] = hashlib.file_digest(stream, 'sha256').hexdigest()
for name, expected in meta['binary_sha256'].items():
    assert before[name] == expected
d1, x1, s1, ts1 = load_window(export / 'D1.bin', '2022-01-18T00:00')
d2, x2, s2, ts2 = load_window(export / 'D2.bin', '2022-01-18T08:00')
q0, qh = calibrate(s1[:, :, 0], ts1)
q2, _ = calibrate(s1[:, :, 1], ts1)
hosts = meta['source']['hosts']
thresholds = {'A0 historical': .6850838848387528, 'A0 D1-Q99': q0,
              'B1': dict(zip(hosts, qh.tolist())), 'B2': q2}
assert thresholds == saved_thresholds == report['thresholds']
four = [hosts.index(h) for h in FOUR]
binary = [s2[:, :, 0] > thresholds['A0 historical'], s2[:, :, 0] > q0,
          s2[:, :, 0] > qh, s2[:, :, 1] > q2]
binary1 = [s1[:, :, 0] > thresholds['A0 historical'], s1[:, :, 0] > q0,
           s1[:, :, 0] > qh, s1[:, :, 1] > q2]
counts = {}
for name, b, b1 in zip(METHODS, binary, binary1):
    saved = report['methods'][name]
    assert int(b.sum()) == saved['d2_signals']
    assert int(b1.sum()) == saved['d1_signals']
    assert int(b[:, four].sum()) == saved['four_signals']
    assert sum(len(linear_runs(b[:, h])) for h in range(288)) == saved['runs']
    assert [int(b[:, h].sum()) for h in range(288)] == [h['methods'][name]['d2'] for h in report['hosts']]
    assert [int(b[:, g*18:(g+1)*18].sum()) for g in range(16)] == [g['methods'][name]['signals'] for g in report['groups']]
    counts[name] = int(b.sum())
p1, p2 = physical(x1), physical(x2)
pt = physical_thresholds(p1, ts1)
assert pt == report['physical_thresholds']
events, transition, quiet = select_events(p2, pt)
assert events == report['events']
groups = np.array([h[:3] for h in hosts])
joints = joint_events(events, groups)
assert joints == report['joint_events']
assert int(transition.sum()) == report['transition_state_count']
assert int(quiet.sum()) == report['quiet_state_count']
for name, b in zip(METHODS, binary):
    assert int((b & transition).sum()) == report['methods'][name]['transition_signals']
    assert int((b & quiet).sum()) == report['methods'][name]['quiet_signals']
for name, expected in before.items():
    with (export / name).open('rb') as stream:
        assert hashlib.file_digest(stream, 'sha256').hexdigest() == expected
print(json.dumps({'counts': counts, 'physical_events': len(events), 'joint_events': len(joints),
                  'D1_thresholds_exact': True, 'all_host_group_run_counts_exact': True,
                  'immutable_export_hashes': before, 'dependency': str(diagnostic_stats.__file__)}, indent=2))
