from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "tools" / "context"))
from context_stats import (  # noqa: E402
    calibrate, increments, partition, physical, physical_thresholds,
    quantile, runs_summary, select_events, support, topk,
)
sys.path.insert(0, str(ROOT / "tools" / "research43" / "vendor" / "research41"))
sys.path.insert(0, str(ROOT / "tools" / "context"))
from context_stats import joint_events  # noqa: E402
from analyze import aggregate_reactions, reaction  # noqa: E402


def d1_times(n):
    return np.datetime64("2022-01-18T00:00", "us") + np.arange(n) * np.timedelta64(10, "s")


def test_quantile_uses_inverted_cdf_ties_and_strict_threshold():
    values = np.array([1., 2., 2., 2., 9.])
    assert quantile(values, .6) == 2
    assert quantile(values, .5) == 2
    threshold, per_host = calibrate(np.column_stack([values, values[::-1]]), d1_times(5))
    assert threshold == 9
    np.testing.assert_array_equal(per_host, [9, 9])
    assert not np.any(values[:4] > quantile(values, .6))
    assert values[-1] > quantile(values, .6)


@pytest.mark.parametrize("bad_time", ["2022-01-18T08:00", "2022-01-18T16:00"])
def test_calibration_rejects_d2_and_d3_timestamps(bad_time):
    times = d1_times(3)
    times[-1] = np.datetime64(bad_time, "us")
    with pytest.raises(ValueError, match="D1"):
        calibrate(np.ones(3), times)


def test_calibration_rejects_shape_mismatch():
    with pytest.raises(ValueError, match="shape"):
        calibrate(np.ones(2), d1_times(3))


def test_support_uses_actual_availability_and_undefined_complements():
    binary = np.array([[1, 1, 0, 1], [1, 0, 1, 0], [0, 0, 0, 1]], bool)
    available = np.array([[1, 0, 1, 1], [0, 0, 1, 1], [0, 0, 0, 1]], bool)
    groups = np.array(["A", "A", "B", "C"])
    k, n, s, e = support(binary, available, groups)
    np.testing.assert_array_equal(k, [[1, 0, 1], [0, 1, 0], [0, 0, 1]])
    np.testing.assert_array_equal(n, [[1, 1, 1], [0, 1, 1], [0, 0, 1]])
    assert s[0, 0] == 1 and e[0, 0] == pytest.approx(.5)
    assert np.isnan(s[1, 0]) and np.isnan(e[1, 0])  # no observed A host
    assert np.isnan(e[2, 2])  # no available host outside C
    assert s[1, 1] == 1 and e[1, 1] == 1
    assert np.all(k.sum(axis=1) == (binary & available).sum(axis=1))
    with pytest.raises(ValueError):
        support(binary[:, :2], available, groups)


def test_partition_is_reproducible_equal_and_preserves_hosts():
    first = partition(np.random.default_rng(4202), hosts=12, size=3)
    second = partition(np.random.default_rng(4202), hosts=12, size=3)
    np.testing.assert_array_equal(first, second)
    assert first.shape == (4, 3)
    np.testing.assert_array_equal(np.sort(first.ravel()), np.arange(12))
    with pytest.raises(ValueError):
        partition(np.random.default_rng(1), hosts=10, size=3)


def test_topk_uses_floor_and_stable_flattened_order_for_ties():
    scores = np.array([[5., 5., 4.], [5., 3., 2.]])
    np.testing.assert_array_equal(topk(scores, .5), [[1, 1, 0], [1, 0, 0]])
    np.testing.assert_array_equal(topk(scores, .32), [[1, 0, 0], [0, 0, 0]])
    assert topk(scores, 1).all()
    with pytest.raises(ValueError):
        topk(scores, 0)


def test_runs_summary_counts_disjoint_runs_in_seconds():
    from context_stats import linear_runs
    np.testing.assert_array_equal(linear_runs(np.array([0, 1, 1, 0, 1], bool)), [[1, 3], [4, 5]])
    assert runs_summary(np.array([0, 1, 1, 0, 1], bool)) == {
        "runs": 2, "total_seconds": 30, "max_seconds": 20, "median_seconds": 15.0,
    }
    assert runs_summary(np.zeros(4, bool))["runs"] == 0


def test_physical_features_and_increment_windows_have_protocol_sign_and_lag():
    raw = np.zeros((20, 1, 18), float)
    raw[:, :, 4:10] = 1
    raw[:, :, 2:4] = 2
    raw[:, :, :2] = 3
    raw[:, :, 12:18] = np.arange(20)[:, None, None]
    p = physical(raw)
    np.testing.assert_array_equal(p[0, 0], [6, 4, 6, 0])
    p[:, 0, 0] = np.arange(20)
    p[:, 0, 3] = np.arange(20) * 2
    dp, dt = increments(p)
    assert dp[6, 0, 0] == 6
    assert np.isnan(dp[5, 0, 0])
    assert dt[0, 0] == 24
    assert np.isnan(dt[8, 0])
    assert np.isnan(dt[8, 0]) and dt[7, 0] == 24


def _event_series(n=70, hosts=2):
    p = np.zeros((n, hosts, 4), float)
    p[:, :, 3] = 20
    return p


def test_physical_thresholds_are_d1_only_and_events_do_not_use_model_scores():
    p = _event_series(80, 1)
    p[20:, 0, 0] = 1
    with pytest.raises(ValueError, match="D1"):
        physical_thresholds(p, np.datetime64("2022-01-18T08:00") + np.arange(80) * np.timedelta64(10, "s"))
    thresholds = {"power": [0., 2., 2.], "temperature": 0.,
                  "power_quiet": [0., 0., 0.], "temperature_quiet": 0.}
    events, coverage, quiet = select_events(p, thresholds)
    assert len(events) == 1
    assert events[0]["direction"] == "rise"
    assert events[0]["component"] == 0
    assert events[0]["thermal"] is False
    assert np.all(coverage[14:44, 0])
    assert np.all(~quiet[14:44, 0])


def test_event_merging_gap_boundary_representative_and_full_coverage():
    p = _event_series(100, 1)
    # Each 60-second difference remains elevated for six samples.
    # Starts 20, 38 merge; start 64 is 210 seconds after the first block ends.
    p[20:, 0, 0] += 1
    p[38:, 0, 0] += 1
    p[64:, 0, 1] += 5
    thresholds = {"power": [0.5, 0.5, 100.], "temperature": 100.,
                  "power_quiet": [0., 0., 0.], "temperature_quiet": 0.}
    events, coverage, _ = select_events(p, thresholds)
    assert len(events) == 2
    assert [(e["start"], e["end"]) for e in events] == [(20, 43), (64, 69)]
    assert events[0]["t"] == 20  # equal normalized maxima choose earliest
    assert np.all(coverage[14:62, 0])
    assert np.all(coverage[58:88, 0])


def test_event_physical_bounds_and_thermal_same_sign_condition():
    p = _event_series(70, 1)
    p[11:, 0, 0] = np.arange(59) * 2
    p[:, 0, 3] = 0
    p[23:, 0, 3] = 2
    thresholds = {"power": [1., 100., 100.], "temperature": 1.,
                  "power_quiet": [0., 0., 0.], "temperature_quiet": 0.}
    events, coverage, _ = select_events(p, thresholds)
    assert all(12 <= e["start"] < len(p) - 19 for e in events)
    assert all(e["t"] < len(p) - 19 for e in events)
    # The initial power jump has no full preceding 60-second window and is excluded.
    assert all(e["start"] >= 12 for e in events)
    assert any(e["thermal"] for e in events)
    p[:, 0, 3] = 0
    p[23:, 0, 3] = -2
    events, _, _ = select_events(p, thresholds)
    assert all(not e["thermal"] for e in events)


def test_joint_events_merge_within_180_seconds_and_require_distinct_hosts():
    groups = np.array(["A", "A", "A", "B"])
    events = [
        {"t": 20, "host": 0}, {"t": 38, "host": 0},
        {"t": 39, "host": 1}, {"t": 57, "host": 2},
        {"t": 20, "host": 3},
    ]
    assert joint_events(events, groups) == [
        {"group": "A", "start": 20, "end": 57, "hosts": [0, 1, 2]},
    ]


def test_reaction_window_and_aggregate_categories_are_independent_of_labels():
    binary = np.zeros((50, 288), bool)
    scores = np.arange(50 * 288, dtype=float).reshape(50, 288)
    groups = np.repeat(np.arange(16), 18)
    binary[20, 0] = True
    binary[38, 1] = True
    event = {"t": 20, "host": 0, "direction": "drop", "thermal": True}
    row = reaction([event], binary, scores, groups)[0]
    assert row["detected"] is True
    assert row["latency_seconds"] == 0
    assert row["pre_score"] == pytest.approx(scores[8:15, 0].mean())
    assert row["max_group_hosts"] == 1
    assert row["max_cluster_hosts"] == 1
    assert row["max_active_groups"] == 1
    assert row["persists_at_180s"] is False
    events = [event, {"t": 29, "host": 1, "direction": "rise", "thermal": False}]
    rows = [row, dict(row, detected=False, latency_seconds=None)]
    aggregate = aggregate_reactions(events, rows)
    assert aggregate["all"]["events"] == 2
    assert aggregate["all"]["detected"] == 1
    assert aggregate["drop"]["events"] == 1
    assert aggregate["rise"]["events"] == 1
    assert aggregate["thermal"]["events"] == 1


def test_reaction_reports_negative_latency_and_run_crossing_window():
    binary = np.zeros((60, 288), bool)
    scores = np.ones((60, 288), float)
    groups = np.repeat(np.arange(16), 18)
    binary[19:25, 0] = True  # event at 20; signal precedes it and run crosses window start
    binary[38, 0] = True
    row = reaction([{"t": 20, "host": 0}], binary, scores, groups)[0]
    assert row["latency_seconds"] == -10
    assert row["max_signal_run_seconds"] == 60
