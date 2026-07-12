"""Unit test for build_single_star_payload — the single-star full-range payload.

The fake ``fit_data`` carries only ``wvl/flux/fit`` (the keys
``flatten_full_spectrum`` consumes); the real ``model-full.fits`` has no
``flux_fit`` HDU, so the payload builder must not require it.
"""
import numpy as np

from wave_explorer.data_processing import build_single_star_payload


def test_single_star_payload_keys_and_domain():
    fd = {
        "wvl": np.array([[5150.0, 5151.0, 5152.0, 5153.0]]),  # Angstrom
        "flux": np.array([[1.0, 0.8, 0.9, 1.0]]),
        "fit": np.array([[1.0, 0.82, 0.88, 1.0]]),
    }
    base = {"ll_entries": [], "ll_hover_stats": [], "region_summary": []}
    p = build_single_star_payload(fd, base)
    # Angstrom -> nm conversion (flatten_full_spectrum divides by 10)
    assert p["wavelengths"][0] == 515.0 and p["wavelengths"][-1] == 515.3
    assert p["flux"] == [1.0, 0.8, 0.9, 1.0]
    assert p["fitFlux"] == [1.0, 0.82, 0.88, 1.0]
    assert p["resid"][1] == round(0.8 - 0.82, 6)
    assert p["lambdaMin"] == 515.0 and p["lambdaMax"] == 515.3
    assert "regions" in p
