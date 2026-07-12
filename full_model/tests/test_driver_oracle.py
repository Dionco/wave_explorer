import numpy as np
from pathlib import Path
from astropy.io import fits
from wave_explorer.full_model.driver import compute_full_model

REF = Path("/net/vdesk/data2/cobelens/MRP/new/obs-data-example/"
           "06_retrievals/gl_382/output_gl_382_v2")


def test_full_model_matches_fit_in_fitted_windows(tmp_path):
    out = tmp_path / "model-full.fits"
    compute_full_model(REF, out_path=out)

    with fits.open(REF / "fit-data.fits") as h:
        wvl_win = np.asarray(h["WVL"].data).reshape(-1)
        fit_win = np.asarray(h["FIT"].data).reshape(-1)
        idx = np.asarray(h["FLUXFIT"].data).reshape(-1)   # NaN outside fitted pixels
    with fits.open(out) as h:
        wvl_full = np.asarray(h["WVL"].data).reshape(-1)
        fit_full = np.asarray(h["FIT"].data).reshape(-1)

    # interpolate full-range model onto the fitted-window wavelengths
    order = np.argsort(wvl_full)
    fit_full_i = np.interp(wvl_win, wvl_full[order], fit_full[order])

    mask = np.isfinite(fit_win) & np.isfinite(idx) & np.isfinite(fit_full_i)
    diff = np.abs(fit_full_i[mask] - fit_win[mask])
    # continuum/broadening path must agree with what was actually fitted
    assert np.nanmedian(diff) < 0.01
    assert np.nanpercentile(diff, 95) < 0.03
