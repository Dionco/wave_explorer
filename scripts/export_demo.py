"""Export the static-demo payloads for wave_explorer (run in the asap env)."""
import argparse
import json
import math
import subprocess
import sys
from pathlib import Path

import numpy as np

from wave_explorer.data_processing import (
    build_dataset,
    build_spectrum_payload,
    load_full_model,
    build_single_star_payload,
    build_single_star_vald_payload,
    compute_custom_region_chi2,
    compute_residual_metrics,
    summarize_region_chi2,
)
from wave_explorer.vald import build_vald_payload

REPO = Path(__file__).resolve().parents[1]          # wave_explorer/
SITE = REPO / "site"
PAYLOAD = SITE / "payload"
FIXTURES = REPO / "tests" / "fixtures"
STAR_SLUGS = ["ds_leo", "gl_699", "gj_1289"]


def _strict(o):
    """Recursively replace non-finite floats with None for strict-JSON serialisation."""
    if isinstance(o, (float, np.floating)):
        return o if math.isfinite(float(o)) else None
    if isinstance(o, dict):
        return {k: _strict(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_strict(v) for v in o]
    return o


def _jsonable(v):
    return None if (v is None or (isinstance(v, float) and not np.isfinite(v))) else v


def emit_compute_fixture(dataset):
    FIXTURES.mkdir(parents=True, exist_ok=True)
    windows = []
    for r in dataset["region_summary"]:
        lo, hi = float(r["lower"]), float(r["upper"])
        c = compute_custom_region_chi2(dataset["fit_data_cache"], lo, hi)
        rs = compute_residual_metrics(dataset, lo, hi)
        windows.append({
            "lo": lo, "hi": hi,
            "chi2": {k: _jsonable(c[k]) for k in
                     ("median_chi2", "p16_chi2", "p84_chi2", "n_stars", "med_npix")},
            "resid": {k: _jsonable(rs[k]) for k in
                      ("n_grid", "mean_resid", "mean_abs_resid", "p95_abs_resid", "mean_norm_resid")},
        })
    (FIXTURES / "compute_expected.json").write_text(json.dumps({"windows": windows}))


def extract_fitpix(fit_data: dict) -> dict:
    """Flatten a star's fitted pixels to valid (w_nm, ff, fm, err) arrays.

    Mirrors the pixel selection in compute_region_chi2_for_star: per order,
    restrict to idxtofit, convert wvl/10 -> nm, keep only finite values with
    error>0. The χ² of any [lo,hi] window equals the mean of ((ff-fm)/err)**2
    over the survivors whose w falls in the window.
    """
    wvl = fit_data["wvl"]
    flux_fit = fit_data["flux_fit"]
    fit_arr = fit_data["fit"]
    error = fit_data["error"]
    idxtofit = fit_data["idxtofit"]
    w, ff, fm, er = [], [], [], []
    for order in range(wvl.shape[0]):
        pix = idxtofit[1][idxtofit[0] == order]
        if not len(pix):
            continue
        wo = wvl[order] / 10.0
        a, b, c, d = wo[pix], flux_fit[order][pix], fit_arr[order][pix], error[order][pix]
        ok = np.isfinite(a) & np.isfinite(b) & np.isfinite(c) & np.isfinite(d) & (d > 0)
        w.extend(float(x) for x in a[ok])
        ff.extend(float(x) for x in b[ok])
        fm.extend(float(x) for x in c[ok])
        er.extend(float(x) for x in d[ok])
    return {"w": w, "ff": ff, "fm": fm, "err": er}


def _floats(seq, ndigits=None):
    if ndigits is None:
        return [float(v) for v in seq]
    return [round(float(v), ndigits) for v in seq]


def _clip_dataset(dataset, lmin, lmax):
    """Restrict the dataset to [lmin, lmax] nm so only that window is shipped/shown.

    Clips the common-grid + mean/std arrays, filters the line-list regions to those
    overlapping the window, then re-derives the region summary, VALD overlay, and
    mean payload from the filtered set so every per-index structure stays aligned.
    """
    cw = np.asarray(dataset["common_w"], dtype=float)
    mask = (cw >= lmin) & (cw <= lmax)
    for k in ("common_w", "mean_obs", "mean_fit", "std_obs", "std_fit",
              "mean_resid", "std_resid", "mean_obs_s", "mean_fit_s", "mean_resid_s"):
        v = dataset.get(k)
        if v is not None:
            dataset[k] = np.asarray(v)[mask]
    keep = [
        i for i, e in enumerate(dataset["ll_entries"])
        if float(e["upper"]) >= lmin and float(e["lower"]) <= lmax
    ]
    dataset["ll_entries"] = [dataset["ll_entries"][i] for i in keep]
    hs = dataset.get("ll_hover_stats") or []
    dataset["ll_hover_stats"] = [hs[i] for i in keep if i < len(hs)]
    dataset["region_summary"] = summarize_region_chi2(
        dataset["fit_data_cache"], dataset["ll_entries"])
    dataset["vald_payload"] = build_vald_payload(
        dataset.get("vald_entries", []), lambda_min=float(lmin), lambda_max=float(lmax),
        observed_ranges=dataset.get("observed_ranges"))
    dataset["mean_payload"] = build_spectrum_payload(dataset)
    return dataset


def _clip_fitpix(fp, lmin, lmax):
    """Keep only fitted pixels with wavelength in [lmin, lmax]."""
    w = fp["w"]
    keep = [i for i, x in enumerate(w) if lmin <= x <= lmax]
    return {k: [fp[k][i] for i in keep] for k in ("w", "ff", "fm", "err")}


def _clip_window_payload(payload, lmin, lmax):
    """Clip a spectrum payload's parallel arrays to [lmin, lmax] (in place).

    Used for the big single-star full-range payloads so only the window is shipped.
    """
    w = payload.get("wavelengths") or []
    keep = [i for i, x in enumerate(w) if lmin <= x <= lmax]
    for k in ("wavelengths", "flux", "fitFlux", "resid"):
        if isinstance(payload.get(k), list):
            payload[k] = [payload[k][i] for i in keep]
    if payload.get("wavelengths"):
        payload["lambdaMin"] = payload["wavelengths"][0]
        payload["lambdaMax"] = payload["wavelengths"][-1]
    return payload


def export(retrievals_dir: Path, suffix: str, line_list, vald_path, built_at: str,
           only_slugs=None, lam=None):
    PAYLOAD.mkdir(parents=True, exist_ok=True)
    dataset = build_dataset(
        retrievals_dir=retrievals_dir, suffix=suffix, line_list_path=line_list,
        grid_step_nm=0.01, smooth_window=1, vald_path=vald_path,
        only_slugs=only_slugs,
    )
    if lam is not None:
        _clip_dataset(dataset, lam[0], lam[1])
    # 1) mean spectrum payload (verbatim from the app)
    (PAYLOAD / "mean.json").write_text(json.dumps(_strict(build_spectrum_payload(dataset))))
    # 2) meta: geometry + region table + residual arrays + per-star fitted pixels + vald
    meta = {
        "common_w": _floats(dataset["common_w"]),
        # Full precision (no rounding): mean_norm_resid = |resid|/sigma amplifies
        # any rounding well past the JS<->Python parity tolerance.
        "mean_resid": _floats(dataset["mean_resid"]),
        "std_resid": _floats(dataset["std_resid"]),
        "ll_entries": [
            {
                "center": float(e["center"]), "lower": float(e["lower"]),
                "upper": float(e["upper"]), "element": str(e["element"]),
                "ion": str(e["ion"]), "excluded": bool(e.get("excluded", False)),
            }
            for e in dataset["ll_entries"]
        ],
        "region_summary": [
            {
                "region_idx": int(r["region_idx"]), "center": float(r["center"]),
                "lower": float(r["lower"]), "upper": float(r["upper"]),
                "element": str(r["element"]), "ion": str(r["ion"]),
                "med_chi2": float(r["med_chi2"]), "n_stars": int(r["n_stars"]),
                "med_npix": int(r["med_npix"]),
            }
            for r in dataset["region_summary"]
        ],
        "fitpix": {
            slug: (_clip_fitpix(extract_fitpix(fd), lam[0], lam[1]) if lam else extract_fitpix(fd))
            for slug, fd in dataset["fit_data_cache"].items()
        },
        "vald": dataset.get("vald_payload"),
    }
    (PAYLOAD / "meta.json").write_text(json.dumps(_strict(meta)))
    # 3) manifest (star views filled in by Task 2)
    w = dataset["common_w"]
    manifest = {
        "suffix": dataset["suffix"], "nStars": int(dataset["n_stars"]),
        "lambdaMin": float(w[0]), "lambdaMax": float(w[-1]),
        "lineListName": Path(dataset["line_list"]).name,
        "nRegions": len(dataset["ll_entries"]), "builtAt": built_at,
        "views": [{"id": "__mean__", "label": "All stars (mean)", "file": "mean.json"}],
    }
    (PAYLOAD / "manifest.json").write_text(json.dumps(_strict(manifest)))
    return dataset, manifest


def _ensure_model_full(folder: Path, grid_path):
    if (folder / "model-full.fits").exists():
        return
    cmd = [sys.executable, "-m", "wave_explorer.full_model", str(folder)]
    if grid_path:
        cmd += ["--grid-path", str(grid_path)]
    print("  computing model-full.fits:", " ".join(cmd))
    subprocess.run(cmd, check=True)


def export_star_payloads(dataset, manifest, grid_path, lam=None):
    folders = dataset["output_folders"]
    for slug in STAR_SLUGS:
        if slug not in folders:
            print(f"  WARNING: {slug} not in dataset; skipping full-range view")
            continue
        folder = Path(folders[slug])
        try:
            _ensure_model_full(folder, grid_path)
            fd = load_full_model(folder)
            payload = build_single_star_payload(fd, dataset)
            if lam is not None:
                _clip_window_payload(payload, lam[0], lam[1])   # ship only the window
            payload["vald"] = build_single_star_vald_payload(payload, dataset["vald_entries"])
            (PAYLOAD / f"star_{slug}.json").write_text(json.dumps(_strict(payload)))
            manifest["views"].append({"id": slug, "label": slug, "file": f"star_{slug}.json"})
            print(f"  star payload written: {slug}")
        except Exception as exc:
            print(
                f"  WARNING: full-range view for {slug} failed "
                f"({type(exc).__name__}: {exc}); skipping this star's view"
            )
    (PAYLOAD / "manifest.json").write_text(json.dumps(_strict(manifest)))


def _resolve_defaults(args):
    cwd = Path.cwd()
    if args.retrievals_dir is None:
        cand = cwd / "06_retrievals"
        args.retrievals_dir = cand if cand.exists() else cwd.parent / "obs-data-example" / "06_retrievals"
    if args.vald_list is None:
        bundled = REPO / "data" / "DionCobelens.017597"
        args.vald_list = str(bundled) if bundled.exists() else None
    return args


def main():
    p = argparse.ArgumentParser(description="Export wave_explorer static-demo payloads")
    p.add_argument("--suffix", default="ds_leo")
    p.add_argument("--retrievals-dir", default=None)
    p.add_argument("--line-list", default=None)
    p.add_argument("--vald-list", default=None)
    p.add_argument("--built-at", default="unknown", help="build timestamp string (passed in)")
    p.add_argument("--grid-path", default=None, help="model grid for model-full.fits pre-warm (Task 2)")
    p.add_argument(
        "--only-stars", default=None,
        help="comma-separated star slugs to restrict the whole demo to "
        "(mean view + per-star stats + full-range views); default = all stars in the campaign",
    )
    p.add_argument(
        "--lambda-min", type=float, default=730.0,
        help="lower wavelength bound (nm) to ship/show; keeps payloads small "
        "(esp. single-star full-range). Pass with --lambda-max 0 to disable clipping.",
    )
    p.add_argument("--lambda-max", type=float, default=1000.0,
                   help="upper wavelength bound (nm); see --lambda-min.")
    args = _resolve_defaults(p.parse_args())
    only_slugs = (
        [s.strip() for s in args.only_stars.split(",") if s.strip()]
        if args.only_stars else None
    )
    lam = None if args.lambda_max <= 0 else (args.lambda_min, args.lambda_max)
    ds, manifest = export(
        Path(args.retrievals_dir).resolve(), args.suffix, args.line_list,
        args.vald_list, args.built_at, only_slugs=only_slugs, lam=lam,
    )
    if lam:
        print(f"clipped to [{lam[0]:.1f}, {lam[1]:.1f}] nm")
    print(f"mean.json + meta.json + manifest.json written for {ds['n_stars']} stars")
    export_star_payloads(ds, manifest, args.grid_path, lam=lam)
    print("star payloads:", [v["id"] for v in manifest["views"] if v["id"] != "__mean__"])
    emit_compute_fixture(ds)
    print(f"compute_expected.json written to {FIXTURES}")


if __name__ == "__main__":
    main()
