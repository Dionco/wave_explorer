"""Unit tests for the Teff-stack payload: fit masking + payload builder."""
import json
import math

import numpy as np

from wave_explorer.data_processing import (
    fitted_ranges_for_star,
    mask_to_ranges,
)


def synth_fit_data(n_pix=200, w0_nm=700.0, dw_nm=0.05,
                   fitted=((20, 60), (120, 160))):
    """One-order synthetic fit-data dict in the load_fit_data shape.

    ``wvl`` is in Å (load_fit_data convention; flatten divides by 10).
    ``fitted`` lists (start, stop) pixel slices marked in idxtofit.
    """
    w_nm = w0_nm + dw_nm * np.arange(n_pix)
    wvl = (w_nm * 10.0)[None, :]                       # (1, n_pix) Å
    flux = np.ones((1, n_pix))
    fit = np.full((1, n_pix), 0.98)
    if fitted:
        pix = np.concatenate([np.arange(a, b) for a, b in fitted])
    else:
        pix = np.array([], dtype=int)
    idxtofit = (np.zeros(pix.size, dtype=int), pix)
    return {
        "wvl": wvl,
        "flux": flux,
        "fit": fit,
        "flux_fit": flux.copy(),
        "error": np.full((1, n_pix), 0.01),
        "idxtofit": idxtofit,
    }


def test_fitted_ranges_cover_fitted_pixels_only():
    fd = synth_fit_data()
    ranges = fitted_ranges_for_star(fd)
    assert len(ranges) == 2
    # first fitted block: pixels 20..59 → 701.0 .. 702.95 nm
    lo, hi = ranges[0]
    assert math.isclose(lo, 701.0, abs_tol=1e-6)
    assert math.isclose(hi, 702.95, abs_tol=1e-6)


def test_fitted_ranges_empty_idxtofit():
    fd = synth_fit_data(fitted=())
    fd["idxtofit"] = (np.array([], dtype=int), np.array([], dtype=int))
    assert fitted_ranges_for_star(fd) == []


def test_mask_to_ranges_nans_outside():
    common_w = np.array([700.0, 701.5, 703.5, 706.5])
    y = np.array([1.0, 2.0, 3.0, 4.0])
    out = mask_to_ranges(y, common_w, [(701.0, 702.95)])
    assert np.isnan(out[0])
    assert out[1] == 2.0
    assert np.isnan(out[2]) and np.isnan(out[3])


from wave_explorer.data_processing import build_stacked_payload


def _stack_dataset():
    """Two synthetic stars with different Teff and different fitted pixels."""
    cool = synth_fit_data(fitted=((20, 60),))
    hot = synth_fit_data(fitted=((20, 60), (120, 160)))
    common_w = np.arange(700.0, 710.0, 0.05, dtype=np.float32)
    return {
        "common_w": common_w,
        "fit_data_cache": {"hot_star": hot, "cool_star": cool},
        "stack_teffs": {"cool_star": 3000.0, "hot_star": 4000.0},
        "ll_entries": [
            # inside both stars' first fitted block (701.0–702.95 nm)
            {"lower": 701.2, "upper": 701.8, "element": "Fe", "ion": "1",
             "center": 701.5},
            # inside hot star's second block only (706.0–707.95 nm)
            {"lower": 706.2, "upper": 706.8, "element": "Ti", "ion": "1",
             "center": 706.5},
        ],
        "ll_hover_stats": [],
        "region_summary": [],
    }


def test_stars_sorted_by_teff_with_offsets():
    p = build_stacked_payload(_stack_dataset(), offset_step=0.5)
    assert p["stacked"] is True
    slugs = [s["slug"] for s in p["stars"]]
    assert slugs == ["cool_star", "hot_star"]          # Teff ascending
    assert [s["offset"] for s in p["stars"]] == [0.0, 0.5]
    assert p["offsetStep"] == 0.5


def test_fit_spans_full_observed_range():
    # The model is shown on the ENTIRE observed range, not just the
    # star's fitted windows (region usage lives in the perStar table).
    p = build_stacked_payload(_stack_dataset(), offset_step=0.5)
    cool = p["stars"][0]
    w = p["wavelengths"]
    # inside cool star's only fitted block → fit present
    i_in = min(range(len(w)), key=lambda i: abs(w[i] - 702.0))
    assert cool["fitFlux"][i_in] is not None
    # inside the hot-only block → cool star's fit STILL present
    i_out = min(range(len(w)), key=lambda i: abs(w[i] - 707.0))
    assert cool["fitFlux"][i_out] is not None
    assert p["stars"][1]["fitFlux"][i_out] is not None


def test_per_star_region_matrix():
    p = build_stacked_payload(_stack_dataset(), offset_step=0.5)
    # region 0: both stars fit it
    per0 = p["regions"][0]["perStar"]
    assert len(per0) == 2
    assert per0[0]["npix"] > 0 and per0[1]["npix"] > 0
    assert per0[0]["chi2"] is not None
    # region 1: hot star only — cool star (index 0) has npix == 0
    per1 = p["regions"][1]["perStar"]
    assert per1[0]["npix"] == 0 and per1[0]["chi2"] is None
    assert per1[1]["npix"] > 0


def test_payload_is_strict_json():
    p = build_stacked_payload(_stack_dataset(), offset_step=0.5)
    s = json.dumps(p)          # would raise on actual NaN with allow_nan=False
    assert "NaN" not in s
    json.dumps(p, allow_nan=False)
