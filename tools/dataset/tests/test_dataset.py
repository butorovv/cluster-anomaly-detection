from __future__ import annotations

import json
from dataclasses import replace
from datetime import date, timedelta

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

import build_dataset
import common
import inspect_dataset


@pytest.mark.parametrize(("host", "expected"), [("a0n1", ("a00", 1)), ("h50n18", ("h50", 18)), ("b03n9", ("b03", 9))])
def test_hostname_parsing_valid_boundaries(host, expected):
    assert common.parse_hostname(host) == expected


@pytest.mark.parametrize("host", ["a100n1", "a00n0", "i00n1", "a00n19", "a00n01x", None])
def test_hostname_parsing_rejects_out_of_range_or_malformed(host):
    with pytest.raises(ValueError):
        common.parse_hostname(host)


def test_validate_days_requires_order_consecutiveness_and_one_month(synthetic_dataset):
    days = [common.scan_day(path, common.load_mapping(synthetic_dataset["mapping"], synthetic_dataset["schema"]))
            for path in synthetic_dataset["paths"]]
    common.validate_days(days)
    with pytest.raises(ValueError, match="consecutive"):
        common.validate_days([days[1], days[0], days[2]])
    with pytest.raises(ValueError, match="consecutive"):
        common.validate_days([days[0], replace(days[1], date=(date.fromisoformat(days[1].date) + timedelta(days=2)).isoformat()), days[2]])
    boundary = [replace(days[0], date="2024-01-31"), replace(days[1], date="2024-02-01"), replace(days[2], date="2024-02-02")]
    with pytest.raises(ValueError, match="monthly"):
        common.validate_days(boundary)


def test_contract_has_exactly_18_features_and_metadata():
    assert len(common.FEATURES) == 18
    assert len(set(common.FEATURES)) == 18
    assert common.FULL_MASK == (1 << 18) - 1
    assert common.PREPARED_SCHEMA.metadata[b"schema_version"] == common.SCHEMA_VERSION.encode()


def test_cpu_mean_ignores_null_nan_and_infinity_and_all_missing_is_null():
    table = pa.table({"core_a": [2.0, None, float("nan"), float("inf")],
                      "core_b": [4.0, float("inf"), None, float("-inf")]})
    mean, count = common.mean_cores(table, ["core_a", "core_b"])
    assert mean.to_pylist() == [3.0, None, None, None]
    assert count.to_pylist() == [2, 0, 0, 0]


def test_load_mapping_requires_explicit_complete_unambiguous_numeric_schema(synthetic_dataset, tmp_path):
    fixture = synthetic_dataset
    assert common.load_mapping(fixture["mapping"], fixture["schema"]) == fixture["mapping_obj"]
    invalid = dict(fixture["mapping_obj"])
    invalid["features"] = dict(invalid["features"])
    invalid["features"].pop(common.FEATURES[-1])
    path = tmp_path / "incomplete.json"
    path.write_text(json.dumps(invalid), encoding="utf-8")
    with pytest.raises(ValueError, match="exactly these 18"):
        common.load_mapping(path, fixture["schema"])
    ambiguous = json.loads(json.dumps(fixture["mapping_obj"]))
    ambiguous["features"][common.FEATURES[0]] = ambiguous["features"][common.FEATURES[1]]
    path.write_text(json.dumps(ambiguous), encoding="utf-8")
    with pytest.raises(ValueError, match="distinct"):
        common.load_mapping(path, fixture["schema"])
    unknown = json.loads(json.dumps(fixture["mapping_obj"]))
    unknown["features"][common.FEATURES[0]] = "not_in_raw_schema"
    path.write_text(json.dumps(unknown), encoding="utf-8")
    with pytest.raises(ValueError, match="Missing raw column"):
        common.load_mapping(path, fixture["schema"])


def test_project_batch_validity_mask_and_naive_timezone_requirement(synthetic_dataset):
    fixture = synthetic_dataset
    mapping = fixture["mapping_obj"]
    schema = fixture["schema"]
    columns = [pa.array([__import__("datetime").datetime(2024, 2, 27)], type=schema.field("clock").type), pa.array(["a00n1"])]
    columns.extend(pa.array([1.0]) for _ in schema.names[2:])
    prepared = common.project_batch(pa.RecordBatch.from_arrays(columns, schema=schema), mapping)
    assert prepared["availability_mask"].to_pylist() == [common.FULL_MASK]
    assert prepared["is_valid"].to_pylist() == [True]
    assert prepared.schema.equals(common.PREPARED_SCHEMA, check_metadata=True)

    naive_schema = schema.set(0, pa.field("clock", pa.timestamp("us")))
    naive_columns = [pa.array([__import__("datetime").datetime(2024, 2, 27)], type=naive_schema.field("clock").type), *columns[1:]]
    batch = pa.RecordBatch.from_arrays(naive_columns, schema=naive_schema)
    with pytest.raises(ValueError, match="supply --timezone"):
        common.project_batch(batch, mapping)
    assert common.project_batch(batch, mapping, "UTC")["timestamp"].type == pa.timestamp("us", tz="UTC")


def test_scan_day_rejects_exact_duplicate_host_timestamp(synthetic_dataset, tmp_path):
    source = pq.read_table(synthetic_dataset["paths"][0])
    duplicated = pa.concat_tables([source, source.slice(0, 1)])
    path = tmp_path / "duplicate.parquet"
    pq.write_table(duplicated, path)
    mapping = common.load_mapping(synthetic_dataset["mapping"], synthetic_dataset["schema"])
    with pytest.raises(ValueError, match=r"Duplicate \(hostname,timestamp\)"):
        common.scan_day(path, mapping)


def test_group_selection_is_deterministic_common_and_nested_4_8_16(synthetic_dataset):
    fixture = synthetic_dataset
    mapping = common.load_mapping(fixture["mapping"], fixture["schema"])
    days = [common.scan_day(path, mapping) for path in fixture["paths"]]
    selected, eligible = common.select_groups(days)
    groups = [item[0] for item in selected]
    assert groups == [f"a{i:02d}" for i in range(1, 17)]
    assert len(eligible) == 17
    assert set(groups[:4]) <= set(groups[:8]) <= set(groups[:16])
    assert "a00" in {item[0] for item in eligible}  # A single absent sample leaves its group eligible.
    assert next(item[2] for item in eligible if item[0] == "a00") == 107
    assert [item[0] for item in common.select_groups(days)[0]] == groups


def test_full_build_writes_sorted_parquet_and_complete_manifest(synthetic_dataset):
    fixture = synthetic_dataset
    output = fixture["output"]
    manifest = build_dataset.build(fixture["paths"], output, fixture["mapping"])
    assert manifest["selected_groups"] == [f"a{i:02d}" for i in range(1, 17)]
    assert manifest["config_4_groups"] == manifest["selected_groups"][:4]
    assert manifest["config_8_groups"] == manifest["selected_groups"][:8]
    assert manifest["config_16_groups"] == manifest["selected_groups"][:16]
    assert manifest["D1_date"] == "2024-02-27" and manifest["D3_date"] == "2024-02-29"
    assert len(manifest["source_file_hashes"]) == 3
    assert manifest["prepared_timezone"] == "UTC"
    on_disk = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
    assert on_disk["feature_order"] == list(common.FEATURES)
    for index in range(1, 4):
        table = pq.read_table(output / f"D{index}.parquet")
        assert table.schema.equals(common.PREPARED_SCHEMA, check_metadata=True)
        assert all(table["is_valid"].to_pylist())
        keys = list(zip(table["timestamp"].to_pylist(), table["group_id"].to_pylist(), table["hostname"].to_pylist()))
        assert keys == sorted(keys)
    assert manifest["row_count_D2"] == 576  # The one incomplete group is outside the selected 16.


def test_inspection_reports_synthetic_schema_and_duplicate_keys(synthetic_dataset):
    result = inspect_dataset.inspect(synthetic_dataset["paths"][0], timestamp="clock", hostname="machine")
    assert result["duplicate_hostname_timestamp"] == 0
    assert result["unique_hostname_count"] == 306
    assert result["mapping_status"].startswith("unconfirmed")
