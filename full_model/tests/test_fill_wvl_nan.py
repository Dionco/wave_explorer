"""Unit tests for driver._fill_wvl_nan (F10).

The old implementation replaced the ENTIRE order row with a linear ramp when
any NaN was present, overwriting genuine finite wavelengths. The fix fills
ONLY the NaN positions: interior NaN via np.interp between finite neighbours,
leading/trailing NaN extrapolated linearly with the local edge step. Rows with
fewer than 2 finite points keep the previous behaviour.
"""
import numpy as np

from wave_explorer.full_model.driver import _fill_wvl_nan


def test_finite_values_kept_verbatim():
    # Non-uniform finite samples: the old whole-row ramp would move 20.5→20.0.
    w = np.array([[10.0, 20.5, np.nan, 40.0]])
    out = _fill_wvl_nan(w)
    assert out[0, 0] == 10.0
    assert out[0, 1] == 20.5
    assert out[0, 3] == 40.0
    # interior NaN interpolated between its finite neighbours (20.5 and 40.0)
    assert np.isclose(out[0, 2], 20.5 + (40.0 - 20.5) / 2)


def test_interior_nan_interpolated():
    w = np.array([[1.0, 2.0, np.nan, 4.0, 5.0]])
    out = _fill_wvl_nan(w)
    assert np.allclose(out[0], [1.0, 2.0, 3.0, 4.0, 5.0])


def test_edges_extrapolated_with_local_step():
    w = np.array([[np.nan, 2.0, 3.0, 4.0, np.nan, np.nan]])
    out = _fill_wvl_nan(w)
    # leading NaN: local step at the blue edge is 1.0 → 2.0 - 1 = 1.0
    # trailing NaN: local step at the red edge is 1.0 → 4.0 + 1, + 2
    assert np.allclose(out[0], [1.0, 2.0, 3.0, 4.0, 5.0, 6.0])
    assert np.all(np.diff(out[0]) > 0), "filled row must stay monotone"


def test_single_finite_point_keeps_unit_step_ramp():
    w = np.array([[np.nan, 5.0, np.nan]])
    out = _fill_wvl_nan(w)
    assert np.allclose(out[0], [4.0, 5.0, 6.0])


def test_all_finite_row_untouched():
    w = np.array([[1.0, 2.5, 3.0]])
    out = _fill_wvl_nan(w)
    assert np.array_equal(out, w)


def test_all_nan_row_untouched():
    w = np.full((1, 4), np.nan)
    out = _fill_wvl_nan(w)
    assert np.all(np.isnan(out))


def test_input_not_mutated():
    w = np.array([[1.0, np.nan, 3.0]])
    w_copy = w.copy()
    _fill_wvl_nan(w)
    assert np.array_equal(np.isnan(w), np.isnan(w_copy))
    assert np.array_equal(w[np.isfinite(w)], w_copy[np.isfinite(w_copy)])
