"""Explicit denominators and boundary cases found by the preprocessing audit."""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq
import pytest

import build_dataset as builder
import common
import disk_guard


@pytest.mark.parametrize('scenario', ['complete', 'null', 'absent', 'both', 'host_gap', 'edges', 'cores', 'nonfinite'])
def test_exact_daily_counts(synthetic_dataset, tmp_path, scenario):
    fixture = synthetic_dataset
    n = 8640
    removed = {'absent': {100}, 'both': {100}, 'host_gap': set(range(100, 110)), 'edges': {0, n-1}}.get(scenario, set())
    readings = {name: [4.0]*n for name in fixture['schema'].names[2:]}
    invalid = missing = 0
    if scenario in ('null', 'both'):
        readings[fixture['mapping_obj']['features'][common.FEATURES[0]]][200] = None
        invalid = missing = 1
    if scenario == 'cores':
        left, right = fixture['mapping_obj']['features']['cpu0_mean_temp']
        readings[left][300] = None
        readings[left][301] = readings[right][301] = None
        invalid = missing = 1
    if scenario == 'nonfinite':
        name = fixture['mapping_obj']['features'][common.FEATURES[0]]
        for i, x in enumerate([float('nan'), float('inf'), float('-inf'), 0.0], 300):
            readings[name][i] = x
        invalid = missing = 3
    slots = [i for i in range(n) if i not in removed]
    start = datetime(2024, 2, 27, tzinfo=timezone.utc)
    # Reverse the raw rows: disk sorting must restore chronological order.
    slots.reverse()
    arrays = [pa.array([start+timedelta(seconds=10*i) for i in slots], type=fixture['schema'].field('clock').type),
              pa.array(['a01n01']*len(slots))]
    arrays.extend(pa.array([readings[name][i] for i in slots], type=pa.float64()) for name in fixture['schema'].names[2:])
    raw = tmp_path/'raw.parquet'
    pq.write_table(pa.Table.from_arrays(arrays, schema=fixture['schema']), raw)
    day = common.scan_day(raw, fixture['mapping_obj'])
    scratch = tmp_path/'scratch'; scratch.mkdir()
    target = scratch/'prepared.parquet'
    stats = builder.prepare_day(day, fixture['mapping_obj'], ['a01n01'], target, scratch)
    rows = n-len(removed)
    assert stats['rows'] == rows
    assert stats['valid'] == rows-invalid
    assert stats['invalid'] == invalid
    assert stats['missing_samples'] == len(removed)
    assert sum(stats['missing_features'].values()) == missing
    assert stats['coverage'] == stats['sample_coverage'] == rows/n
    assert stats['complete_f18_coverage'] == (rows-invalid)/n
    assert stats['feature_missing_fraction_observed'] == missing/(rows*18)
    assert stats['total_unavailable_feature_positions'] == len(removed)*18+missing
    assert stats['total_feature_unavailability_fraction'] == (len(removed)*18+missing)/(n*18)
    prepared = pq.read_table(target)
    assert prepared['timestamp'].to_pylist() == sorted(prepared['timestamp'].to_pylist())
    assert prepared['availability_mask'].to_pylist().count(common.FULL_MASK) == rows-invalid
    assert prepared.schema.equals(common.PREPARED_SCHEMA, check_metadata=True)
    if scenario == 'cores':
        assert prepared['cpu0_valid_cores'][300].as_py() == 1
        assert prepared['cpu0_mean_temp'][300].as_py() == 4.0
        assert prepared['cpu0_valid_cores'][301].as_py() == 0
        assert prepared['cpu0_mean_temp'][301].as_py() is None
    if scenario == 'nonfinite':
        assert prepared[common.FEATURES[0]][303].as_py() == 0.0
        assert prepared['is_valid'][303].as_py()


def test_zero_rows_and_invalid_statistics():
    metrics = common.availability_metrics(0, 0, 0, 8640)
    assert metrics['sample_coverage'] == metrics['complete_f18_coverage'] == 0
    assert metrics['feature_missing_fraction_observed'] is None
    assert metrics['total_feature_unavailability_fraction'] == 1
    for args in [(1, 1, 1, 1), (2, 1, 0, 2), (1, 0, 19, 1), (2, 2, 0, 1), (0, 0, 0, 0)]:
        with pytest.raises(ValueError):
            common.availability_metrics(*args)


def test_membership_order_duplicates_and_preparation_hosts(synthetic_dataset, tmp_path):
    values = pa.array(['a01n01', 'a02n01', 'a03n01', None])
    first = pc.is_in(values, value_set=pa.array(['a02n01', 'a01n01']))
    second = pc.is_in(values, value_set=pa.array(['a01n01', 'a02n01', 'a01n01']))
    assert first.equals(second)
    for hosts in [[], ['a01n01', 'a01n01'], ['invalid']]:
        with pytest.raises(ValueError):
            builder.prepare_day(None, {}, hosts, tmp_path/'out', tmp_path)


@pytest.mark.parametrize('day_count', [1, 3])
def test_group_metrics_count_actual_days_and_absent_ticks(day_count):
    hosts = [f'a01n{i:02}' for i in range(1, 19)]
    days = []
    for _ in range(day_count):
        stats = {h: common.HostStats(rows=8640, valid=8640) for h in hosts}
        stats[hosts[0]] = common.HostStats(rows=8630, valid=8628, missing_features=2)
        days.append(SimpleNamespace(hosts=stats))
    rows = day_count*(18*8640-10)
    quality = builder.group_quality([('a01', hosts, rows, day_count*2)], days)[0]
    assert quality['expected_samples'] == day_count*18*8640
    assert quality['missing_samples'] == day_count*10
    assert quality['valid'] == rows-day_count*2
    assert quality['coverage'] == (18*8640-10)/(18*8640)
    assert quality['missing_fraction'] == quality['feature_missing_fraction_observed'] == day_count*2/(rows*18)
    assert quality['total_unavailable_feature_positions'] == day_count*182


def test_new_manifest_both_modes_preserve_ranking_and_group_totals(synthetic_dataset):
    fixture = synthetic_dataset
    full = builder.build(fixture['paths'], fixture['output'], fixture['mapping'])
    pilot = builder.build_pilot(fixture['paths'][0], fixture['output'].parent/'pilot', fixture['mapping'])
    for manifest, day_count in [(full, 3), (pilot, 1)]:
        assert manifest['manifest_version'] == 'dataset-manifest-v2'
        assert manifest['schema_version'] == 'F18-v1'
        quality = [x for x in manifest['group_quality'] if x['group_id'] in manifest['selected_groups']]
        stats = list(manifest['missingness_statistics'].values())
        for key in ['rows', 'valid', 'invalid', 'missing_samples', 'missing_feature_positions_observed', 'expected_samples']:
            assert sum(x[key] for x in quality) == sum(x[key] for x in stats)
        assert all(x['expected_samples'] == day_count*18*8640 for x in quality)
    assert full['selected_groups'] == [f'a{i:02}' for i in range(1,17)]
    assert pilot['selected_groups'] == [f'a{i:02}' for i in range(16)]


def test_guard_uses_nearest_existing_destination_and_preserves_reserve(tmp_path, monkeypatch):
    seen = []
    def usage(path):
        seen.append(path)
        return SimpleNamespace(free=disk_guard.MIN_FREE+256*1024**2)
    monkeypatch.setattr(disk_guard.shutil, 'disk_usage', usage)
    assert disk_guard.guard(tmp_path/'new'/'out.parquet', 256*1024**2) == disk_guard.MIN_FREE+256*1024**2
    assert seen == [tmp_path.resolve()]
    with pytest.raises(OSError):
        disk_guard.guard(tmp_path/'new', 256*1024**2+1)
    with pytest.raises(ValueError):
        disk_guard.guard(tmp_path, -1)


def test_scratch_guard_precedes_sqlite_creation(tmp_path, monkeypatch):
    seen = []
    def fail(path, reserve):
        seen.append(path)
        raise OSError('scratch full')
    monkeypatch.setattr(builder, 'guard', fail)
    with pytest.raises(OSError, match='scratch full'):
        builder.prepare_day(None, {}, ['a01n01'], tmp_path/'out', tmp_path)
    assert seen == [tmp_path/'sort.sqlite']
    assert not (tmp_path/'sort.sqlite').exists()


def test_guard_rejects_unavailable_filesystem_without_looping(tmp_path, monkeypatch):
    with monkeypatch.context() as patch:
        patch.setattr(type(tmp_path), 'exists', lambda _: False)
        with pytest.raises(FileNotFoundError, match='filesystem unavailable'):
            disk_guard.guard(tmp_path/'out')


@pytest.mark.parametrize('kind', ['offgrid', 'two_days', 'null'])
def test_time_boundaries_reject_invalid_samples(synthetic_dataset, tmp_path, kind):
    table = pq.read_table(synthetic_dataset['paths'][0]).slice(0, 2)
    start = datetime(2024, 2, 27, tzinfo=timezone.utc)
    times = {'offgrid': [start, start+timedelta(seconds=1)],
             'two_days': [start, start+timedelta(days=1)], 'null': [start, None]}[kind]
    table = table.set_column(0, table.schema.field(0), pa.array(times, type=table.schema.field(0).type))
    path = tmp_path/'bad.parquet'; pq.write_table(table, path)
    with pytest.raises(ValueError):
        common.scan_day(path, synthetic_dataset['mapping_obj'])


def test_timestamp_precision_and_feature_order():
    # A nanosecond timestamp cannot silently be rounded to a different tick.
    with pytest.raises(pa.ArrowInvalid):
        common.timestamp_utc(pa.array([1], type=pa.timestamp('ns', tz='UTC')), None)
    assert list(common.FEATURES) == ['psu0_power', 'psu1_power', 'cpu0_power', 'cpu1_power',
        *[f'gpu{i}_power' for i in range(6)], 'cpu0_mean_temp', 'cpu1_mean_temp',
        *[f'gpu{i}_core_temp' for i in range(6)]]
