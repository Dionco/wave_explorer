"""Unit test for build_spectrum_payload — the spectrum-data-store builder."""
import json
import math

from wave_explorer.data_processing import build_spectrum_payload


def _fake_dataset():
    """Minimal dataset dict with the fields build_spectrum_payload reads."""
    return {
        "common_w": [515.0, 515.5, 516.0, 516.5],
        "mean_obs_s": [1.0, 0.8, 0.9, 1.0],
        "mean_fit_s": [1.0, 0.82, 0.88, 1.0],
        "mean_resid_s": [0.0, -0.02, 0.02, 0.0],
        "ll_entries": [
            {"lower": 515.1, "upper": 515.3, "element": "Fe", "ion": "1"},
            {"lower": 515.8, "upper": 516.1, "element": "Mg", "ion": "2"},
        ],
        "ll_hover_stats": [
            {"region_idx": 1, "n_stars": 30, "med_npix": 6},
            {"region_idx": 2, "n_stars": 25, "med_npix": 5},
        ],
        "region_summary": [
            {"region_idx": 0, "med_chi2": 3.2},
            {"region_idx": 1, "med_chi2": float("nan")},
        ],
    }


def test_payload_has_arrays_and_bounds():
    p = build_spectrum_payload(_fake_dataset())
    assert p["wavelengths"] == [515.0, 515.5, 516.0, 516.5]
    assert p["flux"] == [1.0, 0.8, 0.9, 1.0]
    assert p["fitFlux"] == [1.0, 0.82, 0.88, 1.0]
    assert p["resid"] == [0.0, -0.02, 0.02, 0.0]
    assert p["lambdaMin"] == 515.0
    assert p["lambdaMax"] == 516.5


def test_payload_regions_carry_chi2_and_stats():
    p = build_spectrum_payload(_fake_dataset())
    assert len(p["regions"]) == 2
    r0, r1 = p["regions"]
    assert r0 == {"idx": 0, "chi2": 3.2, "n_stars": 30, "n_pix": 6}
    # region_summary has no entry keyed 1 with a finite chi2 -> None
    assert r1["idx"] == 1 and r1["chi2"] is None
    assert r1["n_stars"] == 25 and r1["n_pix"] == 5


def test_payload_thresholds_and_element_colors():
    p = build_spectrum_payload(_fake_dataset())
    assert p["chi2Thresholds"] == [5.0, 15.0, 30.0]
    assert p["elementColors"]["Fe"] == "#4a6c8a"
    assert p["elementColorFallback"] == "#75705f"


def test_payload_is_json_serializable():
    p = build_spectrum_payload(_fake_dataset())
    # Must round-trip cleanly — no numpy scalars, no NaN leaking as float.
    text = json.dumps(p, allow_nan=False)
    assert isinstance(text, str)
