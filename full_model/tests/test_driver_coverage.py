"""Spec-compliance tests for the full-range driver (Fixes 1-3).

Fix 1: partial orders are recovered by trimming to the grid+finite-obs span,
       so the produced model-full.fits reaches down to ~grid_min (~4001 A) and
       a coverage summary is printed (no silent dropping).
Fix 2: FIT/FITNOMAG are NaN wherever the real FLUX is NaN (honest artifact).
Fix 3: FLUXFIT/IDXTOFIT are not present; WVL/FLUX/ERROR/FIT/FITNOMAG are.
"""
import numpy as np
from pathlib import Path
from astropy.io import fits

from wave_explorer.full_model.driver import compute_full_model, grid_wave_range
from wave_explorer.full_model.params import load_run_inputs

REF = Path("/net/vdesk/data2/cobelens/MRP/new/obs-data-example/"
           "06_retrievals/gl_382/output_gl_382_v2")


def _open(out):
    h = fits.open(out)
    return h


def test_partial_order_recovery_reaches_grid_min(tmp_path):
    """Fix 1: WVL minimum must be within a few A of grid_min (~4001), proving the
    blue-end partial order (order 4, trimmed to the grid edge) is recovered and no
    longer silently dropped."""
    out = tmp_path / "model-full.fits"
    compute_full_model(REF, out_path=out)

    ri = load_run_inputs(REF)
    gmin, _ = grid_wave_range(ri.path_to_grid)
    with fits.open(out) as h:
        wvl = np.asarray(h["WVL"].data)
    wmin = float(np.nanmin(wvl))
    # within a few A of grid_min; certainly NOT the old ~4089 A blue cut
    assert abs(wmin - gmin) < 5.0, f"WVL min {wmin} not near grid_min {gmin}"
    assert wmin < 4089.0


def test_fit_is_nan_wherever_flux_is_nan(tmp_path):
    """Fix 2: the durable artifact must never show a model where there is no obs.
    FIT and FITNOMAG must be NaN at every pixel where FLUX is NaN."""
    out = tmp_path / "model-full.fits"
    compute_full_model(REF, out_path=out)
    with fits.open(out) as h:
        flux = np.asarray(h["FLUX"].data)
        fit = np.asarray(h["FIT"].data)
        fitnomag = np.asarray(h["FITNOMAG"].data)
    flux_nan = ~np.isfinite(flux)
    # No finite FIT anywhere FLUX is NaN
    assert not np.any(np.isfinite(fit[flux_nan])), \
        "FIT has finite values where FLUX is NaN"
    assert not np.any(np.isfinite(fitnomag[flux_nan])), \
        "FITNOMAG has finite values where FLUX is NaN"


def test_hdu_layout_drops_fluxfit_idxtofit(tmp_path):
    """Fix 3: model-full.fits keeps WVL/FLUX/ERROR/FIT/FITNOMAG and drops the
    windowed FLUXFIT/IDXTOFIT (which cannot index full-order arrays)."""
    out = tmp_path / "model-full.fits"
    compute_full_model(REF, out_path=out)
    with fits.open(out) as h:
        names = {hdu.name for hdu in h}
    for need in ("WVL", "FLUX", "ERROR", "FIT", "FITNOMAG"):
        assert need in names, f"missing HDU {need}"
    assert "FLUXFIT" not in names, "FLUXFIT should be removed (windowed shape)"
    assert "IDXTOFIT" not in names, "IDXTOFIT should be removed (windowed shape)"


def test_coverage_summary_printed(tmp_path, capsys):
    """Fix 1: the CLI must print a clear coverage summary (kept/trimmed/dropped),
    never omit orders silently."""
    out = tmp_path / "model-full.fits"
    compute_full_model(REF, out_path=out)
    captured = capsys.readouterr()
    text = captured.out + captured.err
    low = text.lower()
    assert "kept" in low
    assert "dropped" in low
    assert "trimmed" in low
