"""Driver: rebuild the ASAP model over the full observed range and write it.

Reuses ASAP's unmodified ``gen_spec`` on a corner grid (only the bracketing
best-fit nodes) with regions = the (trimmed) echelle orders. Writes
``model-full.fits`` with the WVL/FLUX/ERROR/FIT/FITNOMAG HDUs over those orders.

Each of the 40 observed orders is trimmed to the contiguous span that is BOTH
inside the grid's wavelength coverage AND inside the order's finite-obs extent
(leading/trailing NaN trimmed). Orders with no usable overlap (entirely below the
grid's blue edge ~4001 A) are dropped; every kept/trimmed/dropped order is
reported in a coverage summary printed to stdout (the CLI is the user's only
feedback). The fitted regions are marked downstream via the line list, so the
windowed FLUXFIT/IDXTOFIT HDUs are intentionally NOT carried here.
"""
import os
import sys
import tempfile
from pathlib import Path

import numpy as np
import h5py
from astropy.io import fits

sys.path.insert(0, "/net/vdesk/data2/cobelens/MRP/new/asap")
from asap.SpectralAnalysis import SpectralAnalysis   # noqa: E402
import asap.analysis_tools as tls                    # noqa: E402

from .params import load_run_inputs
from .grid_corners import enumerate_nodes, select_corners, is_node_filename
from .corner_load import make_corner_grid_dir


def grid_wave_range(path_to_grid):
    """Vacuum [min, max] wavelength covered by the grid models. Read from any
    one node file (all share the same master wave solution)."""
    src = Path(path_to_grid)
    node = next(f for f in os.listdir(src) if is_node_filename(f))
    with h5py.File(src / node, "r") as h5f:
        w = h5f["wavelink"]["wave"][()] if "wavelink" in h5f.keys() else h5f["wave"][()]
    w = tls.convert_lambda_in_vacuum(w)
    return float(np.min(w)), float(np.max(w))


def _valid_span(w, f, grid_range):
    """Indices ``(lo, hi)`` of the contiguous span of order ``(w, f)`` that is
    BOTH inside ``grid_range`` AND inside the order's finite-obs extent (leading/
    trailing NaN flux trimmed). Returns ``None`` if there is no usable overlap.

    The span is the [first, last] index where ``w`` and ``f`` are finite and
    ``w`` is within the grid wavelength coverage; interior NaN runs (if any) stay
    inside the span and are handled by the guarded continuum fill."""
    finite = np.isfinite(w) & np.isfinite(f)
    if not finite.any():
        return None
    if grid_range is not None:
        gmin, gmax = grid_range
        finite = finite & (w >= gmin) & (w <= gmax)
    if not finite.any():
        return None
    idx = np.where(finite)[0]
    return int(idx[0]), int(idx[-1])


def build_full_order_regions(med, grid_range=None, min_pixels=50, verbose=True):
    """``load_obs`` returns 2D (n_orders, n_pix) arrays. For each order, build the
    full-order region from the contiguous span that is BOTH within the grid's
    wavelength coverage AND within the order's finite-obs extent (FIX 1).

    Instead of dropping a whole order when it only partly overlaps the grid, each
    order is *trimmed* to that valid sub-range. Orders whose valid span is
    non-trivial (>= ``min_pixels``) are kept; orders with no usable overlap
    (entirely below the grid's blue edge ~4001 A) are dropped. This recovers the
    ~4001 A blue end (order 4, trimmed to the grid edge) that the previous
    fully-inside-grid rule discarded.

    Kept orders are padded to a common width (the widest valid span) to keep the
    arrays rectangular; the padded tail of a short order carries NaN obs flux and
    a monotone wavelength continuation. ``obs_flux`` keeps the real observed flux
    (NaN where padded or at interior masked pixels) for the durable FITS;
    ``obs_flux_fit`` is a guarded copy whose NaN pixels are median-filled ONLY in
    windows that would otherwise be entirely NaN, so ASAP's per-order continuum
    fit (``adjust_continuum5``) never sees a fully-NaN sub-window (which would
    crash its numba percentile). ``compute_full_model`` then re-masks FIT/FITNOMAG
    to NaN wherever the real flux is NaN, so the artifact stays honest (FIX 2).

    Returns ``(obs_wvl, obs_flux, obs_flux_fit, obs_err, nan_mask, regions,
    summary)`` where ``summary`` is a human-readable coverage string."""
    med_wvl, med_flux, med_err, _radvel = med
    # FITS arrays come big-endian (>f8); cast to native float64 so numba-jitted
    # continuum routines (adjust_continuum5) accept them.
    med_wvl = np.ascontiguousarray(med_wvl, dtype=np.float64)
    med_flux = np.ascontiguousarray(med_flux, dtype=np.float64)
    med_err = np.ascontiguousarray(med_err, dtype=np.float64)

    kept = []          # (order, lo, hi)
    trimmed = []       # order indices trimmed to a grid/obs edge
    dropped = []       # (order, lo_wvl, hi_wvl) with no usable overlap
    n_orders = med_wvl.shape[0]
    for o in range(n_orders):
        w, f = med_wvl[o], med_flux[o]
        finite_w = w[np.isfinite(w)]
        span = _valid_span(w, f, grid_range)
        if span is None or (span[1] - span[0] + 1) < min_pixels:
            lo_wvl = float(finite_w[0]) if finite_w.size else float("nan")
            hi_wvl = float(finite_w[-1]) if finite_w.size else float("nan")
            dropped.append((o, lo_wvl, hi_wvl))
            continue
        lo, hi = span
        # An order is "trimmed" if its kept span does not cover the full finite
        # extent of the order (i.e. the grid or a NaN edge cut into it).
        ffin = np.where(np.isfinite(w) & np.isfinite(f))[0]
        if ffin.size and (lo > ffin[0] or hi < ffin[-1]):
            trimmed.append(o)
        kept.append((o, lo, hi))

    if not kept:
        raise RuntimeError("No order has usable grid overlap; cannot build model.")

    width = max(hi - lo + 1 for _, lo, hi in kept)
    n_keep = len(kept)
    obs_wvl = np.empty((n_keep, width), dtype=np.float64)
    obs_flux = np.full((n_keep, width), np.nan, dtype=np.float64)
    obs_err = np.full((n_keep, width), np.nan, dtype=np.float64)
    regions = np.empty((n_keep, 2), dtype=np.float64)

    for r, (o, lo, hi) in enumerate(kept):
        n = hi - lo + 1
        obs_wvl[r, :n] = med_wvl[o, lo:hi + 1]
        obs_flux[r, :n] = med_flux[o, lo:hi + 1]
        obs_err[r, :n] = med_err[o, lo:hi + 1]
        # Pad the tail wavelength with a monotone continuation so interpolation
        # stays well-ordered; flux/err padding stays NaN (no real obs there).
        if n < width:
            step = (obs_wvl[r, n - 1] - obs_wvl[r, 0]) / (n - 1) if n > 1 else 1.0
            obs_wvl[r, n:] = obs_wvl[r, n - 1] + (np.arange(1, width - n + 1) * step)
        regions[r] = [obs_wvl[r, 0], obs_wvl[r, n - 1]]

    # wvl must be finite & monotone for interpolation; fill any interior NaN wvl.
    obs_wvl = _fill_wvl_nan(obs_wvl)

    # Guarded continuum-fit copy: median-fill NaN flux ONLY where a continuum
    # sub-window would otherwise be entirely NaN (which crashes adjust_continuum5).
    obs_flux_fit = _guarded_continuum_fill(obs_flux)

    nan_mask = np.ones_like(obs_flux_fit)
    summary = _coverage_summary(kept, trimmed, dropped, med_wvl, n_orders)
    if verbose:
        print(summary)
    return obs_wvl, obs_flux, obs_flux_fit, obs_err, nan_mask, regions, summary


# adjust_continuum5 splits each order into this many windows; a window that is
# entirely NaN in the obs flux crashes its percentile (assert high>low). Match
# the core value so the guarded fill targets exactly those windows.
_N_CONT_WINDOWS = 6


def _guarded_continuum_fill(obs_flux):
    """Return a copy of ``obs_flux`` with NaN pixels median-filled ONLY inside
    continuum windows that are otherwise entirely NaN. Windows that already hold
    real obs are left untouched, so the continuum fit sees real data wherever it
    exists; the result is fed to ``gen_spec`` for the continuum pass only and the
    durable FIT is re-masked to NaN where the real flux is NaN."""
    out = np.array(obs_flux, copy=True)
    n_pix = out.shape[1]
    # adjust_continuum5 truncates to floor(len/10)*10, then splits into 6 windows.
    eff_len = int(np.floor(n_pix / 10) * 10)
    size = max(eff_len // _N_CONT_WINDOWS, 1)
    for r in range(out.shape[0]):
        row = out[r]
        med_val = np.nanmedian(row)
        fill = med_val if np.isfinite(med_val) else 1.0
        for j in range(_N_CONT_WINDOWS):
            i = j * size
            seg = row[i:i + size]
            if seg.size and not np.any(np.isfinite(seg)):
                row[i:i + size] = fill
        # Also guard the truncated tail (pixels beyond eff_len) so the array has
        # no all-NaN run that a later resample could trip over.
        tail = row[eff_len:]
        if tail.size and not np.any(np.isfinite(tail)):
            row[eff_len:] = fill
    return out


def _coverage_summary(kept, trimmed, dropped, med_wvl, n_orders):
    """Build the human-readable coverage summary (no silent omission)."""
    kept_orders = [o for o, _, _ in kept]
    los = [med_wvl[o, lo] for o, lo, hi in kept]
    his = [med_wvl[o, hi] for o, lo, hi in kept]
    wmin, wmax = float(min(los)), float(max(his))
    lines = []
    lines.append(
        "coverage: kept {n} orders ({lo:.1f}-{hi:.1f} A); "
        "trimmed {t} orders to grid/obs edge; dropped {d} orders "
        "(no grid overlap)".format(
            n=len(kept), lo=wmin, hi=wmax, t=len(trimmed), d=len(dropped)))
    lines.append("  kept orders:    " + ", ".join(str(o) for o in kept_orders))
    if trimmed:
        tparts = []
        for o, lo, hi in kept:
            if o in trimmed:
                tparts.append("{o} ({lo:.1f}-{hi:.1f} A)".format(
                    o=o, lo=med_wvl[o, lo], hi=med_wvl[o, hi]))
        lines.append("  trimmed orders: " + ", ".join(tparts))
    else:
        lines.append("  trimmed orders: none")
    if dropped:
        dparts = ["{o} ({lo:.1f}-{hi:.1f} A)".format(o=o, lo=lo, hi=hi)
                  for o, lo, hi in dropped]
        lines.append("  dropped orders: " + ", ".join(dparts))
    else:
        lines.append("  dropped orders: none")
    return "\n".join(lines)


def _fill_wvl_nan(obs_wvl):
    """Replace NaN wavelengths (masked order edges) with a linear continuation
    of the order's finite wavelength step so interpolation stays monotone."""
    out = np.array(obs_wvl, copy=True)
    for r in range(out.shape[0]):
        w = out[r]
        good = np.isfinite(w)
        if good.all() or not good.any():
            continue
        idx = np.arange(w.size)
        gi = idx[good]
        # average step from the finite part
        step = (w[gi[-1]] - w[gi[0]]) / (gi[-1] - gi[0]) if gi[-1] > gi[0] else 1.0
        w0 = w[gi[0]]
        out[r] = w0 + (idx - gi[0]) * step
    return out


def _write_model_fits(out_path, output_folder, obs_wvl, obs_flux, obs_err,
                      fit, fitnomag, normfac):
    """Write the full-range model FITS: WVL/FLUX/ERROR/FIT/FITNOMAG only.

    FIX 3: the windowed FLUXFIT/IDXTOFIT (shape ~(17,1287)) from the run's
    fit-data.fits cannot index these full-order arrays (~(36,6642)), so they are
    intentionally dropped. The full-range view marks fitted regions via the line
    list in the app, not via these HDUs (noted in the PRIMARY header)."""
    hdu = fits.PrimaryHDU()
    hdu.header["OBJECT"] = (str(Path(output_folder).parent.name), "object observed")
    hdu.header["NORMFAC"] = (normfac, "normalization factor")
    hdu.header["FULLRNG"] = (True, "full observed-range model (model-full.fits)")
    hdu.header["FITMARK"] = ("linelist", "fitted regions marked via line list")
    hdul = fits.HDUList([
        hdu,
        fits.ImageHDU(data=np.asarray(obs_wvl), name="WVL"),
        fits.ImageHDU(data=np.asarray(obs_flux), name="FLUX"),
        fits.ImageHDU(data=np.asarray(obs_err), name="ERROR"),
        fits.ImageHDU(data=np.asarray(fit), name="FIT"),
        fits.ImageHDU(data=np.asarray(fitnomag), name="FITNOMAG"),
    ])
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    hdul.writeto(out_path, overwrite=True)


def compute_full_model(output_folder, out_path=None, grid_path_override=None) -> Path:
    output_folder = Path(output_folder)
    out_path = Path(out_path) if out_path else output_folder / "model-full.fits"
    ri = load_run_inputs(output_folder, grid_path_override=grid_path_override)

    SA = SpectralAnalysis()
    SA.read_config(str(ri.config_path), safe=False)   # safe=False: stale cfg grid path
    SA.star = ri.star
    med = SA.load_obs(ri.obs_fits)
    grange = grid_wave_range(ri.path_to_grid)
    (obs_wvl, obs_flux, obs_flux_fit, obs_err,
     nan_mask, regions, _summary) = build_full_order_regions(med, grid_range=grange)

    nodes = enumerate_nodes(ri.path_to_grid)
    sel = select_corners(nodes, ri.teff, ri.logg, ri.mh, ri.afe)
    # ASAP sizes its grid arrays from self.regions (d6 = len(self.regions)).
    # We bypass create_regions, so set the full-order regions explicitly first.
    SA.regions = regions
    SA.get_grid_dims()
    with tempfile.TemporaryDirectory() as tmp:
        corner_dir = make_corner_grid_dir(ri.path_to_grid, sel, tmp)
        SA.load_grid(corner_dir, regions)             # ASAP builds grid_n/nwvls
        SA.get_grid_dims()

        coeffs = np.asarray(ri.mag_ff, dtype=float)
        # gen_spec uses obs_flux only for the per-order continuum adjustment, so
        # pass the NaN-filled obs (obs_flux_fit); the returned model is on obs_wvl.
        # positional tail matches gen_spec(...): vb=None, rv, vsini, vmac
        fit = SA.gen_spec(obs_wvl, obs_flux_fit, obs_err, nan_mask, SA.nwvls, SA.grid_n,
                          coeffs, ri.teff, ri.logg, ri.mh, ri.afe,
                          SA.teffs, SA.loggs, SA.mhs, SA.alphas,
                          None, ri.rv, ri.vsini, ri.vmac)
        coeffs0 = np.zeros_like(coeffs)
        coeffs0[0] = 1
        fitnomag = SA.gen_spec(obs_wvl, obs_flux_fit, obs_err, nan_mask, SA.nwvls, SA.grid_n,
                               coeffs0, ri.teff, ri.logg, ri.mh, ri.afe,
                               SA.teffs, SA.loggs, SA.mhs, SA.alphas,
                               None, ri.rv, ri.vsini, ri.vmac)

    normfac = float(getattr(SA, "normFactor", 1.0) or 1.0)

    # FIX 2: the continuum pass may have used a guarded median-fill for all-NaN
    # windows; re-mask FIT/FITNOMAG to NaN wherever the REAL obs flux is NaN, so
    # the durable artifact never shows a mis-scaled model where there is no obs.
    fit = np.asarray(fit, dtype=np.float64)
    fitnomag = np.asarray(fitnomag, dtype=np.float64)
    flux_nan = ~np.isfinite(obs_flux)
    fit[flux_nan] = np.nan
    fitnomag[flux_nan] = np.nan

    _write_model_fits(out_path, output_folder, obs_wvl, obs_flux, obs_err,
                      fit, fitnomag, normfac)
    return out_path
