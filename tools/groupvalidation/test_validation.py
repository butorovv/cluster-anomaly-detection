"""Contract checks for research controls, not new production detector tests."""
import numpy as np
import pytest

from tools.groupvalidation.common import (candidates, fit_group, quantile, r_components,
    score_group, segments, validate_partition)
from tools.groupvalidation.experiments import match_control


def test_two_host_rule_and_different_channel_direction():
    u = np.zeros((4, 18, 5))
    u[0, 0, 0] = 10
    u[1, :2, 0] = 10
    u[2, 0, 0], u[2, 1, 1] = 10, 10
    u[3, 0, 0], u[3, 1, 0] = 10, -10
    score, channel, direction, witnesses = r_components(u, np.zeros((18, 5)), np.ones((18, 5)), 9)
    np.testing.assert_array_equal(score, [0, 10, 0, 0])
    assert witnesses[1].sum() == 2 and channel[1] == 0 and direction[1] == 1
    assert not witnesses[[0, 2, 3]].any()
    assert quantile(np.arange(100.)) == 98


def test_unknown_breaks_events_and_is_not_boolean_true():
    r, b = np.array([1, -1, 1, 0]), np.array([1, 1, 1, 1])
    c = candidates(r, b)
    np.testing.assert_array_equal(c, [1, -1, 1, 0])
    assert segments(c == 1) == [(0, 1), (2, 3)]
    with pytest.raises(ValueError):
        segments(c)


def test_partition_neither_duplicates_nor_drops_hosts():
    hosts = [f'h{i}' for i in range(288)]
    groups = [dict(id=f'p{g}', hosts=hosts[g*18:(g+1)*18]) for g in range(16)]
    validate_partition(groups, hosts)
    groups[1]['hosts'][0] = groups[0]['hosts'][0]
    with pytest.raises(ValueError):
        validate_partition(groups, hosts)


def test_rank_policy_and_missing_group():
    p = fit_group(np.ones((20, 18, 5)))
    assert p['effective_rank'] == 0 and p['b_q99'] is None
    x = np.ones((2, 18, 5)); x[1, 0] = np.nan
    scored = score_group(p, x)
    np.testing.assert_array_equal(scored['b'], [-1, -1])
    np.testing.assert_array_equal(scored['r'], [0, -1])


def test_control_matches_without_using_IF_or_event_data():
    c = np.zeros(1000, dtype=np.int8); c[500:502] = 1
    complete = np.ones(1000, dtype=bool)
    # Equal distances choose earlier, with a full 60s guard.
    assert match_control(c, complete, 500, 2) == 492
    complete[492] = False
    assert match_control(c, complete, 500, 2) == 508
    assert match_control(np.ones(20, dtype=np.int8), np.ones(20, bool), 0, 2) is None
