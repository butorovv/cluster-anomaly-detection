"""Additional boundary tests discovered during integration acceptance."""
from dataclasses import replace
import json

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from build_dataset import build
from common import FEATURES, load_mapping, mean_cores, project_batch, scan_day, select_groups


def test_cpu_aggregation_overflow_is_an_error_not_a_valid_state():
    with pytest.raises(ValueError, match="overflow"):
        mean_cores(pa.table({"a": [1e308], "b": [1e308]}), ["a", "b"])


def test_source_mean_has_unknown_core_count_and_keeps_time(synthetic_dataset, tmp_path):
    fixture = synthetic_dataset
    mapping = json.loads(json.dumps(fixture['mapping_obj']))
    for cpu in range(2):
        mapping['features'][f'cpu{cpu}_mean_temp'] = mapping['features'][f'cpu{cpu}_mean_temp'][0]
    path = tmp_path/'mapping.json'
    path.write_text(json.dumps(mapping), encoding='utf-8')
    mapping = load_mapping(path, fixture['schema'])
    source = pq.read_table(fixture['paths'][0]).slice(0, 1)
    result = project_batch(source.to_batches()[0], mapping).to_pylist()[0]
    assert result['timestamp'] == source[mapping['timestamp']][0].as_py()
    assert result['cpu0_valid_cores'] == result['cpu1_valid_cores'] == -1
    assert result['cpu0_mean_temp'] == source[mapping['features']['cpu0_mean_temp']][0].as_py()


def test_grid_inspector_matches_disk_index(synthetic_dataset):
    from inspect_dataset import inspect
    fixture = synthetic_dataset
    regular = inspect(fixture['paths'][0], 'clock', 'machine')
    compact = inspect(fixture['paths'][0], 'clock', 'machine', grid_day=True)
    assert regular == compact


def test_checkpoint_rejects_gaps_and_inconsistent_summary():
    from import_pilot import validate_progress
    from datetime import datetime, timezone, timedelta
    start = datetime(2022, 1, 18, tzinfo=timezone.utc)
    end = start+timedelta(minutes=10)
    state = {'windows': [{'start': start.isoformat(), 'end': end.isoformat(),
                         'states': 17280, 'finite_measurements': 311040, 'inserted_measurements': 311040}],
             'states': 17280, 'measurements': 311040, 'next_timestamp': end.isoformat()}
    validate_progress(state, start)
    state['measurements'] -= 1
    with pytest.raises(ValueError, match='summary'):
        validate_progress(state, start)
    state['measurements'] += 1
    state['windows'][0]['start'] = (start+timedelta(seconds=10)).isoformat()
    with pytest.raises(ValueError, match='contiguous'):
        validate_progress(state, start)


def test_prepared_output_cannot_overwrite_raw_archive(synthetic_dataset):
    fixture = synthetic_dataset
    before = [p.read_bytes() for p in fixture["paths"]]
    with pytest.raises(ValueError, match="different directories"):
        build(fixture["paths"], fixture["paths"][0].parent, fixture["mapping"], replace=True)
    assert [p.read_bytes() for p in fixture["paths"]] == before


def test_partial_cores_and_missing_coordinate_keep_distinct_metadata(synthetic_dataset):
    fixture = synthetic_dataset
    batch = pq.read_table(fixture["paths"][0]).slice(0, 1)
    row = batch.to_pylist()[0]
    mapping = fixture["mapping_obj"]
    row[mapping["features"]["psu0_power"]] = float("nan")
    cpu0 = mapping["features"]["cpu0_mean_temp"]
    row[cpu0[0]], row[cpu0[1]] = None, 32.0
    cpu1 = mapping["features"]["cpu1_mean_temp"]
    row[cpu1[0]], row[cpu1[1]] = None, float("inf")
    prepared = project_batch(pa.Table.from_pylist([row], schema=batch.schema).to_batches()[0], mapping).to_pylist()[0]
    assert prepared["psu0_power"] is None
    assert prepared["cpu0_mean_temp"] == 32.0 and prepared["cpu0_valid_cores"] == 1
    assert prepared["cpu1_mean_temp"] is None and prepared["cpu1_valid_cores"] == 0
    assert prepared["is_valid"] is False
    assert prepared["availability_mask"] == ((1 << 18) - 1) & ~1 & ~(1 << 11)


def test_equal_coverage_prefers_less_missing_data_and_lexical_tie(synthetic_dataset):
    fixture = synthetic_dataset
    mapping = load_mapping(fixture["mapping"], fixture["schema"])
    days = [scan_day(p, mapping) for p in fixture["paths"]]
    days[0].hosts["a01n1"].missing_features = 18
    selected, _ = select_groups(days)
    assert [g[0] for g in selected] == [f"a{i:02d}" for i in range(2,17)] + ["a01"]
    del days[2].hosts["a02n18"]
    selected, eligible = select_groups(days)
    assert "a02" not in {g[0] for g in eligible}
    assert len(selected) == 16  # One missing sample permitted; a missing structural host is not.
    del days[2].hosts["a03n18"]
    with pytest.raises(ValueError, match="Only 15"):
        select_groups(days)


def test_reject_bad_grid_multiple_days_empty_and_incompatible_schema(synthetic_dataset, tmp_path):
    fixture = synthetic_dataset
    mapping = fixture["mapping_obj"]
    table = pq.read_table(fixture["paths"][0])
    rows = table.to_pylist()
    from datetime import timedelta
    rows[0]["clock"] += timedelta(microseconds=1)
    path = tmp_path / "bad-grid.parquet"
    pq.write_table(pa.Table.from_pylist(rows, schema=table.schema), path)
    with pytest.raises(ValueError, match="Off-grid"):
        scan_day(path, mapping)
    rows[0]["clock"] += timedelta(days=1)
    rows[0]["clock"] -= timedelta(microseconds=1)
    pq.write_table(pa.Table.from_pylist(rows, schema=table.schema), path)
    with pytest.raises(ValueError, match="multiple UTC days"):
        scan_day(path, mapping)
    pq.write_table(table.slice(0,0), path)
    with pytest.raises(ValueError, match="Empty"):
        scan_day(path, mapping)
    pq.write_table(table.drop([table.column_names[-1]]), path)
    with pytest.raises(ValueError, match="schemas differ"):
        build([fixture["paths"][0], path, fixture["paths"][2]], tmp_path/"output", fixture["mapping"])


def test_timezone_conversion_and_ambiguous_dst_are_explicit(synthetic_dataset):
    fixture = synthetic_dataset
    source = pq.read_table(fixture["paths"][0]).slice(0,1)
    from datetime import datetime, timezone
    schema = source.schema.set(0, pa.field("clock", pa.timestamp("us")))
    row = source.to_pylist()[0]
    row["clock"] = datetime(2024,2,27,3,0)
    table = pa.Table.from_pylist([row], schema=schema)
    result = project_batch(table.to_batches()[0],fixture["mapping_obj"],"Europe/Moscow")
    assert result["timestamp"].to_pylist() == [datetime(2024,2,27,0,0,tzinfo=timezone.utc)]
    row["clock"] = datetime(2024,11,3,1,30)
    table = pa.Table.from_pylist([row], schema=schema)
    with pytest.raises(pa.ArrowInvalid):
        project_batch(table.to_batches()[0],fixture["mapping_obj"],"America/New_York")
