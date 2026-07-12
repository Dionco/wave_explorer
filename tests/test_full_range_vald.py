"""Full-range VALD payload for the single-star view.

Regression for the bug where focusing a star (full-range model) kept the
mean-view VALD payload, which is filtered to the fitted line-list windows —
so VALD lines OUTSIDE the fitted windows disappeared. The single-star VALD
payload must cover the star's full observed range, not just the windows.
"""
import numpy as np

from wave_explorer.data_processing import build_single_star_vald_payload
from wave_explorer.vald import build_vald_payload


def _vald_entries():
    # Lines spread across the full range; 650 and 990 sit OUTSIDE a typical
    # fitted-window band (~743-981 nm); 760 and 850 sit inside it.
    return [
        {"element": "Fe", "ion": 1, "wavelength_nm": 650.0,
         "excit_ev": 4.1, "log_gf": -1.5, "central_depth": 0.30},
        {"element": "Ca", "ion": 2, "wavelength_nm": 760.0,
         "excit_ev": 3.0, "log_gf": 0.5, "central_depth": 0.25},
        {"element": "Ti", "ion": 1, "wavelength_nm": 850.0,
         "excit_ev": 1.0, "log_gf": -0.3, "central_depth": 0.20},
        {"element": "Si", "ion": 1, "wavelength_nm": 990.0,
         "excit_ev": 5.0, "log_gf": -0.8, "central_depth": 0.15},
    ]


def _full_range_payload():
    # A single-star payload covering 600-1000 nm with continuous sampling.
    w = np.arange(600.0, 1000.0, 0.02)
    return {
        "wavelengths": [float(x) for x in w],
        "lambdaMin": float(w[0]),
        "lambdaMax": float(w[-1]),
    }


def test_includes_lines_outside_fitted_windows():
    payload = _full_range_payload()
    p = build_single_star_vald_payload(payload, _vald_entries())
    wl = p["wavelengths"]
    # All four lines, including the ones outside the fitted-window band.
    assert 650.0 in wl
    assert 990.0 in wl
    assert p["count"] == 4

    # Contrast: the windowed mean build would drop the out-of-window lines.
    windowed = build_vald_payload(
        _vald_entries(), lambda_min=743.0, lambda_max=981.0
    )
    assert 650.0 not in windowed["wavelengths"]
    assert 990.0 not in windowed["wavelengths"]


def test_hides_lines_in_genuine_inter_order_gaps():
    # Two covered bands with a real gap between them; a VALD line in the gap
    # must still be hidden (no observation there).
    w = np.concatenate([
        np.arange(600.0, 700.0, 0.02),   # band 1
        np.arange(800.0, 1000.0, 0.02),  # band 2 (gap 700-800)
    ])
    payload = {
        "wavelengths": [float(x) for x in w],
        "lambdaMin": float(w[0]),
        "lambdaMax": float(w[-1]),
    }
    p = build_single_star_vald_payload(payload, _vald_entries())
    wl = p["wavelengths"]
    assert 650.0 in wl          # in band 1
    assert 850.0 in wl          # in band 2
    assert 990.0 in wl          # in band 2
    assert 760.0 not in wl      # in the 700-800 gap → hidden


def test_empty_entries_safe():
    p = build_single_star_vald_payload(_full_range_payload(), [])
    assert p["count"] == 0
