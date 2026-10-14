"""Contract tests for the standalone diagnostics statistics helpers."""
from itertools import permutations
from pathlib import Path
import sys

import numpy as np
import pytest


# Make the diagnostics module importable when pytest is launched from the repo
# root, without relying on an installed package layout.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import diagnostic_stats as stats  # noqa: E402


def test_average_ranks_are_one_based_and_average_ties():
    assert stats.average_ranks([40, 10, 10, 30]).tolist() == [4.0, 1.5, 1.5, 3.0]
    assert stats.average_ranks([7, 7, 7]).tolist() == [2.0, 2.0, 2.0]


@pytest.mark.parametrize("values", [[], [[1, 2]], [1, np.nan], [np.inf]])
def test_average_ranks_rejects_invalid_vectors(values):
    with pytest.raises(ValueError):
        stats.average_ranks(values)


def test_pearson_returns_none_for_either_constant_vector():
    assert stats.pearson([2, 2, 2], [1, 3, 9]) is None
    assert stats.pearson([1, 3, 9], [5, 5, 5]) is None
    assert stats.pearson([1, 2, 3], [3, 2, 1]) == pytest.approx(-1.0)


@pytest.mark.parametrize(
    "x,y", [([], []), ([1, 2], [1]), ([[1, 2]], [[1, 2]]), ([1, np.inf], [1, 2])]
)
def test_pearson_rejects_unpaired_or_nonfinite_vectors(x, y):
    with pytest.raises(ValueError):
        stats.pearson(x, y)


def test_pr_curve_processes_equal_scores_as_whole_blocks_and_step_weights_ap():
    # At threshold 0.8 the complete tied block has one positive and one
    # negative. AP is the block's recall increment times its endpoint
    # precision; trapezoidal interpolation would give a different area.
    result = stats.pr_curve([0.9, 0.8, 0.8, 0.1], [True, True, False, False])
    assert result["thresholds"].tolist() == [0.9, 0.8, 0.1]
    assert result["precision"].tolist() == pytest.approx([1.0, 1.0, 2 / 3, 1 / 2])
    assert result["recall"].tolist() == pytest.approx([0.0, 0.5, 1.0, 1.0])
    assert result["average_precision"] == pytest.approx(5 / 6)
    assert result["trapezoidal_pr_area"] != pytest.approx(result["average_precision"])


def test_pr_curve_is_permutation_invariant_with_tied_scores():
    scores = [0.6, 0.6, 0.2, 0.2, 0.9]
    labels = [True, False, True, False, False]
    baseline = stats.pr_curve(scores, labels)
    for order in permutations(range(len(scores))):
        result = stats.pr_curve(np.asarray(scores)[list(order)], np.asarray(labels)[list(order)])
        for key in ("thresholds", "precision", "recall"):
            np.testing.assert_allclose(result[key], baseline[key])
        assert result["average_precision"] == pytest.approx(baseline["average_precision"])


def test_pr_curve_has_defined_no_positive_behavior_and_rejects_bad_inputs():
    result = stats.pr_curve([0.3, 0.1], [False, False])
    assert result["average_precision"] is None
    assert result["trapezoidal_pr_area"] is None
    assert result["prevalence"] == 0
    for scores, labels in [([], []), ([1, 2], [True]), ([np.nan], [False])]:
        with pytest.raises(ValueError):
            stats.pr_curve(scores, labels)


@pytest.mark.parametrize(
    "mask,expected",
    [
        ([False, True, True, False, True], [(1, 3), (4, 5)]),
        ([True, True, False, False], [(0, 2)]),
        ([False, False, True, True], [(2, 4)]),
        ([True, False, False, True], [(0, 1), (3, 4)]),
        ([False, False, False], []),
    ],
)
def test_linear_runs_are_half_open_linear_and_do_not_wrap(mask, expected):
    assert stats.linear_runs(mask) == expected


def test_linear_runs_rejects_non_vector_input():
    with pytest.raises(ValueError):
        stats.linear_runs([[True, False]])


def test_coincidence_metrics_match_small_hand_counted_example():
    # One group, four hosts. Pair counts per time bin are 1, 3, 0, 1, 0;
    # qualifying-bin counts are 2, 3, 1, 2, 0, so the longest run is 2.
    binary = np.array(
        [
            [[1, 1, 0, 0]],
            [[1, 1, 1, 0]],
            [[1, 0, 0, 0]],
            [[0, 1, 1, 0]],
            [[0, 0, 0, 0]],
        ],
        dtype=bool,
    )
    np.testing.assert_array_equal(stats.coincidence_metrics(binary), [[5, 3, 1, 2]])


def test_coincidence_metrics_longest_run_is_linear_and_duration_is_bin_count():
    # Coincidences at the first and last bins remain separate runs.
    binary = np.array([[[1, 1]], [[1, 0]], [[0, 0]], [[1, 1]]], dtype=bool)
    np.testing.assert_array_equal(stats.coincidence_metrics(binary), [[2, 2, 0, 1]])
    # Three consecutive qualifying bins have duration three, not two gaps.
    consecutive = np.ones((3, 1, 2), dtype=bool)
    np.testing.assert_array_equal(stats.coincidence_metrics(consecutive), [[3, 3, 0, 3]])


@pytest.mark.parametrize("binary", [np.zeros((0, 1, 1)), np.zeros((2, 0, 1)), np.zeros((2, 1, 0)), np.zeros((2, 1))])
def test_coincidence_metrics_rejects_empty_or_wrong_rank_arrays(binary):
    with pytest.raises(ValueError):
        stats.coincidence_metrics(binary)


def test_circular_shift_preserves_each_host_count_and_circular_autocorrelation():
    binary = np.zeros((7, 1, 2), dtype=bool)
    binary[[0, 2, 5], 0, 0] = True
    binary[[1, 4], 0, 1] = True
    offsets = np.array([[3, -2]])
    shifted = stats.circular_shift(binary, offsets)
    np.testing.assert_array_equal(shifted.sum(axis=0), binary.sum(axis=0))
    for host in range(binary.shape[2]):
        original = binary[:, 0, host]
        moved = shifted[:, 0, host]
        for lag in range(binary.shape[0]):
            assert np.dot(original, np.roll(original, lag)) == np.dot(moved, np.roll(moved, lag))


def test_circular_shift_can_break_synchronous_pulses_and_accepts_wrapped_offsets():
    synchronous = np.zeros((8, 1, 2), dtype=bool)
    synchronous[[1, 5], 0, :] = True
    shifted = stats.circular_shift(synchronous, np.array([[0, 1_000_000_000_001]]))
    assert shifted[:, 0, 0].sum() == shifted[:, 0, 1].sum() == 2
    assert stats.coincidence_metrics(synchronous)[0, 0] == 2
    assert stats.coincidence_metrics(shifted)[0, 0] < 2


@pytest.mark.parametrize(
    "binary,offsets",
    [
        (np.zeros((0, 1, 1)), np.zeros((1, 1), dtype=int)),
        (np.zeros((2, 1, 1)), np.zeros((1, 1), dtype=float)),
        (np.zeros((2, 1, 1)), np.zeros((1,), dtype=int)),
        (np.zeros((2, 1)), np.zeros((1, 1), dtype=int)),
    ],
)
def test_circular_shift_rejects_invalid_shape_or_offsets(binary, offsets):
    with pytest.raises(ValueError):
        stats.circular_shift(binary, offsets)


def test_shift_control_repeats_exactly_for_seed_and_changes_for_relevant_seed():
    binary = np.zeros((12, 1, 3), dtype=bool)
    binary[[0, 4, 8], 0, :] = True
    first = stats.shift_control(binary, repeats=20, seed=12)
    np.testing.assert_array_equal(first, stats.shift_control(binary, repeats=20, seed=12))
    assert not np.array_equal(first, stats.shift_control(binary, repeats=20, seed=13))
    assert first.shape == (20, 1, 4)


@pytest.mark.parametrize("binary,repeats", [(np.zeros((0, 1, 1)), 1), (np.zeros((2, 1, 1)), 0), (np.zeros((2, 1)), 1)])
def test_shift_control_rejects_empty_series_or_invalid_repeat_count(binary, repeats):
    with pytest.raises(ValueError):
        stats.shift_control(binary, repeats, seed=0)


def test_empirical_tail_uses_plus_one_correction_and_counts_equalities():
    result = stats.empirical_tail(actual=3, controls=[3, 2, 3, 1])
    assert result["p_greater_equal"] == pytest.approx(3 / 5)
    assert result["repeats"] == 4
    assert stats.empirical_tail(actual=10, controls=[1, 2, 3])["p_greater_equal"] == pytest.approx(1 / 4)
    assert stats.empirical_tail(actual=0, controls=[0, 0])["p_greater_equal"] == 1


def test_empirical_tail_reports_control_interval_and_zero_mean_ratio():
    values = [0, 1, 2, 3, 4]
    result = stats.empirical_tail(actual=2, controls=values)
    assert result["control_interval_95"] == pytest.approx(np.quantile(values, [0.025, 0.975]).tolist())
    assert result["effect_difference"] == pytest.approx(0)
    zero = stats.empirical_tail(actual=2, controls=[0, 0])
    assert zero["control_mean"] == 0
    assert zero["effect_ratio"] is None


@pytest.mark.parametrize("actual,controls", [(1, []), (np.nan, [1]), (1, [1, np.inf]), (np.inf, [1])])
def test_empirical_tail_rejects_empty_or_nonfinite_values(actual, controls):
    with pytest.raises(ValueError):
        stats.empirical_tail(actual, controls)


def test_holm_adjustment_matches_known_values_and_is_permutation_equivariant():
    pvalues = [0.01, 0.04, 0.03]
    expected = np.array([0.03, 0.06, 0.06])
    np.testing.assert_allclose(stats.holm(pvalues), expected)
    order = [2, 0, 1]
    permuted = stats.holm(np.asarray(pvalues)[order])
    np.testing.assert_allclose(permuted, expected[order])
    np.testing.assert_allclose(stats.holm([0.0, 0.5, 1.0]), [0.0, 1.0, 1.0])


@pytest.mark.parametrize("pvalues", [[], [[0.1]], [-0.1], [1.1], [np.nan], [np.inf]])
def test_holm_rejects_invalid_pvalues(pvalues):
    with pytest.raises(ValueError):
        stats.holm(pvalues)
