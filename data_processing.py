"""
ASAP Data Processing & Loading Layer
"""

import configparser
import math
import warnings
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np

from .theme import CHI2_THRESHOLDS, ELEMENT_COLORS, ELEMENT_COLOR_FALLBACK


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
            if len(candidates) > 1:
                print(
                    f"  ⚠ {star_dir.name}: {len(candidates)} output folders "
                    f"match suffix '{suffix}' "
                    f"({', '.join(p.name for p in candidates)}) — "
                    f"using {candidates[0].name}"
                )
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

    # %f (microseconds) prevents same-second saves clobbering each other
    # via the os.replace below.
    ts = timestamp or datetime.now().strftime("%Y%m%d-%H%M%S-%f")
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
        # Prefer the per-retrieval config_copy.ini (the actual config used
        # for this run); fall back to the star-level config.ini only if the
        # retrieval copy is missing.
        config_path = folder_path / "config_copy.ini"
        if not config_path.exists():
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


def compute_observed_ranges(
    flat_data: dict, gap_factor: float = 5.0
) -> List[Tuple[float, float]]:
    """Union of contiguous wavelength spans actually sampled by observations.

    Detects gaps between echelle orders by finding pixel-spacing jumps
    bigger than `gap_factor` × the per-star median Δλ. Returned ranges are
    merged across all stars so VALD overlay and other coverage-aware
    consumers can filter cleanly.
    """
    ranges: List[Tuple[float, float]] = []
    for slug in sorted(flat_data):
        w = flat_data[slug][0]
        if len(w) < 2:
            continue
        dw = np.diff(w)
        median_dw = float(np.median(dw))
        gap_threshold = max(0.05, gap_factor * median_dw)
        gap_idx = np.where(dw > gap_threshold)[0]
        starts = [0] + [int(i) + 1 for i in gap_idx]
        ends = [int(i) for i in gap_idx] + [len(w) - 1]
        for s, e in zip(starts, ends):
            ranges.append((float(w[s]), float(w[e])))
    ranges.sort()
    merged: List[Tuple[float, float]] = []
    for lo, hi in ranges:
        if merged and lo <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], hi))
        else:
            merged.append((lo, hi))
    return merged


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
    """Compute mean chi2/N and pixel count for a region in one star.

    Returns the MEAN of the pointwise ((flux-fit)/err)² over the region's
    fitted pixels; the median across stars is taken downstream (so table
    labels like "χ²/N med" refer to that per-star median).
    """
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
            median_chi2=np.nan, p16_chi2=np.nan, p84_chi2=np.nan, n_stars=0,
            med_npix=0, per_star_chi2=[],
        )
    per_star, npix = [], []
    for fd in fit_data_cache.values():
        c, n = compute_region_chi2_for_star(fd, wvl_lo, wvl_hi)
        if np.isfinite(c):
            per_star.append(c)
            npix.append(n)
    if not per_star:
        return dict(
            median_chi2=np.nan, p16_chi2=np.nan, p84_chi2=np.nan, n_stars=0,
            med_npix=0, per_star_chi2=[],
        )
    return dict(
        median_chi2=float(np.median(per_star)),
        p16_chi2=float(np.percentile(per_star, 16)),
        p84_chi2=float(np.percentile(per_star, 84)),
        n_stars=len(per_star),
        med_npix=int(np.median(npix)),
        per_star_chi2=[float(x) for x in per_star],
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
    vald_path: Optional[str] = None,
    only_slugs: Optional[List[str]] = None,
    only_folders: Optional[Dict[str, Path]] = None,
) -> dict:
    """Load and process all spectral data for a given suffix.

    ``only_folders`` (slug -> output folder) bypasses suffix-based discovery
    entirely and loads exactly those folders — used when the caller points at
    a specific output folder rather than a campaign suffix.
    """
    if only_folders is not None:
        found = dict(only_folders)
    else:
        found = discover_output_folders(retrievals_dir, suffix)
        if only_slugs is not None:
            wanted = set(only_slugs)
            found = {s: p for s, p in found.items() if s in wanted}
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

    from .vald import parse_vald_lines
    vald_entries: List[dict] = []
    if vald_path:
        vald_entries = parse_vald_lines(Path(vald_path).expanduser().resolve())

    w_min = float(np.nanmin([v[0].min() for v in flat_data.values()]))
    w_max = float(np.nanmax([v[0].max() for v in flat_data.values()]))
    n_grid = int(round((w_max - w_min) / grid_step_nm)) + 1
    common_w = np.linspace(w_min, w_max, n_grid).astype(np.float32)

    obs_stack, fit_stack, kept_slugs = [], [], []
    for slug in sorted(flat_data):
        w, obs, fit = flat_data[slug]
        oi = interp_to_common_grid(w, obs, common_w)
        fi = interp_to_common_grid(w, fit, common_w)
        if np.sum(np.isfinite(oi) & np.isfinite(fi)) >= 100:
            obs_stack.append(oi)
            fit_stack.append(fi)
            kept_slugs.append(slug)

    obs_arr = np.array(obs_stack, dtype=np.float32)
    fit_arr = np.array(fit_stack, dtype=np.float32)
    if obs_arr.size == 0:
        raise RuntimeError("No stars left after interpolation / quality filtering.")

    # Keep χ² statistics and the displayed mean/std computed over the SAME
    # star sample: drop stars that failed the overlap filter above from the
    # caches too, so summarize_region_chi2 / compute_custom_region_chi2 and
    # n_stars all describe the stacked sample.
    dropped = sorted(set(flat_data) - set(kept_slugs))
    if dropped:
        print(
            f"  ⚠ {len(dropped)} star(s) dropped by the <100-overlapping-"
            f"pixel filter (excluded from mean AND χ² stats): "
            + ", ".join(dropped)
        )
    fit_data_cache = {s: fit_data_cache[s] for s in kept_slugs}
    flat_data = {s: flat_data[s] for s in kept_slugs}
    region_summary = summarize_region_chi2(fit_data_cache, ll_entries)

    # warnings.catch_warnings (not np.errstate) is needed for the all-NaN
    # column RuntimeWarnings ("Mean of empty slice" / "Degrees of freedom
    # <= 0") that nanmean/nanstd emit via the warnings machinery.
    with np.errstate(all="ignore"), warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
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

    observed_ranges = compute_observed_ranges(flat_data)
    from .vald import build_vald_payload
    # Mean-view VALD payload: filtered to the windowed common_w range and the
    # mean observed coverage. The single-star full-range view rebuilds its own
    # (build_single_star_vald_payload) so lines outside the fitted windows show.
    vald_payload = build_vald_payload(
        vald_entries,
        lambda_min=float(common_w[0]),
        lambda_max=float(common_w[-1]),
        observed_ranges=observed_ranges,
    )

    dataset = dict(
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
        vald_entries=vald_entries,
        vald_path=str(vald_path) if vald_path else None,
        observed_ranges=observed_ranges,
        vald_payload=vald_payload,
        # slug -> output_* Path; only stars whose fit-data.fits loaded, so the
        # keys line up with fit_data_cache (the star-select dropdown options).
        output_folders={slug: found[slug] for slug in fit_data_cache},
    )
    # Cached mean-view payload to restore when the user picks "All stars (mean)".
    dataset["mean_payload"] = build_spectrum_payload(dataset)
    return dataset


# ══════════════════════════════════════════════════════════════════════════════
# Spectrum component payload
# ══════════════════════════════════════════════════════════════════════════════


def _build_region_metadata(dataset: dict) -> dict:
    """Build the region/colour/threshold metadata shared by every payload.

    Reads only `region_summary`, `ll_entries`, and `ll_hover_stats` — never the
    mean-view arrays — so it works for both the mean view and a single-star
    full-range view (whose base dataset carries no `common_w`/mean arrays).
    """
    chi2_map = {}
    for r in dataset.get("region_summary", []):
        c2 = r.get("med_chi2")
        try:
            c2f = float(c2)
        except (TypeError, ValueError):
            continue
        if math.isfinite(c2f):
            chi2_map[int(r["region_idx"])] = c2f

    hover_stats = list(dataset.get("ll_hover_stats", []))
    regions = []
    for i, _entry in enumerate(dataset.get("ll_entries", [])):
        hs = hover_stats[i] if i < len(hover_stats) else {}
        regions.append(
            {
                "idx": i,
                "chi2": chi2_map.get(i),
                "n_stars": int(hs.get("n_stars", 0) or 0),
                "n_pix": int(hs.get("med_npix", 0) or 0),
            }
        )

    return {
        "regions": regions,
        "chi2Thresholds": [float(t) for t in CHI2_THRESHOLDS],
        "elementColors": dict(ELEMENT_COLORS),
        "elementColorFallback": ELEMENT_COLOR_FALLBACK,
    }


def _round_wavelengths(seq) -> List[float]:
    """Wavelength axis values: rounded to 4 decimals (0.1 pm) to keep the
    JSON payload compact instead of embedding full 17-digit float reprs."""
    return [round(float(v), 4) for v in seq]


def _round_fluxes(seq) -> list:
    """Flux/fit/resid values: 5 decimals; non-finite becomes None.

    Contract with spectrum.js: gaps in the data are null (never NaN, which
    is not strict JSON).
    """
    return [
        round(float(v), 5) if math.isfinite(float(v)) else None for v in seq
    ]


def build_spectrum_payload(dataset: dict) -> dict:
    """Build the JSON-serializable payload for the spectrum-data-store.

    Carries the static data the client-side SVG renderer needs: the
    obs/fit/resid arrays, the wavelength axis, and a per-region χ² + star
    count list aligned to ll_entries by 0-based index.

    χ² is keyed by region_summary's `region_idx` (region_summary may be a
    subset of ll_entries — only regions with a fit). Star/pixel counts come
    from ll_hover_stats, which is kept 1:1 with ll_entries by position.
    Non-finite values become None so the payload is strict-JSON.
    """
    wavelengths = _round_wavelengths(dataset["common_w"])
    payload = {
        "wavelengths": wavelengths,
        "flux": _round_fluxes(dataset["mean_obs_s"]),
        "fitFlux": _round_fluxes(dataset["mean_fit_s"]),
        "resid": _round_fluxes(dataset["mean_resid_s"]),
        "lambdaMin": wavelengths[0],
        "lambdaMax": wavelengths[-1],
    }
    payload.update(_build_region_metadata(dataset))
    return payload


# ══════════════════════════════════════════════════════════════════════════════
# Single-star full-range model (model-full.fits)
# ══════════════════════════════════════════════════════════════════════════════


def load_full_model(folder) -> dict:
    """Load ``model-full.fits`` from a star's output folder.

    Returns a dict with the keys ``flatten_full_spectrum`` needs (``wvl``,
    ``flux``, ``fit``) plus ``error`` and ``fit_nomag`` for completeness. The
    full-range FITS has HDUs ``WVL/FLUX/ERROR/FIT/FITNOMAG`` only — there is no
    ``FLUXFIT``/``IDXTOFIT`` HDU (fitted regions are marked via the line list).
    """
    from astropy.io import fits

    folder = Path(folder)
    path = folder / "model-full.fits"
    if not path.exists():
        raise FileNotFoundError(path)
    with fits.open(path) as h:
        return {
            "wvl": np.asarray(h["WVL"].data),
            "flux": np.asarray(h["FLUX"].data),
            "fit": np.asarray(h["FIT"].data),
            "error": np.asarray(h["ERROR"].data),
            "fit_nomag": (
                np.asarray(h["FITNOMAG"].data) if "FITNOMAG" in h else None
            ),
        }


def build_single_star_payload(fit_data: dict, base_dataset: dict) -> dict:
    """Payload for a single star's full-range spectrum.

    Same shape as ``build_spectrum_payload`` so ``spectrum.js`` consumes it
    unchanged. Reuses ``flatten_full_spectrum`` (which drops non-finite pixels,
    so the NaN red-edges from real-obs gaps vanish) to get sorted 1D arrays,
    then supplies the obs/fit/resid arrays and λ-bounds alongside the
    region/colour/threshold metadata derived from the base dataset.
    """
    flat = flatten_full_spectrum(fit_data)
    if flat is None:
        raise ValueError("empty/invalid full-range spectrum")
    w, obs, fit = flat
    resid = obs - fit
    wavelengths = _round_wavelengths(w)
    payload = {
        "wavelengths": wavelengths,
        "flux": _round_fluxes(obs),
        "fitFlux": _round_fluxes(fit),
        "resid": _round_fluxes(resid),
        "lambdaMin": wavelengths[0],
        "lambdaMax": wavelengths[-1],
        # Flag so spectrum.js resets the view to the full λ-range when a
        # single-star payload arrives (the windowed mean view keeps its view).
        "fullRange": True,
    }
    # reuse the region/colour/threshold metadata; this does NOT touch the
    # mean-view arrays, so the base dataset need only carry ll_*/region_summary.
    payload.update(_build_region_metadata(base_dataset))
    return payload


def build_single_star_vald_payload(spectrum_payload: dict, vald_entries: list) -> dict:
    """VALD payload scoped to a single star's full-range spectrum.

    Filters VALD to the payload's full λ-range and to the star's OWN observed
    coverage (derived from the payload wavelengths, so genuine inter-order gaps
    stay hidden) — crucially WITHOUT restricting to the fitted line-list
    windows. This makes model-predicted lines outside the fitted regions
    visible in the full-range view, instead of inheriting the mean view's
    window-scoped VALD set.
    """
    from .vald import build_vald_payload

    w = spectrum_payload.get("wavelengths") or []
    if not w:
        return build_vald_payload(vald_entries, lambda_min=0.0, lambda_max=0.0)
    w_arr = np.asarray(w, dtype=float)
    # compute_observed_ranges keys gap detection off the wavelength axis only;
    # pass w for all three slots since obs/fit are unused there.
    observed = compute_observed_ranges({"_": (w_arr, w_arr, w_arr)})
    return build_vald_payload(
        vald_entries,
        lambda_min=float(spectrum_payload["lambdaMin"]),
        lambda_max=float(spectrum_payload["lambdaMax"]),
        observed_ranges=observed,
    )


# ══════════════════════════════════════════════════════════════════════════════
# Teff-stack mode (stacked multi-star view)
# ══════════════════════════════════════════════════════════════════════════════


def fitted_ranges_for_star(fit_data: dict) -> List[Tuple[float, float]]:
    """Contiguous wavelength spans of the pixels this star actually fitted.

    Derived from ``idxtofit``, so a region filtered out for this star (the
    per-star filtering workflow) contributes no span. Reuses the gap
    detection in ``compute_observed_ranges``.
    """
    wvl, idxtofit = fit_data["wvl"], fit_data["idxtofit"]
    ws = []
    for order in range(wvl.shape[0]):
        pix = idxtofit[1][idxtofit[0] == order]
        if len(pix):
            ws.append(np.asarray(wvl[order])[pix] / 10.0)
    if not ws:
        return []
    w = np.sort(np.concatenate(ws))
    w = w[np.isfinite(w)]
    if w.size < 2:
        return []
    return compute_observed_ranges({"_": (w, w, w)})


def mask_to_ranges(
    y: np.ndarray, common_w: np.ndarray, ranges: List[Tuple[float, float]]
) -> np.ndarray:
    """NaN out ``y`` at grid points outside every ``(lo, hi)`` range."""
    keep = np.zeros(common_w.shape, dtype=bool)
    for lo, hi in ranges:
        keep |= (common_w >= lo) & (common_w <= hi)
    out = np.asarray(y, dtype=float).copy()
    out[~keep] = np.nan
    return out


def build_stacked_payload(dataset: dict, offset_step: float = 0.5) -> dict:
    """Payload for the Teff-stack view (``stacked: true`` variant).

    One obs/fit trace pair per star on the dataset's common grid, each
    offset by ``i * offset_step`` with stars in Teff-ascending order
    (coolest at offset 0). The fit trace spans the star's ENTIRE observed
    range (fit-data.fits carries the model on every pixel, not just the
    fitted windows); per-star region usage is conveyed by the tooltip's
    ``perStar`` table instead. All non-finite values become None (strict
    JSON). ``regions[i]["perStar"]`` carries each displayed star's χ²/N
    and pixel count in trace order.
    """
    common_w = np.asarray(dataset["common_w"], dtype=float)
    cache = dataset["fit_data_cache"]
    teffs = dataset["stack_teffs"]  # slug -> Teff (K)
    slugs = sorted(cache, key=lambda s: teffs.get(s, float("inf")))

    def _vals(arr):
        return [float(v) if np.isfinite(v) else None for v in arr]

    stars = []
    for slug in slugs:
        if slug not in teffs:
            continue
        fd = cache[slug]
        flat = flatten_full_spectrum(fd)
        if flat is None:
            continue
        w, obs, fit = flat
        oi = interp_to_common_grid(w, obs, common_w)
        fi = interp_to_common_grid(w, fit, common_w)
        stars.append(
            {
                "slug": slug,
                "teff": float(teffs[slug]),
                # len(stars) (not the loop index) so offsets stay
                # consecutive even if a star is skipped above.
                "offset": float(len(stars) * offset_step),
                "flux": _vals(oi),
                "fitFlux": _vals(fi),
            }
        )

    payload = {
        "stacked": True,
        "offsetStep": float(offset_step),
        "wavelengths": [float(v) for v in common_w],
        "lambdaMin": float(common_w[0]),
        "lambdaMax": float(common_w[-1]),
        "stars": stars,
    }
    payload.update(_build_region_metadata(dataset))

    star_order = [s["slug"] for s in stars]
    for i, e in enumerate(dataset.get("ll_entries", [])):
        per_star = []
        for slug in star_order:
            c2, npix = compute_region_chi2_for_star(
                cache[slug], float(e["lower"]), float(e["upper"])
            )
            per_star.append(
                {
                    "chi2": float(c2) if np.isfinite(c2) else None,
                    "npix": int(npix),
                }
            )
        payload["regions"][i]["perStar"] = per_star
    return payload


def build_stacked_dataset(
    retrievals_dir: Path,
    suffix: str,
    line_list_path: Optional[str],
    grid_step_nm: float,
    smooth_window: int,
    vald_path: Optional[str] = None,
    n_stack: int = 10,
    offset_step: float = 0.5,
) -> dict:
    """Build the Teff-stack dataset: N even-Teff stars, stacked view.

    Same shape as ``build_dataset`` restricted to the picked slugs (so
    every existing callback works unchanged, with statistics scoped to
    the displayed stars) plus ``stacked``, ``stack_teffs`` and
    ``stacked_payload``. A picked star whose fit-data.fits fails to load
    is substituted by the next-nearest-Teff unused candidate.
    """
    from .stack_select import select_stack_stars

    found = discover_output_folders(retrievals_dir, suffix)
    if not found:
        raise RuntimeError(
            f"No output folders for suffix '{suffix}' in {retrievals_dir}"
        )
    sel = select_stack_stars(found, n_stack)
    for w in sel["warnings"]:
        print(f"  ⚠ {w}")
    if not sel["picked"]:
        raise RuntimeError("No stars with a usable Teff in results.txt.")

    # Verify each pick loads; substitute next-nearest-Teff on failure.
    picked_slugs = {p["slug"] for p in sel["picked"]}
    unused = [c for c in sel["candidates"] if c["slug"] not in picked_slugs]
    final = []
    for p in sel["picked"]:
        cand = p
        while cand is not None:
            try:
                load_fit_data(str(found[cand["slug"]]))
                final.append(cand)
                break
            except Exception:
                print(
                    f"  ⚠ {cand['slug']}: fit-data.fits failed to load — "
                    "substituting"
                )
                if unused:
                    unused.sort(key=lambda c: abs(c["teff"] - p["teff"]))
                    cand = unused.pop(0)
                else:
                    cand = None
    if not final:
        raise RuntimeError("No valid fit-data.fits loaded for the Teff stack.")

    dataset = build_dataset(
        retrievals_dir=retrievals_dir,
        suffix=suffix,
        line_list_path=line_list_path,
        grid_step_nm=grid_step_nm,
        smooth_window=smooth_window,
        vald_path=vald_path,
        only_slugs=[c["slug"] for c in final],
    )
    dataset["stacked"] = True
    dataset["stack_teffs"] = {
        c["slug"]: c["teff"]
        for c in final
        if c["slug"] in dataset["fit_data_cache"]
    }
    dataset["stacked_payload"] = build_stacked_payload(dataset, offset_step)
    # Any "__mean__" restore in stacked mode must restore the stack.
    dataset["mean_payload"] = dataset["stacked_payload"]
    return dataset
