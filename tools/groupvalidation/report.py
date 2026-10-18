"""Publish compact tables and scientific figures from one completed validation run."""
import argparse
import csv
import json
import sys
from pathlib import Path

import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.dates as mdates
import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from tools.groupvalidation.common import CHANNELS, PROTOCOL, describe, dump, sha
from tools.groupvalidation.experiments import csv_rows


def publish(source, output):
    output.mkdir(parents=True, exist_ok=False)
    figures = output/'figures'; figures.mkdir()
    manifest = json.loads((source/'artifact-sha256.json').read_text(encoding='utf-8'))
    for name, expected in manifest.items():
        if sha(source/name) != expected:
            raise ValueError(f'changed run artifact: {name}')
    s = json.loads((source/'summary.json').read_text(encoding='utf-8'))
    config = json.loads(PROTOCOL.read_text(encoding='utf-8'))
    if sha(PROTOCOL) != s['protocol_sha256']:
        raise ValueError('changed protocol')
    baseline, perms = s['baseline'], s['permutations']
    events = json.loads((source/'events.json').read_text(encoding='utf-8'))
    controls = json.loads((source/'matched-controls.json').read_text(encoding='utf-8'))
    episodes = json.loads((source/'episodes.json').read_text(encoding='utf-8'))
    summary_metrics = ['R', 'B', 'RB', 'events', 'duration_seconds', 'group_event_HHI',
                       'group_event_entropy', 'multi_5plus_ticks', 'IF_supported_tick_fraction']
    comparison = {k:dict(baseline=baseline[k], controls=describe([p[k] for p in perms]),
                         controls_less_than_baseline=sum(p[k] < baseline[k] for p in perms)) for k in summary_metrics}
    perm_rows = [dict(seed=p['seed'], **{k:p[k] for k in summary_metrics},
                      duration_mean=p['event_duration']['mean'], duration_median=p['event_duration']['median'],
                      duration_max=p['event_duration']['max'], R_witness_fraction_mean=p['R_witness_fraction']['mean'],
                      **{f'R_channel_{k}':v for k,v in p['R_channels'].items()},
                      **{f'R_direction_{k}':v for k,v in p['R_directions'].items()},
                      **{f'duration_bin_{k}':v for k,v in p['duration_bins'].items()},
                      condition_median=p['conditions']['median'], condition_max=p['conditions']['max'], minimum_rank=p['minimum_rank'],
                      R_unknown=p['R_unknown'], B_unknown=p['B_unknown'], profile_sha256=p['profile_sha256']) for p in perms]
    csv_rows(output/'permutations.csv', perm_rows)
    csv_rows(output/'group-permutations.csv', [dict(seed=p['seed'], **{k:v for k,v in g.items() if k != 'R_witness_fraction'},
        witness_fraction_mean=g['R_witness_fraction']['mean']) for p in perms for g in p['per_group']])
    def flat_event(e):
        row = {k:v for k,v in e.items() if not isinstance(v, (dict, list))}
        for channel, values in e.get('R_witness_amplitudes', {}).items():
            for metric in ['min', 'median', 'max']:
                row[f'R_amplitude_{channel}_{metric}'] = values[metric]
        row['R_witness_hosts'] = ','.join(e.get('R_witness_hosts', []))
        return row
    csv_rows(output/'event-metrics.csv', [flat_event(e) for e in events])
    csv_rows(output/'matched-controls.csv', [flat_event(e) for e in controls])
    dump(output/'episodes.json', episodes)
    episode_rows = []
    for e in episodes:
        participants = [g for g in e['per_group'] if g['RB_ticks'] > 0]
        episode_rows.append(dict(label=e['label'], start=e['start'], end_exclusive=e['end_exclusive'],
            groups=','.join(g['group'] for g in participants), group_count=len(participants),
            RB_group_ticks=sum(g['RB_ticks'] for g in participants),
            GPU_temperature_delta_min=min((g['delta_gpu_mean_C'] for g in participants), default=None),
            GPU_temperature_delta_max=max((g['delta_gpu_mean_C'] for g in participants), default=None)))
    csv_rows(output/'multigroup-episodes.csv', episode_rows)
    # Full per-tick interventions remain in results; publish the compact scalar table.
    with (source/'intervention-details.csv').open(encoding='utf-8', newline='') as stream:
        details = list(csv.DictReader(stream))
    profile = json.loads(Path('configs/group-profile.summit-v1.json').read_text(encoding='utf-8'))
    synthetic_rows = []
    for scenario in s['interventions']:
        sid = scenario['scenario']
        q_r = {p['group']:p['r_q99'] for p in profile['groups']}
        q_b = {p['group']:p['b_q99'] for p in profile['groups']}
        rows = [x for x in details if x['scenario'] == sid]
        r_count = sum(x['R_state'] == 'positive' for x in rows)
        b_count = sum(x['B_state'] == 'positive' for x in rows)
        synthetic_rows.append(dict(scenario=sid, groups=','.join(scenario['affected_groups']),
            altered_group_ticks=len(rows), R_positive_ticks=r_count, B_positive_ticks=b_count,
            baseline_RB_ticks=scenario['baseline_positive_ticks'], perturbed_RB_ticks=scenario['perturbed_positive_ticks'],
            new_RB_ticks=scenario['new_positive_ticks'], removed_RB_ticks=scenario['removed_positive_ticks'],
            first_new_delay_seconds=scenario['new_detection_delay_seconds'], unknown_ticks=scenario['unknown_group_ticks'],
            all_D2_events=scenario['metrics']['events'], outside_new_RB_ticks=scenario['extra_positive_ticks_outside_groups'],
            maximum_R_witness_hosts=max((len(x['R_witness_hosts'].split(',')) if x['R_witness_hosts'] else 0 for x in rows), default=0),
            maximum_R_ratio=max((float(x['R_perturbed'])/q_r[x['group']] for x in rows if x['R_perturbed']), default=None),
            maximum_B_ratio=max((float(x['B_perturbed'])/q_b[x['group']] for x in rows if x['B_perturbed']), default=None)))
    csv_rows(output/'interventions.csv', synthetic_rows)
    compact = {k:s[k] for k in ['version', 'D1_parity_max_errors', 'IF_support', 'protected_files',
        'protected_all_unchanged', 'protocol_commit', 'protocol_sha256', 'code_commit', 'code_dirty',
        'python', 'numpy', 'platform', 'go_probe_sha256', 'Go_probe_requests', 'permutation_seconds',
        'total_seconds', 'interpretation']}
    compact.update(baseline=baseline, permutation_comparison=comparison,
                   permutation_physical_channels={k:dict(baseline=baseline['R_channels'][k], controls=describe([p['R_channels'][k] for p in perms])) for k in CHANNELS},
                   permutation_stability={k:dict(baseline=baseline['event_duration'][k],controls=describe([p['event_duration'][k] for p in perms])) for k in ['mean','median','max']},
                   permutation_R_witness_fraction=dict(baseline=baseline['R_witness_fraction']['mean'], controls=describe([p['R_witness_fraction']['mean'] for p in perms])),
                   interventions=s['interventions'], zero_MAD=s['zero_MAD_existing_comparison'],
                   run_artifact_sha256=sha(source/'artifact-sha256.json'),
                   report_code_sha256=sha(__file__), matplotlib=matplotlib.__version__,
                   raw_witness_count_definition='Go above-Q99 hosts in winning channel; may be one when R is negative')
    dump(output/'findings.json', compact)
    dump(output/'run-artifact-sha256.json', manifest)
    # Save all plotted aggregates as the preceding CSV/JSON tables.
    plt.rcParams.update({'font.size':9, 'svg.hashsalt':'group-validation-v1', 'axes.grid':True,
                         'grid.alpha':.2, 'figure.constrained_layout.use':True})
    def save(fig, name):
        fig.savefig(figures/f'{name}.png', dpi=150)
        fig.savefig(figures/f'{name}.svg', metadata={'Date':None})
        path = figures/f'{name}.svg'
        path.write_bytes(('\n'.join(line.rstrip() for line in path.read_text(encoding='utf-8').splitlines())+'\n').encode())
        plt.close(fig)
    fig, axes = plt.subplots(2, 3, figsize=(10, 5))
    for ax, key in zip(axes.ravel(), ['R', 'B', 'RB', 'events', 'group_event_HHI', 'IF_supported_tick_fraction'], strict=True):
        ax.scatter(np.arange(1, 21), [p[key] for p in perms], color='#356c9a', s=22, label='permutation')
        ax.axhline(baseline[key], color='#bd2828', linewidth=1.5, label='documented groups')
        ax.set(title=key, xlabel='fixed seed index', xticks=[1, 5, 10, 15, 20])
    axes[0, 0].legend(fontsize=7)
    fig.suptitle('20 D1-refitted grouping controls; exploratory D2 comparison')
    save(fig, 'topology-controls')
    fig, axes = plt.subplots(1, 2, figsize=(9, 3.2))
    for ax, key, bins in [(axes[0], 'IF_tick_fraction', np.linspace(0, 1, 11)),
                           (axes[1], 'IF_distinct_hosts', np.arange(-.5, 19.5))]:
        ax.hist([e[key] for e in events], bins=bins, histtype='step', linewidth=2, color='#356c9a', label='GroupEvent')
        ax.hist([e[key] for e in controls if e['status'] == 'matched'], bins=bins, histtype='step', linewidth=2, color='#777777', label='matched no-event')
        ax.set(xlabel=key, ylabel='interval count'); ax.legend(fontsize=8)
    fig.suptitle('IF support: 285 event/control pairs; 283 unique controls')
    axes[1].set_xticks([0, 3, 6, 9, 12, 15, 18])
    save(fig, 'if-support-controls')
    with Path('docs/group-runtime-v1/d2/timeline.csv').open(encoding='utf-8', newline='') as stream:
        timeline = list(csv.DictReader(stream))
    times = np.array([np.datetime64(x['timestamp'].removesuffix('Z')) for x in timeline[::16]])
    physical = np.array([[float(x[f'v{k}']) for k in range(5)] for x in timeline]).reshape(2880, 16, 5)
    mask = (times >= np.datetime64('2022-01-18T12:19:00')) & (times < np.datetime64('2022-01-18T12:32:00'))
    fig, axes = plt.subplots(3, 1, figsize=(9, 6.4), sharex=True)
    for ax, k, label in [(axes[0], 0, 'GPU total per host, W'), (axes[1], 2, 'PSU AC total per host, W'),
                          (axes[2], 3, 'GPU mean temperature, degC')]:
        for g in range(11, 16):
            ax.plot(times[mask], physical[mask, g, k], label=f'a{g+1:02}', linewidth=1)
        ax.axvspan(np.datetime64('2022-01-18T12:24:00'), np.datetime64('2022-01-18T12:31:00'), color='#cccccc', alpha=.2)
        ax.axvline(np.datetime64('2022-01-18T12:24:40'), color='black', linewidth=.7, linestyle=':')
        ax.set(ylabel=label)
    axes[0].legend(ncol=5, fontsize=8)
    axes[-1].xaxis.set_major_formatter(mdates.DateFormatter('%H:%M'))
    axes[-1].set_xlabel('2022-01-18 assumed UTC; dotted line: R+B onset; Y unknown')
    fig.suptitle('Shared a12-a16 episode: powers and GPU temperature decrease')
    save(fig, 'shared-episode')
    fig, axes = plt.subplots(3, 1, figsize=(9, 6), sharex=True)
    for sid, label in [('A', '1 host'), ('B', '2 hosts'), ('C', '6 hosts'), ('D', '18 hosts')]:
        rows = [x for x in details if x['scenario'] == sid]
        t = [np.datetime64(x['timestamp'].removesuffix('Z')) for x in rows]
        axes[0].plot(t, [float(x['R_perturbed'])/q_r['a04'] for x in rows], label=f'{sid}: {label}')
        axes[1].plot(t, [float(x['B_perturbed'])/q_b['a04'] for x in rows], label=sid)
        axes[2].plot(t, [int(x['IF_perturbed']) for x in rows], label=sid)
    rows = [x for x in details if x['scenario'] == 'A']
    t = [np.datetime64(x['timestamp'].removesuffix('Z')) for x in rows]
    axes[0].plot(t, [float(x['R_baseline'])/q_r['a04'] for x in rows], color='#777777', linestyle='--', label='baseline')
    axes[1].plot(t, [float(x['B_baseline'])/q_b['a04'] for x in rows], color='#777777', linestyle='--')
    axes[2].plot(t, [int(x['IF_baseline']) for x in rows], color='#777777', linestyle='--')
    for ax in axes[:2]:
        ax.axhline(1, color='black', linestyle=':', linewidth=1)
    axes[1].set_yscale('log')
    axes[0].set_ylabel('R / frozen Q99'); axes[1].set_ylabel(r'B $D^2$ / frozen Q99')
    axes[2].set_ylabel('IF-positive hosts')
    axes[0].legend(ncol=3, fontsize=8)
    axes[-1].xaxis.set_major_formatter(mdates.DateFormatter('%H:%M:%S'))
    axes[-1].set_xlabel('2022-01-18 assumed UTC; +5 degC GPU-mean probes, not fault models')
    fig.suptitle('Fixed perturbations A-D: large B response does not guarantee R+B')
    save(fig, 'temperature-probes')
    fig, axes = plt.subplots(2, 1, figsize=(9, 4.5), sharex=True)
    for g in ['a04', 'a05', 'a06']:
        rows = [x for x in details if x['scenario'] == 'E' and x['group'] == g]
        t = [np.datetime64(x['timestamp'].removesuffix('Z')) for x in rows]
        axes[0].plot(t, [float(x['R_perturbed'])/q_r[g] for x in rows], label=g)
        axes[1].plot(t, [float(x['B_perturbed'])/q_b[g] for x in rows], label=g)
    for ax in axes:
        ax.axhline(1, color='black', linestyle=':', linewidth=1)
    axes[0].legend(ncol=3); axes[0].set_ylabel('R / frozen Q99'); axes[1].set_ylabel(r'B $D^2$ / frozen Q99')
    axes[-1].xaxis.set_major_formatter(mdates.DateFormatter('%H:%M:%S'))
    axes[-1].set_xlabel('2022-01-18 assumed UTC; +120 W GPU and +150 W PSU AC per host')
    fig.suptitle('Fixed three-group power probe E: no new R+B event')
    save(fig, 'power-probe')
    lines = ['# Результаты зарегистрированного group-validation-v1', '',
        f"Protocol commit `{s['protocol_commit']}`; experiment code `{s['code_commit']}`, dirty={s['code_dirty']}.",
        'D2 уже исследован: дополнительные разведочные опыты, не независимое подтверждение.', '',
        '| Метрика | Исходная | Контроли min / median / max |', '|---|---:|---:|']
    for key, values in comparison.items():
        c = values['controls']; lines.append(f"| {key} | {values['baseline']:.6g} | {c['min']:.6g} / {c['median']:.6g} / {c['max']:.6g} |")
    lines += ['', '| Сценарий | R+ | B+ | RB исходные → внесённые | Новые RB | Unknown |', '|---|---:|---:|---:|---:|---:|']
    for x in synthetic_rows:
        lines.append(f"| {x['scenario']} | {x['R_positive_ticks']} | {x['B_positive_ticks']} | {x['baseline_RB_ticks']} → {x['perturbed_RB_ticks']} | {x['new_RB_ticks']} | {x['unknown_ticks']} |")
    lines += ['', 'Величины R/B/RB в таблице сценариев относятся только к изменённым group-ticks.',
        'Полные D2 counts и события — в findings.json/interventions.csv. F даёт фрагментацию, не новые отказы.', '',
        'Исходные 371 защищённый файл и все коэффициенты v1 сохранены. Никакие отрицательные результаты не исправлялись подбором параметров.', '',
        '## Все автоматически выбранные многогрупповые интервалы', '',
        'Условие: не менее пяти одновременных R+B групп на каждом tick. Это интервалы статистической активности, не incident labels.', '',
        '| Начало UTC | Конец exclusive | Групп за интервал | R&B group-ticks |', '|---|---|---:|---:|']
    for e in episode_rows[1:]:
        lines.append(f"| {e['start'][11:19]} | {e['end_exclusive'][11:19]} | {e['group_count']} | {e['RB_group_ticks']} |")
    lines += ['',
        '![Контроль группировки](figures/topology-controls.png)', '',
        '![IF support](figures/if-support-controls.png)', '',
        '![Общий эпизод](figures/shared-episode.png)', '',
        '![Температурные воздействия](figures/temperature-probes.png)', '',
        '![Мощностное воздействие](figures/power-probe.png)', '']
    (output/'README.md').write_bytes(('\n'.join(lines)).encode())
    dump(output/'artifact-sha256.json', {p.relative_to(output).as_posix():sha(p) for p in sorted(output.rglob('*')) if p.is_file()})
    print(json.dumps(dict(status='PASS', files=sum(p.is_file() for p in output.rglob('*')),
                          bytes=sum(p.stat().st_size for p in output.rglob('*') if p.is_file()))))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    publish(args.input, args.output)


if __name__ == '__main__':
    main()
