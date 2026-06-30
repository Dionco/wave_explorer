"""Unit test for export_demo.extract_fitpix — no FITS, no env needed."""
import numpy as np
from wave_explorer.scripts.export_demo import extract_fitpix
from wave_explorer.data_processing import compute_region_chi2_for_star


def _synthetic_fit_data():
    # 2 orders × 5 pixels. wvl in Angstrom (export divides by 10 -> nm).
    wvl = np.array([[12000., 12010., 12020., 12030., 12040.],
                    [12050., 12060., 12070., np.nan, 12090.]])
    flux_fit = np.array([[1.0, 1.1, 0.9, 1.0, 1.2],
                         [1.0, 0.8, 1.0, 1.0, 1.0]])
    fit = np.array([[1.0, 1.0, 1.0, 1.0, 1.0],
                    [1.0, 1.0, 1.0, 1.0, 1.0]])
    error = np.array([[0.1, 0.1, 0.0, 0.1, 0.1],   # pixel (0,2) has err=0 -> dropped
                      [0.1, 0.1, 0.1, 0.1, 0.1]])
    # idxtofit selects (order, pixel): mark pixels 1,2 of order 0 and 1,3 of order 1
    idxtofit = (np.array([0, 0, 1, 1]), np.array([1, 2, 1, 3]))
    return dict(wvl=wvl, flux_fit=flux_fit, fit=fit, error=error, idxtofit=idxtofit)


def test_extract_fitpix_matches_python_chi2():
    fd = _synthetic_fit_data()
    fp = extract_fitpix(fd)
    # Order0 pix2 dropped (err=0); order1 pix3 dropped (wvl NaN). Survivors: (0,1),(1,1).
    assert fp["w"] == [1201.0, 1206.0]
    # χ² over the full survivor range must equal the Python reference.
    lo, hi = min(fp["w"]) - 1, max(fp["w"]) + 1
    js_like = sum(((ff - fm) / er) ** 2 for ff, fm, er in zip(fp["ff"], fp["fm"], fp["err"])) / len(fp["w"])
    ref_chi2, ref_n = compute_region_chi2_for_star(fd, lo, hi)
    assert ref_n == len(fp["w"]) == 2
    assert abs(js_like - ref_chi2) < 1e-9
