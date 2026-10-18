"""Arithmetic checks for the checkpoint diagnostic, not detector contract tests."""
import numpy as np
import pytest

from tools.groupdiagnostics.d1 import host_channels, group_vectors, robust, covariance_diagnostics


def test_physical_channel_mapping_and_population_spread():
    f = np.zeros((2, 18, 18))
    f[..., :2] = 100
    f[..., 2:4] = 20
    f[..., 4:10] = 30
    f[..., 10:12] = 40
    f[..., 12:18] = 50
    u = host_channels(f)
    np.testing.assert_array_equal(u[0, 0], [180, 40, 200, 50, 40])
    u[1, :2, 0] += 18
    v = group_vectors(u)
    assert v[1, 0] == 182
    assert v[1, 5] == pytest.approx(18 * np.sqrt((2/18)*(16/18)))
    assert v[0, 5] == 0


def test_floor_preserves_zero_mad_without_claiming_sensor_resolution():
    median, mad, scale = robust(np.array([[1., 2.], [1., 3.], [1., 4.]]))
    np.testing.assert_array_equal(median, [1, 3])
    np.testing.assert_array_equal(mad, [0, 1])
    np.testing.assert_array_equal(scale, [1e-4, 1.4826])


def test_rank_deficient_is_unknown():
    v = np.tile(np.arange(30.)[:, None], (1, 10))
    d = covariance_diagnostics(v)
    assert d['effective_rank'] == 1
    assert d['status'] == 'unknown'
    assert d['q99_mahalanobis_squared'] is None
    zero = covariance_diagnostics(np.ones((20, 10)))
    assert zero['effective_rank'] == 0 and zero['status'] == 'unknown'
    assert zero['reconstruction_relative_frobenius'] == 0


def test_full_rank_quadratic_form_and_covariance():
    # Deterministic orthogonal columns, with known diagonal covariance.
    a = np.arange(32)[:, None]
    b = np.arange(1, 11)[None, :]
    v = np.cos(np.pi*(a + .5)*b/32)
    d = covariance_diagnostics(v)
    assert d['effective_rank'] == 10
    assert d['status'] == 'algebraically_usable'
    np.testing.assert_allclose(d['raw_covariance'], np.eye(10)*16/31, atol=1e-15)
    assert d['reconstruction_relative_frobenius'] < 1e-12


def test_missing_and_insufficient_training_are_unknown():
    assert covariance_diagnostics(np.zeros((10, 10)))['status'] == 'unknown'
    assert covariance_diagnostics(np.full((20, 10), np.nan))['status'] == 'unknown'
    with pytest.raises(ValueError):
        group_vectors(np.zeros((20, 17, 5)))
