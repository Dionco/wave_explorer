"""Export the static-demo payloads for wave_explorer (run in the asap env)."""
import argparse
import json
from pathlib import Path

import numpy as np

from wave_explorer.data_processing import (
    build_dataset,
    build_spectrum_payload,
)

REPO = Path(__file__).resolve().parents[1]          # wave_explorer/
SITE = REPO / "site"
PAYLOAD = SITE / "payload"
STAR_SLUGS = ["ds_leo", "gl_581", "gj_1289"]


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


def export(retrievals_dir: Path, suffix: str, line_list, vald_path, built_at: str):
    PAYLOAD.mkdir(parents=True, exist_ok=True)
    dataset = build_dataset(
        retrievals_dir=retrievals_dir, suffix=suffix, line_list_path=line_list,
        grid_step_nm=0.01, smooth_window=1, vald_path=vald_path,
    )
    # 1) mean spectrum payload (verbatim from the app)
    (PAYLOAD / "mean.json").write_text(json.dumps(build_spectrum_payload(dataset)))
    # 2) meta: geometry + region table + residual arrays + per-star fitted pixels + vald
    meta = {
        "common_w": _floats(dataset["common_w"]),
        "mean_resid": _floats(dataset["mean_resid"], 6),
        "std_resid": _floats(dataset["std_resid"], 6),
        "ll_entries": [
            {k: e[k] for k in ("center", "lower", "upper", "element", "ion", "excluded")}
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
        "fitpix": {slug: extract_fitpix(fd) for slug, fd in dataset["fit_data_cache"].items()},
        "vald": dataset.get("vald_payload"),
    }
    (PAYLOAD / "meta.json").write_text(json.dumps(meta))
    # 3) manifest (star views filled in by Task 2)
    w = dataset["common_w"]
    manifest = {
        "suffix": dataset["suffix"], "nStars": int(dataset["n_stars"]),
        "lambdaMin": float(w[0]), "lambdaMax": float(w[-1]),
        "lineListName": Path(dataset["line_list"]).name,
        "nRegions": len(dataset["ll_entries"]), "builtAt": built_at,
        "views": [{"id": "__mean__", "label": "All stars (mean)", "file": "mean.json"}],
    }
    (PAYLOAD / "manifest.json").write_text(json.dumps(manifest))
    return dataset, manifest


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
    args = _resolve_defaults(p.parse_args())
    ds, manifest = export(
        Path(args.retrievals_dir).resolve(), args.suffix, args.line_list,
        args.vald_list, args.built_at,
    )
    print(f"mean.json + meta.json + manifest.json written for {ds['n_stars']} stars")
    # Task 2 appends star payloads here.


if __name__ == "__main__":
    main()
