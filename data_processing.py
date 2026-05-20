"""
ASAP Data Processing & Loading Layer
"""

import configparser
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np


try:
    from helper_functions.retrieval.retrieval_analysis import load_fit_data
except ImportError:
    import sys

    HERE = Path(__file__).resolve().parent.parent.parent / "code_vibing"
    sys.path.insert(0, str(HERE))
    from helper_functions.retrieval.retrieval_analysis import load_fit_data


# ══════════════════════════════════════════════════════════════════════════════
# Discovery & File I/O
# ══════════════════════════════════════════════════════════════════════════════


def discover_output_folders(retrievals_dir: Path, suffix: str) -> Dict[str, Path]:
    """Find output_*_<suffix> folders in retrievals_dir, keyed by parent folder name."""
    found: Dict[str, Path] = {}
    for star_dir in sorted(retrievals_dir.glob("*")):
        if not star_dir.is_dir():
            continue
        candidates = sorted(
            p
            for p in star_dir.glob("output_*")
            if p.is_dir() and p.name.endswith(f"_{suffix}")
        )
        if candidates:
            found[star_dir.name] = candidates[0]
    return found


def _parse_line_entry(raw_line: str) -> Optional[dict]:
    """Parse a single line-list row (commented or not).

    Returns a dict with keys:
        center, lower, upper, element, ion, order, inline_comment,
        excluded (True iff the source line was commented out)
    or None if the line is blank / a pure header comment / unparseable.
    """
    stripped = raw_line.strip()
    if not stripped:
        return None

    excluded_in_source = False
    payload = stripped
    if payload.startswith("#"):
        # Could be (a) a header/doc comment, or (b) a commented-out entry.
        payload = payload.lstrip("#").strip()
        if not payload:
            return None
        excluded_in_source = True

    data_part, _, inline = payload.partition("#")
    parts = data_part.split()
    if len(parts) < 3:
        return None
    try:
        center = float(parts[0])
        lower = float(parts[1])
        upper = float(parts[2])
    except ValueError:
        return None

    element = parts[3] if len(parts) > 3 else "Unknown"
    ion = parts[4] if len(parts) > 4 else "1"
    order = parts[5] if len(parts) > 5 else "0"
    inline_comment = inline.strip() if inline else ""

    return dict(
        center=center,
        lower=lower,
        upper=upper,
        element=element,
        ion=ion,
        order=order,
        inline_comment=inline_comment,
        excluded=excluded_in_source,
    )


def load_line_list(path: Path) -> List[dict]:
    """Load line list preserving commented-out entries as excluded regions.

    Each returned dict carries the original lower/upper and the source
    excluded flag so the curated save can compute diffs and preserve the
    full file fidelity (6-col format + inline comments).
    """
    entries: List[dict] = []
    with open(path) as fh:
        for raw in fh:
            parsed = _parse_line_entry(raw)
            if parsed is None:
                continue
            idx = len(entries)
            parsed["original_idx"] = idx
            parsed["original_lower"] = parsed["lower"]
            parsed["original_upper"] = parsed["upper"]
            parsed["original_excluded"] = parsed["excluded"]
            parsed["added"] = False
            entries.append(parsed)
    return entries


def _format_entry_line(e: dict) -> str:
    """Format a single entry as a fixed-width data row (without # prefix).

    Preserves the 6-column format: center lower upper element ion order.
    """
    lower = float(e["lower"])
    upper = float(e["upper"])
    center = float(e.get("center", 0.5 * (lower + upper)))
    element = str(e.get("element", "Unknown"))
    ion = str(e.get("ion", "1"))
    order = str(e.get("order", "0"))
    return (
        f"{center:<10.4f} {lower:<10.4f} {upper:<10.4f}"
        f" {element:<10s} {ion:<4s} {order}"
    )


def save_curated_line_list(
    dest_dir: Path,
    suffix: str,
    entries: List[dict],
    timestamp: Optional[str] = None,
) -> Path:
    """Write a curated line list to a NEW timestamped file.

    Does NOT overwrite the source file. Returns the resolved path.

    File layout:
      # header with counts
      # format comment
      <uncommented data rows, tagged if ADJUSTED/ADDED>
      <# prefixed excluded rows, tagged EXCLUDED>

    Entry fields consulted:
      center, lower, upper, element, ion, order, inline_comment,
      excluded, added, original_lower, original_upper, original_excluded
    """
    import os
    import tempfile
    from datetime import datetime

    ts = timestamp or datetime.now().strftime("%Y%m%d-%H%M%S")
    dest_dir = Path(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    out_path = dest_dir / f"line_list_{suffix}_curated_{ts}.txt"

    original_count = sum(
        1 for e in entries if not e.get("added", False) and not e.get(
            "original_excluded", False
        )
    )
    deleted_count = sum(
        1
        for e in entries
        if not e.get("added", False)
        and e.get("excluded", False)
        and not e.get("original_excluded", False)
    )
    modified_count = 0
    for e in entries:
        if e.get("added") or e.get("excluded"):
            continue
        o_lo = e.get("original_lower")
        o_hi = e.get("original_upper")
        if o_lo is None or o_hi is None:
            continue
        if abs(float(e["lower"]) - float(o_lo)) > 1e-6 or abs(
            float(e["upper"]) - float(o_hi)
        ) > 1e-6:
            modified_count += 1
    added_count = sum(
        1 for e in entries if e.get("added", False) and not e.get("excluded", False)
    )
    final_count = sum(1 for e in entries if not e.get("excluded", False))

    def _wlen_key(e):
        return float(e.get("center", 0.5 * (float(e["lower"]) + float(e["upper"]))))

    active = sorted(
        (e for e in entries if not e.get("excluded", False)), key=_wlen_key
    )
    excluded = sorted(
        (e for e in entries if e.get("excluded", False)), key=_wlen_key
    )

    with tempfile.NamedTemporaryFile(
        "w", dir=str(dest_dir), delete=False, suffix=".tmp"
    ) as fh:
        tmp_path = fh.name
        fh.write(f"# ASAP curated line list — suffix: {suffix} — {ts}\n")
        fh.write(
            f"# Original: {original_count} | Deleted: {deleted_count}"
            f" | Modified: {modified_count} | Added: {added_count}"
            f" | Final: {final_count}\n"
        )
        fh.write(
            "# Format: center_wvl(nm) lower_wvl(nm) upper_wvl(nm) element ion order\n"
        )

        for e in active:
            row = _format_entry_line(e)
            tags: List[str] = []
            if e.get("added"):
                tags.append("ADDED")
            else:
                if e.get("original_excluded", False):
                    tags.append("RESTORED")
                o_lo = e.get("original_lower")
                o_hi = e.get("original_upper")
                if o_lo is not None and o_hi is not None and (
                    abs(float(e["lower"]) - float(o_lo)) > 1e-6
                    or abs(float(e["upper"]) - float(o_hi)) > 1e-6
                ):
                    tags.append(
                        f"ADJUSTED (was: {float(o_lo):.4f} \u2013 {float(o_hi):.4f})"
                    )
            inline = e.get("inline_comment", "") or ""
            suffix_parts: List[str] = []
            if inline:
                suffix_parts.append(inline)
            suffix_parts.extend(tags)
            line_out = row
            if suffix_parts:
                line_out = line_out + "  # " + " | ".join(suffix_parts)
            fh.write(line_out + "\n")

        if excluded:
            fh.write("#\n# --- Excluded regions ---\n")
            for e in excluded:
                row = _format_entry_line(e)
                tags = ["EXCLUDED"]
                if not e.get("original_excluded", False) and not e.get("added", False):
                    tags.append("removed in session")
                inline = e.get("inline_comment", "") or ""
                suffix_parts = []
                if inline:
                    suffix_parts.append(inline)
                suffix_parts.extend(tags)
                fh.write(f"# {row}  # " + " | ".join(suffix_parts) + "\n")

    os.replace(tmp_path, str(out_path))
    return out_path


def save_line_list(path: Path, entries: List[dict]) -> None:
    """Deprecated: kept for backward compatibility with any external callers.

    Writes the ACTIVE (non-excluded) entries in the 6-column format to `path`.
    New code should use `save_curated_line_list` which never overwrites and
    carries full audit info.
    """
    import os
    import tempfile

    with tempfile.NamedTemporaryFile(
        "w", dir=str(path.parent), delete=False, suffix=".tmp"
    ) as fh:
        tmp_path = fh.name
        fh.write("# center    lower    upper    element    ion    order\n")
        for e in entries:
            if e.get("excluded", False):
                continue
            fh.write(_format_entry_line(e) + "\n")
    os.replace(tmp_path, str(path))


def resolve_line_list_path(
    found: Dict[str, Path],
    requested_path: Optional[str],
    suffix: str,
    base_dir: Path,
) -> Path:
    """Resolve line list path: explicit > detected > default candidate.

    When stars disagree on `linelistfile` (e.g. one star points at a
    per-star curated override like `<star>/line_list_filtered.txt` while
    the rest share a common list), pick the path used by the majority.
    The minority is assumed to be a per-star override that shouldn't
    drive the global visualization. Only raise when there is no clear
    majority (tie between two distinct paths).
    """
    if requested_path:
        return Path(requested_path).expanduser().resolve()

    from collections import Counter

    detected: List[str] = []
    for folder_path in found.values():
        config_path = folder_path.parent / "config.ini"
        if not config_path.exists():
            continue
        cfg = configparser.ConfigParser()
        cfg.read(str(config_path))
        p = cfg.get("PATHS", "linelistfile", fallback="").strip()
        if p:
            detected.append(str(Path(p).expanduser().resolve()))

    counts = Counter(detected)
    if len(counts) == 1:
        return Path(next(iter(counts)))
    if len(counts) > 1:
        ranked = counts.most_common()
        top_count = ranked[0][1]
        leaders = [path for path, c in ranked if c == top_count]
        if len(leaders) == 1:
            return Path(leaders[0])
        raise RuntimeError(
            f"Multiple line lists detected for suffix '{suffix}' with "
            f"no clear majority. Set --line-list.\n"
            + "\n".join(f"  {c}x  {p}" for p, c in ranked)
        )

    candidate = base_dir / "line_lists" / f"line_list_{suffix}.txt"
    if candidate.exists():
        return candidate.resolve()
    return (base_dir / "line_lists" / "targets_line_list_v2.txt").resolve()


# ══════════════════════════════════════════════════════════════════════════════
# Spectral interpolation & smoothing
# ══════════════════════════════════════════════════════════════════════════════


def flatten_full_spectrum(
    fit_data: dict,
) -> Optional[Tuple[np.ndarray, np.ndarray, np.ndarray]]:
    """Flatten multi-order spectra to 1D; sort by wavelength; deduplicate."""
    w = (fit_data["wvl"] / 10.0).reshape(-1)
    obs = fit_data["flux"].reshape(-1)
    fit = fit_data["fit"].reshape(-1)

    ok = np.isfinite(w) & np.isfinite(obs) & np.isfinite(fit)
    w, obs, fit = w[ok], obs[ok], fit[ok]
    if w.size < 2:
        return None

    idx = np.argsort(w)
    w, obs, fit = w[idx], obs[idx], fit[idx]
    w_u, u_idx = np.unique(w, return_index=True)
    return w_u, obs[u_idx], fit[u_idx]


def interp_to_common_grid(
    w: np.ndarray, y: np.ndarray, common_w: np.ndarray
) -> np.ndarray:
    """Interpolate data to common wavelength grid."""
    out = np.full(common_w.shape, np.nan, dtype=np.float32)
    if len(w) < 2:
        return out
    mask = (common_w >= w.min()) & (common_w <= w.max())
    if mask.any():
        out[mask] = np.interp(common_w[mask], w, y).astype(np.float32)
    return out


def smooth_nan(y: np.ndarray, window: int) -> np.ndarray:
    """Smooth data with NaN-aware moving average."""
    if window <= 1:
        return y.copy()
    window = int(window) | 1  # ensure odd
    y = np.asarray(y, dtype=float)
    good = np.isfinite(y).astype(float)
    y0 = np.where(np.isfinite(y), y, 0.0)
    k = np.ones(window, dtype=float)
    num = np.convolve(y0, k, mode="same")
    den = np.convolve(good, k, mode="same")
    out = np.full_like(y, np.nan)
    ok = den > 0
    out[ok] = num[ok] / den[ok]
    return out


# ══════════════════════════════════════════════════════════════════════════════
# Chi2 computation (per-region)
# ══════════════════════════════════════════════════════════════════════════════


def compute_region_chi2_for_star(
    fit_data: dict, wvl_lo: float, wvl_hi: float
) -> Tuple[float, int]:
    """Compute median chi2/N and pixel count for a region in one star."""
    wvl_arr = fit_data["wvl"]
    flux_fit = fit_data["flux_fit"]
    fit_arr = fit_data["fit"]
    error = fit_data["error"]
    idxtofit = fit_data["idxtofit"]

    pointwise: List[float] = []
    for order in range(wvl_arr.shape[0]):
        wvl_o = wvl_arr[order] / 10.0
        fit_pix = idxtofit[1][idxtofit[0] == order]
        if not len(fit_pix):
            continue
        fit_wvl = wvl_o[fit_pix]
        in_reg = np.isfinite(fit_wvl) & (fit_wvl >= wvl_lo) & (fit_wvl <= wvl_hi)
        if not in_reg.any():
            continue
        pix = fit_pix[in_reg]
        ff, fm, err = flux_fit[order][pix], fit_arr[order][pix], error[order][pix]
        ok = np.isfinite(ff) & np.isfinite(fm) & np.isfinite(err) & (err > 0)
        if ok.any():
            pointwise.extend(((ff[ok] - fm[ok]) / err[ok]) ** 2)

    if not pointwise:
        return np.nan, 0
    return float(np.mean(pointwise)), len(pointwise)


def compute_custom_region_chi2(
    fit_data_cache: dict, wvl_lo: float, wvl_hi: float
) -> dict:
    """Compute chi2 stats across all stars for a custom wavelength range."""
    if wvl_hi <= wvl_lo:
        return dict(
            median_chi2=np.nan, p16_chi2=np.nan, p84_chi2=np.nan, n_stars=0, med_npix=0
        )
    per_star, npix = [], []
    for fd in fit_data_cache.values():
        c, n = compute_region_chi2_for_star(fd, wvl_lo, wvl_hi)
        if np.isfinite(c):
            per_star.append(c)
            npix.append(n)
    if not per_star:
        return dict(
            median_chi2=np.nan, p16_chi2=np.nan, p84_chi2=np.nan, n_stars=0, med_npix=0
        )
    return dict(
        median_chi2=float(np.median(per_star)),
        p16_chi2=float(np.percentile(per_star, 16)),
        p84_chi2=float(np.percentile(per_star, 84)),
        n_stars=len(per_star),
        med_npix=int(np.median(npix)),
    )


def summarize_region_chi2(
    fit_data_cache: dict, line_list_entries: List[dict]
) -> List[dict]:
    """Compute chi2 summary stats for active (non-excluded) line-list regions.

    `region_idx` (0-based) on each summary row refers to the position in
    the input `line_list_entries` list — this matches the store indices used
    by the Dash callbacks so that navigation and exclusion stay in sync.
    """
    summary = []
    for idx, e in enumerate(line_list_entries):
        if e.get("excluded", False):
            continue
        per_star, npix = [], []
        for fd in fit_data_cache.values():
            c, n = compute_region_chi2_for_star(fd, e["lower"], e["upper"])
            if np.isfinite(c):
                per_star.append(c)
                npix.append(n)
        if per_star:
            summary.append(
                dict(
                    region_idx=idx,
                    center=e["center"],
                    lower=e["lower"],
                    upper=e["upper"],
                    element=e["element"],
                    ion=e["ion"],
                    med_chi2=float(np.median(per_star)),
                    n_stars=len(per_star),
                    med_npix=int(np.median(npix)),
                )
            )
    summary = [r for r in summary if np.isfinite(r["med_chi2"]) and r["n_stars"] > 0]
    summary.sort(key=lambda x: x["med_chi2"], reverse=True)
    return summary


def compute_residual_metrics(data: dict, wvl_lo: float, wvl_hi: float) -> dict:
    """Compute residual diagnostics for a wavelength range."""
    w = data["common_w"]
    r = data["mean_resid"]
    s = data["std_resid"]
    mask = (w >= wvl_lo) & (w <= wvl_hi)
    if mask.sum() < 2:
        return dict(
            n_grid=0,
            mean_resid=np.nan,
            mean_abs_resid=np.nan,
            p95_abs_resid=np.nan,
            mean_norm_resid=np.nan,
        )
    rv, sv = r[mask], s[mask]
    ok = np.isfinite(rv)
    if ok.sum() < 2:
        return dict(
            n_grid=0,
            mean_resid=np.nan,
            mean_abs_resid=np.nan,
            p95_abs_resid=np.nan,
            mean_norm_resid=np.nan,
        )
    rv, sv = rv[ok], sv[ok]
    with np.errstate(divide="ignore", invalid="ignore"):
        norm_r = np.abs(rv) / np.where((sv > 0) & np.isfinite(sv), sv, np.nan)
    return dict(
        n_grid=int(len(rv)),
        mean_resid=float(np.nanmean(rv)),
        mean_abs_resid=float(np.nanmean(np.abs(rv))),
        p95_abs_resid=float(np.nanpercentile(np.abs(rv), 95)),
        mean_norm_resid=float(np.nanmean(norm_r)),
    )


# ══════════════════════════════════════════════════════════════════════════════
# Main dataset builder
# ══════════════════════════════════════════════════════════════════════════════


def build_dataset(
    retrievals_dir: Path,
    suffix: str,
    line_list_path: Optional[str],
    grid_step_nm: float,
    smooth_window: int,
) -> dict:
    """Load and process all spectral data for a given suffix."""
    found = discover_output_folders(retrievals_dir, suffix)
    if not found:
        raise RuntimeError(
            f"No output folders for suffix '{suffix}' in {retrievals_dir}"
        )

    fit_data_cache, flat_data = {}, {}
    for slug, folder in found.items():
        try:
            fd = load_fit_data(str(folder))
            fl = flatten_full_spectrum(fd)
            if fl is not None:
                fit_data_cache[slug] = fd
                flat_data[slug] = fl
        except FileNotFoundError:
            continue

    if not flat_data:
        raise RuntimeError("No valid fit-data.fits loaded.")

    base_dir = retrievals_dir.parent
    resolved_ll = resolve_line_list_path(found, line_list_path, suffix, base_dir)
    if not resolved_ll.exists():
        raise RuntimeError(f"Line list not found: {resolved_ll}")
    ll_entries = load_line_list(resolved_ll)
    region_summary = summarize_region_chi2(fit_data_cache, ll_entries)

    w_min = float(np.nanmin([v[0].min() for v in flat_data.values()]))
    w_max = float(np.nanmax([v[0].max() for v in flat_data.values()]))
    common_w = np.arange(w_min, w_max + grid_step_nm, grid_step_nm, dtype=np.float32)

    obs_stack, fit_stack = [], []
    for slug in sorted(flat_data):
        w, obs, fit = flat_data[slug]
        oi = interp_to_common_grid(w, obs, common_w)
        fi = interp_to_common_grid(w, fit, common_w)
        if np.sum(np.isfinite(oi) & np.isfinite(fi)) >= 100:
            obs_stack.append(oi)
            fit_stack.append(fi)

    obs_arr = np.array(obs_stack, dtype=np.float32)
    fit_arr = np.array(fit_stack, dtype=np.float32)
    if obs_arr.size == 0:
        raise RuntimeError("No stars left after interpolation / quality filtering.")

    with np.errstate(all="ignore"):
        mean_obs = np.nanmean(obs_arr, axis=0)
        mean_fit = np.nanmean(fit_arr, axis=0)
        std_obs = np.nanstd(obs_arr, axis=0)
        std_fit = np.nanstd(fit_arr, axis=0)
    mean_resid = mean_obs - mean_fit
    std_resid = np.nanstd(obs_arr - fit_arr, axis=0)

    # Precompute hover stats for each fitted line-list region.
    # `region_idx` here is 1-based (matches the front-end tooltip) but maps
    # 1:1 to the entry's position in `ll_entries` via (region_idx - 1).
    summary_lookup = {r["region_idx"]: r for r in region_summary}
    resid_data = {
        "common_w": common_w,
        "mean_resid": mean_resid,
        "std_resid": std_resid,
    }
    ll_hover_stats = []
    for i, e in enumerate(ll_entries):
        rsum = summary_lookup.get(i)
        resid = compute_residual_metrics(resid_data, e["lower"], e["upper"])
        ll_hover_stats.append(
            dict(
                region_idx=i + 1,
                lower=e["lower"],
                upper=e["upper"],
                center=e["center"],
                element=e["element"],
                ion=e["ion"],
                med_chi2=(rsum["med_chi2"] if rsum else np.nan),
                n_stars=(rsum["n_stars"] if rsum else 0),
                med_npix=(rsum["med_npix"] if rsum else 0),
                mean_resid=resid["mean_resid"],
                mean_abs_resid=resid["mean_abs_resid"],
                p95_abs_resid=resid["p95_abs_resid"],
                mean_norm_resid=resid["mean_norm_resid"],
            )
        )

    return dict(
        suffix=suffix,
        retrievals_dir=str(retrievals_dir),
        line_list=str(resolved_ll),
        n_stars=int(obs_arr.shape[0]),
        common_w=common_w,
        mean_obs=mean_obs,
        mean_fit=mean_fit,
        std_obs=std_obs,
        std_fit=std_fit,
        mean_resid=mean_resid,
        std_resid=std_resid,
        mean_obs_s=smooth_nan(mean_obs, smooth_window),
        mean_fit_s=smooth_nan(mean_fit, smooth_window),
        mean_resid_s=smooth_nan(mean_resid, smooth_window),
        ll_entries=ll_entries,
        ll_hover_stats=ll_hover_stats,
        region_summary=region_summary,
        fit_data_cache=fit_data_cache,
    )
