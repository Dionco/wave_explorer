# Wave Explorer Static Demo — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Publish a fully interactive, static GitHub Pages demo of `wave_explorer` on preloaded `ds_leo` data so thesis reviewers can use the tool from a URL, with no server.

**Architecture:** Reuse the existing client-side renderer (`spectrum.js`, `heatstrip.js`, `keyboard.js`, `styles.css`) byte-for-byte. Replace the Dash/Flask server with a tiny static controller (`demo/main.mjs`) that installs a `window.dash_clientside.set_props` shim, loads precomputed JSON payloads, drives `spectrum.js` via its `WaveExplorer.sync(...)` API, and re-implements the few server callbacks (live χ²/residual recompute, stats/table/histogram rendering, drag/draw) in vanilla JS. Payloads are exported offline by a Python script that calls the unchanged `data_processing` functions.

**Tech Stack:** Python 3.9 + the `asap` conda env (export only); vanilla ES modules + SVG in the browser (runtime); Node ≥18 for JS unit tests; GitHub Pages (`gh-pages` branch) for hosting.

## Global Constraints

- Runtime is **100% static**: no Python, no network after initial asset load. Everything the browser needs ships as files under `site/`.
- The vendored files `site/assets/spectrum.js`, `heatstrip.js`, `keyboard.js`, `styles.css` are **copied verbatim** from `wave_explorer/assets/` and never edited. All new behavior lives in `site/demo/`.
- Editing is **local-only**: drags/draws update in-browser state and recompute χ² live, but **nothing persists** and there is **no save/download**. The save/discard/pending header controls are hidden; a "changes are local to your browser" note replaces them.
- Preloaded views: `ds_leo` campaign **mean view** + **single-star full-range** views for exactly `ds_leo`, `gl_581`, `gj_1289`.
- Export runs only on this machine via `/net/vdesk/data2/cobelens/.conda/envs/asap/bin/python` (the env that has ASAP + the data + the model grid). CI never rebuilds payloads.
- The `spectrum.js` data contract is fixed: a spectrum payload has keys `wavelengths, flux, fitFlux, resid, lambdaMin, lambdaMax, regions[], chi2Thresholds[], elementColors{}, elementColorFallback` (+ optional `fullRange:true`); `WaveExplorer.sync(specData, llEntries, pending, selected, drawActive, goto, vald, valdVisible, valdDepthMin)`; outbound events arrive only via `window.dash_clientside.set_props(storeId, {data})` for `selected-region-store {region_idx}|null`, `drag-result-store {region_idx, bound, new_x_nm}`, `draw-region-store {lo, hi}`.
- χ²/N tiers (from `theme.py`): good `<5`, fair `<15`, poor `<30`, bad `≥30`. Colors: green `#4f7a4d`, amber `#b88829`, orange `#c87338`, red `#9c3d2e`, miss/muted `#75705f`. `chi2_pct = min(100, int(v/30*100))`.

## File Structure

```
wave_explorer/
├── scripts/
│   ├── export_demo.py          # build site/payload/*.json + test fixtures   (Task 1,2,5)
│   └── publish_gh_pages.sh      # mirror site/ → gh-pages branch              (Task 11)
├── site/
│   ├── index.html               # static shell: banner + empty containers     (Task 3)
│   ├── assets/                   # VENDORED VERBATIM                           (Task 3)
│   │   ├── spectrum.js  heatstrip.js  keyboard.js  styles.css
│   ├── demo/
│   │   ├── theme.mjs             # χ² color/label/tier/pct, fmt, palette       (Task 4)
│   │   ├── compute.mjs           # region/custom χ² + residual metrics         (Task 5)
│   │   ├── render.mjs            # header/heatstrip/histogram/table/stats DOM   (Task 6,7)
│   │   └── main.mjs              # shim + bootstrap + handlers + view switch    (Task 4,7,8,9)
│   └── payload/                  # generated                                   (Task 1,2)
│       ├── manifest.json  mean.json  meta.json
│       └── star_ds_leo.json  star_gl_581.json  star_gj_1289.json
└── tests/
    ├── test_export_demo.py       # Python: fitpix extraction + export schema   (Task 1,2)
    └── demo_compute.test.mjs      # Node: JS compute vs Python expectations     (Task 5)
```

Why this split: `theme.mjs`/`compute.mjs` are pure and Node-testable; `render.mjs` is pure DOM-string building; `main.mjs` holds all wiring/state. `spectrum.js` stays untouched, so the SVG plot, drag, draw, and tooltip keep working exactly as in the live app.

---

### Task 1: Payload export — mean spectrum + meta + per-star fitted pixels

**Files:**
- Create: `scripts/export_demo.py`
- Test: `tests/test_export_demo.py`

**Interfaces:**
- Produces (consumed by Tasks 4–9 and the JS parity test):
  - `extract_fitpix(fit_data: dict) -> dict` → `{"w": [float nm], "ff": [float], "fm": [float], "err": [float]}` — only fully-valid fitted pixels (finite wvl/flux_fit/fit/error, error>0), flattened across orders. Parallel arrays, same length.
  - `site/payload/mean.json` = `build_spectrum_payload(dataset)` verbatim.
  - `site/payload/meta.json` = `{common_w, mean_resid, std_resid, ll_entries, region_summary, fitpix:{slug:extract_fitpix(...)}, vald}`.
  - `site/payload/manifest.json` = `{suffix, nStars, lambdaMin, lambdaMax, lineListName, nRegions, builtAt, views:[{id,label,file}]}`.

The export reuses the **unchanged** `data_processing` functions (`build_dataset`, `build_spectrum_payload`) and the same default path/vald resolution as `app.main()` (`app.py:177-191`).

- [ ] **Step 1: Write the failing test for `extract_fitpix`**

`extract_fitpix` must reproduce exactly the pixels `compute_region_chi2_for_star` (`data_processing.py:433-461`) would use: per order, take `idxtofit` pixels, convert `wvl/10` → nm, keep only finite + `error>0`. Test it on a synthetic `fit_data` (no FITS, no env) so it runs anywhere.

```python
# tests/test_export_demo.py
import numpy as np
from scripts.export_demo import extract_fitpix
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
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `/net/vdesk/data2/cobelens/.conda/envs/asap/bin/python -m pytest tests/test_export_demo.py::test_extract_fitpix_matches_python_chi2 -v`
Expected: FAIL — `ModuleNotFoundError: scripts.export_demo` (file not yet created).

- [ ] **Step 3: Implement `extract_fitpix` + the export skeleton**

```python
# scripts/export_demo.py
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
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `/net/vdesk/data2/cobelens/.conda/envs/asap/bin/python -m pytest tests/test_export_demo.py::test_extract_fitpix_matches_python_chi2 -v`
Expected: PASS.

- [ ] **Step 5: Run the real export and sanity-check it (integration)**

Run (from `new/obs-data-example/`):
```bash
cd /net/vdesk/data2/cobelens/MRP/new/obs-data-example
/net/vdesk/data2/cobelens/.conda/envs/asap/bin/python -m scripts.export_demo --built-at 2026-06-30
ls -la /net/vdesk/data2/cobelens/MRP/new/obs-data-example/wave_explorer/site/payload/
du -h /net/vdesk/data2/cobelens/MRP/new/obs-data-example/wave_explorer/site/payload/*.json
```
Expected: `mean.json`, `meta.json`, `manifest.json` exist; `meta.json` is the largest (fitpix); log the sizes. If `meta.json` is over ~8 MB, note it for Task 5's size budget (mitigation: round `ff/fm/err` to fewer digits, or drop stars — but do NOT do this yet).

- [ ] **Step 6: Commit**

```bash
git add scripts/export_demo.py tests/test_export_demo.py
git commit -m "feat(demo): export mean + meta + fitpix payloads for static demo"
```

---

### Task 2: Single-star full-range payloads + model-full pre-warm

**Files:**
- Modify: `scripts/export_demo.py` (add `export_star_payloads`, call it from `main`)
- Modify: `tests/test_export_demo.py` (schema test)

**Interfaces:**
- Consumes: `dataset` from Task 1 (`dataset["output_folders"][slug]`, `dataset["vald_entries"]`).
- Produces: `site/payload/star_<slug>.json` = `build_single_star_payload(fit_data, dataset)` with an added `"vald"` key = `build_single_star_vald_payload(payload, dataset["vald_entries"])`; and appends each to `manifest["views"]`.

`model-full.fits` is **missing** for all three stars, so it must be computed once via the existing driver (`python -m wave_explorer.full_model <output_folder> [--grid-path ...]`). The campaign is Narval/optical; the most likely grid is `/net/vdesk/data2/cobelens/MRP/new/grid_models/hdf5-narval-full/`, but verify against each run's config `pathToGrid` and override with `--grid-path` if the driver errors.

- [ ] **Step 1: Write the failing schema test**

```python
# tests/test_export_demo.py  (append)
import json
from pathlib import Path
from scripts.export_demo import REPO, STAR_SLUGS


def test_star_payload_schema_if_present():
    """If star payloads have been exported, they must carry full-range spectra."""
    for slug in STAR_SLUGS:
        f = REPO / "site" / "payload" / f"star_{slug}.json"
        if not f.exists():
            continue  # integration-only; skipped until export has run
        p = json.loads(f.read_text())
        for key in ("wavelengths", "flux", "fitFlux", "resid", "lambdaMin",
                    "lambdaMax", "regions", "fullRange", "vald"):
            assert key in p, f"{slug} payload missing {key}"
        assert p["fullRange"] is True
        assert len(p["wavelengths"]) == len(p["flux"]) == len(p["fitFlux"])
```

- [ ] **Step 2: Run it to verify it passes-trivially-then-fails after export**

Run: `/net/vdesk/data2/cobelens/.conda/envs/asap/bin/python -m pytest tests/test_export_demo.py::test_star_payload_schema_if_present -v`
Expected: PASS (skips, since no star payloads yet). This guards the schema once Step 4 produces the files.

- [ ] **Step 3: Implement `export_star_payloads`**

```python
# scripts/export_demo.py  (add imports + function, then call from main)
import subprocess
from wave_explorer.data_processing import (
    load_full_model, build_single_star_payload, build_single_star_vald_payload,
)


def _ensure_model_full(folder: Path, grid_path):
    if (folder / "model-full.fits").exists():
        return
    cmd = ["python", "-m", "wave_explorer.full_model", str(folder)]
    if grid_path:
        cmd += ["--grid-path", str(grid_path)]
    print("  computing model-full.fits:", " ".join(cmd))
    subprocess.run(cmd, check=True)


def export_star_payloads(dataset, manifest, grid_path):
    folders = dataset["output_folders"]
    for slug in STAR_SLUGS:
        if slug not in folders:
            print(f"  WARNING: {slug} not in dataset; skipping full-range view")
            continue
        folder = Path(folders[slug])
        _ensure_model_full(folder, grid_path)
        fd = load_full_model(folder)
        payload = build_single_star_payload(fd, dataset)
        payload["vald"] = build_single_star_vald_payload(payload, dataset["vald_entries"])
        (PAYLOAD / f"star_{slug}.json").write_text(json.dumps(payload))
        manifest["views"].append({"id": slug, "label": slug, "file": f"star_{slug}.json"})
    (PAYLOAD / "manifest.json").write_text(json.dumps(manifest))
```

Add to `main()` after `export(...)`:
```python
    export_star_payloads(ds, manifest, args.grid_path)
    print("star payloads:", [v["id"] for v in manifest["views"] if v["id"] != "__mean__"])
```

- [ ] **Step 4: Run the real star export (integration)**

Run:
```bash
cd /net/vdesk/data2/cobelens/MRP/new/obs-data-example
/net/vdesk/data2/cobelens/.conda/envs/asap/bin/python -m scripts.export_demo \
  --built-at 2026-06-30 \
  --grid-path /net/vdesk/data2/cobelens/MRP/new/grid_models/hdf5-narval-full/
```
Expected: three `model-full.fits` computed (~1 min each, first time), then `star_ds_leo.json`, `star_gl_581.json`, `star_gj_1289.json` written and added to `manifest.json`. If the driver errors on the grid, re-run with the `pathToGrid` from that star's run config.

- [ ] **Step 5: Run the schema test to verify it now enforces**

Run: `/net/vdesk/data2/cobelens/.conda/envs/asap/bin/python -m pytest tests/test_export_demo.py -v`
Expected: PASS (schema test now exercises the three real files).

- [ ] **Step 6: Commit**

```bash
git add scripts/export_demo.py tests/test_export_demo.py
git commit -m "feat(demo): export single-star full-range payloads (ds_leo, gl_581, gj_1289)"
```

---

### Task 3: Static shell `index.html` + vendored assets

**Files:**
- Create: `site/index.html`
- Create (copy verbatim): `site/assets/spectrum.js`, `site/assets/heatstrip.js`, `site/assets/keyboard.js`, `site/assets/styles.css`

**Interfaces:**
- Produces: the DOM the renderer and `spectrum.js` require — IDs `spectrum-graph`, `candidate-stats`, `chi2-histogram`, `status-range`, `table-body`, `heatstrip`, `heatstrip-regions`, `heatstrip-viewport`, `star-select`, `vald-toggle-btn`, `vald-depth-min-slider`, `draw-mode-toggle`, `cursor-tooltip`, `draw-confirm-popover` (+ its `draw-confirm-range-text`, `draw-confirm-accept`, `draw-confirm-cancel`), and header containers (`#header-chips`, `#demo-note`). Containers are empty; `main.mjs` fills them.

- [ ] **Step 1: Vendor the assets**

```bash
cd /net/vdesk/data2/cobelens/MRP/new/obs-data-example/wave_explorer
mkdir -p site/assets site/demo
cp assets/spectrum.js assets/heatstrip.js assets/keyboard.js assets/styles.css site/assets/
```

- [ ] **Step 2: Write `site/index.html`**

The body mirrors `layout.build_layout` structure but ships empty containers (data-driven content is rendered by `main.mjs`). The heatstrip wrapper keeps its `data-lmin`/`data-lmax` (filled by `main.mjs` once `manifest.json` loads — set to `0`/`1` placeholders here).

```html
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Wave Explorer — interactive demo</title>
  <link rel="stylesheet" href="assets/styles.css" />
</head>
<body>
  <!-- Explainer banner (Task 10 fills copy/links) -->
  <div id="demo-banner" class="demo-banner"></div>

  <div class="asap-header">
    <div class="asap-wordmark">
      <span>Wave Explorer</span>
      <span class="wm-sub">Line curation · ASAP · demo</span>
    </div>
    <div id="header-chips" class="header-chips"></div>
    <div class="h-spacer"></div>
    <button id="draw-mode-toggle" class="btn btn-sm" type="button">✎ Draw Region</button>
    <div id="selected-region-container" class="selected-region-container" style="display:none">
      <span class="h-chip c-cyan">◉ <span id="selected-region-label" class="hc-val"></span></span>
      <button id="selected-clear-btn" class="btn btn-sm" type="button">Deselect</button>
    </div>
    <div id="demo-note" class="h-chip"></div>
  </div>

  <div class="asap-main">
    <div class="plot-wrap">
      <div class="spectrum-toolbar">
        <div class="spectrum-toolbar-left">
          <div class="eyebrow">Spectrum</div>
          <div class="display-md">Observation, fit &amp; residuals</div>
          <div style="display:flex;gap:8px;align-items:center;margin-top:6px">
            <select id="star-select" class="we-select" style="min-width:220px"></select>
          </div>
        </div>
        <div class="vald-toolbar-controls" style="display:flex;gap:10px;align-items:center">
          <button id="vald-toggle-btn" class="btn btn-sm" type="button">│ VALD lines</button>
          <span class="eyebrow" style="white-space:nowrap">min depth</span>
          <input id="vald-depth-min-slider" type="range" min="0" max="1" step="0.05" value="0.10" style="width:160px" />
        </div>
        <div class="zoom-readout">scroll to zoom · drag to pan · double-click resets</div>
      </div>
      <div class="spectrum-canvas-wrap" style="position:relative">
        <div id="spectrum-graph" class="spectrum-canvas"></div>
      </div>
      <div class="heatstrip-section">
        <div class="heatstrip-head">
          <span class="eyebrow">Quality map · full λ range</span>
          <span class="subtitle">click or drag to navigate</span>
        </div>
        <div id="heatstrip" class="heatstrip-wrap" data-lmin="0" data-lmax="1"
             title="Click or drag to move the spectrum view">
          <div id="heatstrip-regions" class="heatstrip-regions"></div>
          <div id="heatstrip-viewport" class="heatstrip-viewport"></div>
        </div>
      </div>
    </div>

    <div class="two-col gap-md">
      <div class="card">
        <div class="card-title">Live Statistics</div>
        <div id="candidate-stats">Click a region in the spectrum to see statistics.</div>
        <div id="chi2-histogram"></div>
      </div>
      <div class="card gap-lg">
        <div class="card-title" style="margin-bottom:12px">Worst Fitted Regions (top 50 by median χ²/N)</div>
        <div class="table-wrap">
          <table class="asap-table">
            <thead><tr>
              <th>#</th><th>Center (nm)</th><th>Range (nm)</th><th>χ²/N med</th>
              <th>Quality</th><th>N★</th><th>N pix</th><th></th>
            </tr></thead>
            <tbody id="table-body"></tbody>
          </table>
        </div>
      </div>
    </div>
  </div>

  <div id="cursor-tooltip" class="cursor-tooltip" style="display:none"></div>

  <div id="draw-confirm-popover" style="display:none;position:fixed;z-index:999">
    <div style="margin-bottom:10px;font-weight:bold">Add this region?</div>
    <div id="draw-confirm-range-text" style="font-size:12px;margin-bottom:12px"></div>
    <div style="display:flex;gap:8px">
      <button id="draw-confirm-accept" class="btn btn-sm btn-green" type="button">✓ Accept</button>
      <button id="draw-confirm-cancel" class="btn btn-sm btn-danger" type="button">✕ Cancel</button>
    </div>
  </div>

  <div class="status-bar">
    <div class="status-dot"></div>
    <span id="status-summary" style="color:#9c9684"></span>
    <span>·</span>
    <span id="status-range" style="color:#b3553b"></span>
  </div>

  <!-- vendored classic scripts define window.WaveExplorer etc. -->
  <script src="assets/spectrum.js"></script>
  <script src="assets/heatstrip.js"></script>
  <script src="assets/keyboard.js"></script>
  <!-- controller -->
  <script type="module" src="demo/main.mjs"></script>
</body>
</html>
```

- [ ] **Step 3: Verify the page loads and is styled (manual)**

Run a throwaway static server and open it:
```bash
cd /net/vdesk/data2/cobelens/MRP/new/obs-data-example/wave_explorer/site
/net/vdesk/data2/cobelens/.conda/envs/asap/bin/python -m http.server 8123
```
Open `http://127.0.0.1:8123/`. Expected: the warm-parchment theme applies (header bar, cards, empty table). The browser console will show a 404/parse path for `demo/main.mjs` (created next) — that is expected at this step. The spectrum area is empty (no payload yet).

- [ ] **Step 4: Commit**

```bash
git add site/index.html site/assets/
git commit -m "feat(demo): static shell index.html + vendored spectrum/heatstrip/keyboard/css"
```

---

### Task 4: `theme.mjs` + `main.mjs` bootstrap (shim + render the mean spectrum)

**Files:**
- Create: `site/demo/theme.mjs`
- Create: `site/demo/main.mjs`

**Interfaces:**
- `theme.mjs` produces: `chi2Color(v)`, `chi2Label(v)`, `chi2Tier(v)`, `chi2Pct(v)`, `fmt(v, digits, signed=false)`, and `C` (palette object). NaN/`null`/non-finite → muted color, `"—"` label, `"miss"` tier, `0` pct.
- `main.mjs` produces: the global controller. Installs `window.dash_clientside = {no_update, set_props}` **before** any await; loads `manifest.json` + `mean.json` + `meta.json`; calls `window.WaveExplorer.sync(...)` to render the mean spectrum. Exposes nothing (side-effecting entry point).

- [ ] **Step 1: Write `theme.mjs`** (1:1 port of `theme.py:64-117,140-163`)

```js
// site/demo/theme.mjs
export const C = {
  bg: "#f8f5ec", surf: "#fdfcf7", border2: "#e6dfcb",
  text: "#1a1814", muted: "#75705f", dim: "#9c9684",
  cyan: "#b3553b", amber: "#b88829", green: "#4f7a4d",
  red: "#9c3d2e", orange: "#c87338",
};
const GOOD = 5.0, FAIR = 15.0, BAD = 30.0;
const finite = (v) => v != null && Number.isFinite(+v);

export function chi2Color(v) {
  if (!finite(v)) return C.muted;
  if (v < GOOD) return C.green;
  if (v < FAIR) return C.amber;
  if (v < BAD) return C.orange;
  return C.red;
}
export function chi2Label(v) {
  if (!finite(v)) return "—";
  if (v < GOOD) return "GOOD";
  if (v < FAIR) return "FAIR";
  if (v < BAD) return "POOR";
  return "BAD";
}
export function chi2Tier(v) {
  if (!finite(v)) return "miss";
  if (v < GOOD) return "good";
  if (v < FAIR) return "fair";
  if (v < BAD) return "poor";
  return "bad";
}
export function chi2Pct(v) {
  if (!finite(v)) return 0;
  return Math.min(100, Math.trunc((v / BAD) * 100));
}
export function fmt(v, digits = 4, signed = false) {
  if (!finite(v)) return "—";
  const s = (+v).toFixed(digits);
  return signed && +v >= 0 ? "+" + s : s;
}
```

- [ ] **Step 2: Write `main.mjs` bootstrap (shim + sync the mean view)**

```js
// site/demo/main.mjs
// Static controller: replaces the Dash server for the wave_explorer demo.

// 1) Dash shim — installed synchronously so any spectrum.js event is captured.
const handlers = {};               // storeId -> fn(data); filled in later tasks
window.dash_clientside = window.dash_clientside || {};
window.dash_clientside.no_update = Symbol("no_update");
window.dash_clientside.set_props = (id, props) => {
  const fn = handlers[id];
  if (fn && props && "data" in props) fn(props.data);
};

const state = {
  manifest: null, meta: null, mean: null,
  llEntries: [], pending: {}, selected: null,
  drawActive: false, valdVisible: false, valdDepthMin: 0.10,
  view: "__mean__", specByView: {},   // cache loaded spectrum payloads
  gotoTick: 0,
};

async function getJSON(file) {
  const r = await fetch(`payload/${file}`);
  if (!r.ok) throw new Error(`fetch payload/${file}: ${r.status}`);
  return r.json();
}

function currentVald() {
  const spec = state.specByView[state.view];
  return (spec && spec.vald) || state.meta.vald || null;
}

// Push the full state into spectrum.js. Single source of truth for the plot.
export function syncSpectrum(goto = null) {
  const spec = state.specByView[state.view];
  window.WaveExplorer.sync(
    spec, state.llEntries, state.pending, state.selected,
    state.drawActive, goto, currentVald(), state.valdVisible, state.valdDepthMin,
  );
}

async function boot() {
  state.manifest = await getJSON("manifest.json");
  state.meta = await getJSON("meta.json");
  state.mean = await getJSON("mean.json");
  state.specByView["__mean__"] = state.mean;
  state.llEntries = state.meta.ll_entries.map((e) => ({ ...e }));

  // heatstrip needs λ-bounds on its wrapper before heatstrip.js reads them
  const hs = document.getElementById("heatstrip");
  hs.dataset.lmin = String(state.manifest.lambdaMin);
  hs.dataset.lmax = String(state.manifest.lambdaMax);

  syncSpectrum();                  // render the mean spectrum
  // Task 6 fills header/heatstrip/histogram/table; Task 7+ wire handlers.
  const { renderAll } = await import("./render.mjs");
  renderAll(state, { handlers, syncSpectrum });
}

boot().catch((err) => {
  console.error(err);
  const el = document.getElementById("candidate-stats");
  if (el) el.textContent = "Failed to load demo data: " + err.message;
});
```

(Adjustment: `render.mjs` does not exist until Task 6. For this task, temporarily comment out the `renderAll` import lines so the bootstrap is testable in isolation, then restore them in Task 6.)

- [ ] **Step 3: Verify the mean spectrum renders (manual)**

With the static server running (Task 3 Step 3) and payloads from Tasks 1–2 present, reload `http://127.0.0.1:8123/`.
Expected: the obs/fit/residual spectrum draws in `#spectrum-graph`; scroll-zoom and drag-pan work; hovering a fitted region shows the cursor tooltip with χ²/N (all handled inside the untouched `spectrum.js`). No console errors from the shim.

- [ ] **Step 4: Commit**

```bash
git add site/demo/theme.mjs site/demo/main.mjs
git commit -m "feat(demo): dash shim + bootstrap renders the mean spectrum from payloads"
```

---

### Task 5: `compute.mjs` — live χ²/residual recompute + Python parity gate

**Files:**
- Create: `site/demo/compute.mjs`
- Modify: `scripts/export_demo.py` (emit a test-fixture of Python-computed expectations)
- Create: `tests/demo_compute.test.mjs`

**Interfaces:**
- `compute.mjs` produces:
  - `regionChi2ForStar(star, lo, hi) -> {chi2, n}` where `star = {w,ff,fm,err}`; `chi2` is `NaN`, `n` `0` if no pixels.
  - `customRegionChi2(fitpix, lo, hi) -> {median_chi2, p16_chi2, p84_chi2, n_stars, med_npix, per_star_chi2}` (`fitpix` = `{slug:star}`); matches `compute_custom_region_chi2`.
  - `residualMetrics(commonW, meanResid, stdResid, lo, hi) -> {n_grid, mean_resid, mean_abs_resid, p95_abs_resid, mean_norm_resid}`; matches `compute_residual_metrics`.
  - `percentile(sortedAsc, q)` — numpy linear interpolation; `median(arr)`.
- Consumes: `meta.json` `fitpix`, `common_w`, `mean_resid`, `std_resid`.

- [ ] **Step 1: Write the failing Node parity test**

```js
// tests/demo_compute.test.mjs
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import {
  customRegionChi2, residualMetrics,
} from "../site/demo/compute.mjs";

const meta = JSON.parse(readFileSync(new URL("../site/payload/meta.json", import.meta.url)));
const exp = JSON.parse(readFileSync(new URL("./fixtures/compute_expected.json", import.meta.url)));
const close = (a, b, eps = 1e-6) =>
  (a == null && b == null) ||
  (Number.isNaN(a) && b == null) ||
  Math.abs(a - b) <= eps * (1 + Math.abs(b));

test("customRegionChi2 matches Python for every region window", () => {
  for (const w of exp.windows) {
    const got = customRegionChi2(meta.fitpix, w.lo, w.hi);
    assert.ok(close(got.median_chi2, w.chi2.median_chi2), `median @${w.lo}`);
    assert.ok(close(got.p16_chi2, w.chi2.p16_chi2), `p16 @${w.lo}`);
    assert.ok(close(got.p84_chi2, w.chi2.p84_chi2), `p84 @${w.lo}`);
    assert.equal(got.n_stars, w.chi2.n_stars, `n_stars @${w.lo}`);
    assert.equal(got.med_npix, w.chi2.med_npix, `med_npix @${w.lo}`);
  }
});

test("residualMetrics matches Python for every region window", () => {
  for (const w of exp.windows) {
    const got = residualMetrics(meta.common_w, meta.mean_resid, meta.std_resid, w.lo, w.hi);
    for (const k of ["mean_resid", "mean_abs_resid", "p95_abs_resid", "mean_norm_resid"]) {
      assert.ok(close(got[k], w.resid[k]), `${k} @${w.lo}`);
    }
    assert.equal(got.n_grid, w.resid.n_grid, `n_grid @${w.lo}`);
  }
});
```

- [ ] **Step 2: Emit the expectations fixture from Python**

Add to `scripts/export_demo.py` and call it from `main()` after the star export:

```python
# scripts/export_demo.py  (add)
from wave_explorer.data_processing import (
    compute_custom_region_chi2, compute_residual_metrics,
)

FIXTURES = REPO / "tests" / "fixtures"


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
```
Call in `main()`: `emit_compute_fixture(ds)`. Re-run the export (Task 2 Step 4 command) to produce `tests/fixtures/compute_expected.json`.

- [ ] **Step 3: Run the test to verify it fails**

Run: `node --test tests/demo_compute.test.mjs`
Expected: FAIL — `compute.mjs` has no exports yet / cannot find module.

- [ ] **Step 4: Implement `compute.mjs`** (ports of `data_processing.py:433-491,532-565`)

```js
// site/demo/compute.mjs
const finite = (v) => v != null && Number.isFinite(+v);

export function percentile(sorted, q) {       // numpy 'linear' on ascending array
  const n = sorted.length;
  if (n === 0) return NaN;
  if (n === 1) return sorted[0];
  const rank = (q / 100) * (n - 1);
  const lo = Math.floor(rank), hi = Math.ceil(rank);
  if (lo === hi) return sorted[lo];
  return sorted[lo] + (sorted[hi] - sorted[lo]) * (rank - lo);
}
export function median(arr) {
  return percentile([...arr].sort((a, b) => a - b), 50);
}

export function regionChi2ForStar(star, lo, hi) {
  const { w, ff, fm, err } = star;
  let sum = 0, n = 0;
  for (let i = 0; i < w.length; i++) {
    if (w[i] >= lo && w[i] <= hi) {
      const z = (ff[i] - fm[i]) / err[i];
      sum += z * z; n++;
    }
  }
  return n ? { chi2: sum / n, n } : { chi2: NaN, n: 0 };
}

export function customRegionChi2(fitpix, lo, hi) {
  const per = [], npix = [];
  if (hi > lo) {
    for (const slug in fitpix) {
      const { chi2, n } = regionChi2ForStar(fitpix[slug], lo, hi);
      if (finite(chi2)) { per.push(chi2); npix.push(n); }
    }
  }
  if (!per.length) {
    return { median_chi2: NaN, p16_chi2: NaN, p84_chi2: NaN, n_stars: 0, med_npix: 0, per_star_chi2: [] };
  }
  const s = [...per].sort((a, b) => a - b);
  return {
    median_chi2: percentile(s, 50),
    p16_chi2: percentile(s, 16),
    p84_chi2: percentile(s, 84),
    n_stars: per.length,
    med_npix: Math.trunc(median(npix)),
    per_star_chi2: per,
  };
}

function nanmean(arr) {
  let s = 0, n = 0;
  for (const v of arr) if (finite(v)) { s += v; n++; }
  return n ? s / n : NaN;
}
function nanpercentile(arr, q) {
  const ok = arr.filter(finite).sort((a, b) => a - b);
  return ok.length ? percentile(ok, q) : NaN;
}

export function residualMetrics(commonW, meanResid, stdResid, lo, hi) {
  const rv = [], sv = [];
  for (let i = 0; i < commonW.length; i++) {
    if (commonW[i] >= lo && commonW[i] <= hi) { rv.push(meanResid[i]); sv.push(stdResid[i]); }
  }
  // keep grid points where mean_resid is finite (matches Python's `ok` mask)
  const r = [], s = [];
  for (let i = 0; i < rv.length; i++) if (finite(rv[i])) { r.push(rv[i]); s.push(sv[i]); }
  if (r.length < 2) {
    return { n_grid: 0, mean_resid: NaN, mean_abs_resid: NaN, p95_abs_resid: NaN, mean_norm_resid: NaN };
  }
  const absr = r.map(Math.abs);
  const norm = r.map((v, i) => (finite(s[i]) && s[i] > 0 ? Math.abs(v) / s[i] : NaN));
  return {
    n_grid: r.length,
    mean_resid: nanmean(r),
    mean_abs_resid: nanmean(absr),
    p95_abs_resid: nanpercentile(absr, 95),
    mean_norm_resid: nanmean(norm),
  };
}
```

- [ ] **Step 5: Run the test to verify it passes**

Run: `node --test tests/demo_compute.test.mjs`
Expected: PASS — both tests green for every region window. If any window mismatches, the JS port diverges from Python; fix `compute.mjs` (do not relax the test).

- [ ] **Step 6: Check the payload size budget**

Run: `du -h site/payload/meta.json`. If over ~6 MB, reduce `ff/fm/err` precision in `extract_fitpix` (e.g. round to 5 sig-figs) and re-run export + this test. Log the final size.

- [ ] **Step 7: Commit**

```bash
git add site/demo/compute.mjs scripts/export_demo.py tests/demo_compute.test.mjs tests/fixtures/compute_expected.json
git commit -m "feat(demo): JS chi2/residual recompute with Python parity test"
```

---

### Task 6: `render.mjs` — header, heatstrip, default histogram, region table

**Files:**
- Create: `site/demo/render.mjs`
- Modify: `site/demo/main.mjs` (restore the `renderAll` import from Task 4)

**Interfaces:**
- `render.mjs` produces `renderAll(state, ctx)` where `ctx = {handlers, syncSpectrum}`. It fills `#header-chips`, `#status-summary`, `#heatstrip-regions`, `#chi2-histogram` (default view), `#table-body`, and the `#star-select` options. It also exposes (for Task 7) `renderStats(chi2, resid, lo, hi) -> htmlString`, `buildHistogram(values, subtitle, unit) -> htmlString`, and `renderTableRows(rows, llEntries) -> htmlString`.
- Consumes: `chi2Color/Label/Tier/Pct/fmt/C` from `theme.mjs`.

These are 1:1 DOM ports. Use the cited Python as the source of truth for class names and structure: header chips `layout.py:88-112`, heatstrip blocks `build_heatstrip_regions` `layout.py:343-383`, histogram `build_histogram` `layout.py:280-340`, table rows `build_table_row` `layout.py:647-709`, stats `render_stats` `layout.py:450-624`. Reproduce the same `className`s (they are styled by the vendored `styles.css`); reproduce the dynamic inline styles (color, width%, badge background) shown below; the **visual-parity check in Task 10** is the gate that any static inline style copied from those line ranges is faithful.

- [ ] **Step 1: Write `render.mjs`**

```js
// site/demo/render.mjs
import { C, chi2Color, chi2Label, chi2Tier, chi2Pct, fmt } from "./theme.mjs";

const esc = (s) => String(s).replace(/[&<>"]/g, (c) =>
  ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const ROMAN = { "1": "I", "2": "II", "3": "III", "4": "IV", "5": "V" };

export function buildHistogram(values, subtitle, unit = "region") {
  const binW = 2.0, nBins = 22;
  const bins = new Array(nBins).fill(0);
  const vals = (values || []).filter((v) => v != null && Number.isFinite(+v));
  for (const v of vals) bins[Math.min(nBins - 1, Math.max(0, Math.trunc(v / binW)))]++;
  const peak = Math.max(1, ...bins);
  const bars = bins.map((count, i) => {
    const h = ((count / peak) * 100).toFixed(1);
    const bg = chi2Color((i + 0.5) * binW);
    return `<div class="hist-bar" title="χ²/N ${i*binW}–${(i+1)*binW}${i===nBins-1?'+':''} · ${count} ${unit}${count===1?'':'s'}">`
      + `<div class="hist-bar-fill" style="height:${h}%;background:${bg}"></div></div>`;
  }).join("");
  return `<div class="hist-card"><div class="hist-head">`
    + `<span class="eyebrow">χ²/N distribution</span><span class="subtitle">${esc(subtitle)}</span></div>`
    + `<div class="hist-bars">${bars}</div>`
    + `<div class="hist-legend">`
    + `<div class="legend-item"><span class="legend-swatch" style="background:${C.green}"></span>good</div>`
    + `<div class="legend-item"><span class="legend-swatch" style="background:${C.amber}"></span>fair</div>`
    + `<div class="legend-item"><span class="legend-swatch" style="background:${C.orange}"></span>poor</div>`
    + `<div class="legend-item"><span class="legend-swatch" style="background:${C.red}"></span>bad</div></div></div>`;
}

export function renderStats(chi2, resid, lo, hi) {
  const c2 = chi2.median_chi2, color = chi2Color(c2), label = chi2Label(c2), pct = chi2Pct(c2);
  const block = (key, body) => `<div class="stat-block"><div class="stat-key">${key}</div>${body}</div>`;
  const rrow = (k, v) => `<div class="resid-row"><span class="rr-key">${k}</span><span class="rr-val">${v}</span></div>`;
  return `<div>
    <div style="font-family:${C.MONO||"monospace"};font-size:11px;color:${C.muted};margin-bottom:12px;background:${C.bg};padding:6px 10px;border-radius:5px;border:1px solid ${C.border2}">
      λ  ${lo.toFixed(3)} – ${hi.toFixed(3)} nm  ·  Δλ = ${(hi-lo).toFixed(3)} nm</div>
    <div class="stat-grid">
      ${block("χ²/N  median",
        `<div style="display:flex;align-items:baseline;gap:6px">
           <div class="stat-val" style="color:${color}">${fmt(c2, 3)}</div>
           <span><span class="quality-badge" style="color:${color};background:${color}22;border:1px solid ${color}44">${label}</span></span>
         </div>
         <div class="chi2-track"><div class="chi2-fill" style="width:${pct}%;background:${color}"></div></div>`)}
      ${block("χ²/N  16–84%", `<div class="stat-val" style="font-size:14px;color:${C.text}">${fmt(chi2.p16_chi2,2)} – ${fmt(chi2.p84_chi2,2)}</div>`)}
      ${block("Stars", `<div><span class="stat-val" style="color:${C.cyan}">${chi2.n_stars}</span><span class="stat-unit"> ★</span></div>`)}
      ${block("Median pix/star", `<div><span class="stat-val" style="color:${C.text}">${chi2.med_npix}</span><span class="stat-unit"> px</span></div>`)}
    </div>
    <div class="divider"></div>
    <div style="font-family:monospace;font-size:10px;letter-spacing:.1em;text-transform:uppercase;color:${C.dim};margin-bottom:8px">Residual diagnostics</div>
    <div class="resid-grid">
      ${rrow("mean", fmt(resid.mean_resid, 4, true))}
      ${rrow("|mean|", fmt(resid.mean_abs_resid, 4))}
      ${rrow("|p95|", fmt(resid.p95_abs_resid, 4))}
      ${rrow("|res|/σ  mean", fmt(resid.mean_norm_resid, 3))}
      ${rrow("grid pts", String(resid.n_grid || 0))}
    </div></div>`;
}

export function renderTableRows(rows, llEntries) {
  return rows.slice(0, 50).map((row, i) => {
    const col = chi2Color(row.med_chi2);
    const ri = row.region_idx ?? i;
    const excluded = !!(llEntries[ri] && llEntries[ri].excluded);
    const trCls = excluded ? ' class="asap-row-excluded"' : "";
    return `<tr data-region="${ri}"${trCls}>
      <td class="rank-num">${i + 1}</td>
      <td>${row.center.toFixed(3)}</td>
      <td>${row.lower.toFixed(3)} – ${row.upper.toFixed(3)}</td>
      <td style="color:${col};font-weight:700">${row.med_chi2.toFixed(3)}</td>
      <td><span class="q-badge q-${chi2Tier(row.med_chi2)}">${chi2Label(row.med_chi2)}</span></td>
      <td>${row.n_stars}</td>
      <td>${row.med_npix}</td>
      <td><button class="btn btn-xs btn-cyan" data-nav="${ri}" title="Navigate to region">→</button></td>
    </tr>`;
  }).join("");
}

function headerChips(m) {
  const chip = (cls, label, val) => `<div class="h-chip ${cls}">${label} <span class="hc-val">${esc(val)}</span></div>`;
  return chip("c-cyan", "suffix", m.suffix)
    + chip("c-green", "stars", m.nStars)
    + chip("", "λ", `${m.lambdaMin.toFixed(1)} – ${m.lambdaMax.toFixed(1)} nm`)
    + chip("", "ll regions", m.nRegions);
}

export function renderAll(state, ctx) {
  const m = state.manifest, meta = state.meta;
  document.getElementById("header-chips").innerHTML = headerChips(m);
  document.getElementById("status-summary").textContent =
    `Wave Explorer · ASAP · ${m.suffix} · ${m.nStars} stars · ${m.nRegions} regions`;

  // default histogram = median χ²/N of every fitted region
  const defaultVals = meta.region_summary.map((r) => r.med_chi2).filter(Number.isFinite);
  document.getElementById("chi2-histogram").innerHTML =
    buildHistogram(defaultVals, `${defaultVals.length} fitted regions`);

  // heatstrip blocks (build_heatstrip_regions port)
  const span = Math.max(1e-6, m.lambdaMax - m.lambdaMin);
  const chi2Map = new Map(meta.region_summary.map((r) => [r.region_idx, r.med_chi2]));
  document.getElementById("heatstrip-regions").innerHTML = state.llEntries.map((e, idx) => {
    const left = ((e.lower - m.lambdaMin) / span) * 100;
    const width = Math.max(0.18, ((e.upper - e.lower) / span) * 100);
    const c2 = chi2Map.get(idx);
    const bg = c2 != null ? chi2Color(c2) : C.dim;
    return `<div class="heatstrip-region${e.excluded ? " excluded" : ""}" style="left:${left.toFixed(4)}%;width:${width.toFixed(4)}%;background:${bg}"></div>`;
  }).join("");

  // worst-regions table
  document.getElementById("table-body").innerHTML =
    renderTableRows(meta.region_summary, state.llEntries);

  // star-select options
  document.getElementById("star-select").innerHTML =
    m.views.map((v) => `<option value="${esc(v.id)}">${esc(v.label)}</option>`).join("");

  ctx.wire && ctx.wire();          // handler wiring added in Task 7+
}
```

- [ ] **Step 2: Restore the `renderAll` import in `main.mjs`**

Ensure `boot()` ends with:
```js
  const { renderAll } = await import("./render.mjs");
  renderAll(state, { handlers, syncSpectrum, wire: null });
```

- [ ] **Step 3: Verify the panels render (manual)**

Reload the page. Expected: header chips show suffix/stars/λ/regions; the heatstrip shows colored region blocks; the χ²/N histogram renders; the worst-regions table lists 50 rows colored by tier; the star dropdown lists "All stars (mean)", "ds_leo", "gl_581", "gj_1289". No interaction wired yet.

- [ ] **Step 4: Commit**

```bash
git add site/demo/render.mjs site/demo/main.mjs
git commit -m "feat(demo): render header, heatstrip, histogram, table from payload"
```

---

### Task 7: Selected-region interaction — stats panel + table navigation

**Files:**
- Modify: `site/demo/main.mjs`

**Interfaces:**
- Consumes: `customRegionChi2`, `residualMetrics` (Task 5); `renderStats`, `buildHistogram` (Task 6).
- Produces: the `selected-region-store` handler + a `wire()` function (passed to `renderAll`) that delegates table `→`/row clicks. On selection: compute live stats over the region's `[lo,hi]` (honoring local pending edits), render `#candidate-stats` + per-region histogram + `#status-range`, highlight the region via `syncSpectrum`, and frame it on table nav.

- [ ] **Step 1: Add the selection logic to `main.mjs`**

```js
// site/demo/main.mjs  (add imports at top)
import { customRegionChi2, residualMetrics } from "./compute.mjs";

// add near state helpers
function regionBounds(idx) {
  const staged = state.pending[String(idx)];
  const e = (staged && typeof staged === "object") ? staged : state.llEntries[idx];
  return e ? [Number(e.lower), Number(e.upper)] : null;
}

async function renderSelectedStats() {
  const { renderStats, buildHistogram } = await import("./render.mjs");
  const statsEl = document.getElementById("candidate-stats");
  const histEl = document.getElementById("chi2-histogram");
  const rangeEl = document.getElementById("status-range");
  const idx = state.selected && state.selected.region_idx;
  const bounds = idx == null ? null : regionBounds(idx);
  if (!bounds) {
    statsEl.textContent = "Click a region in the spectrum to see statistics.";
    rangeEl.textContent = "";
    const vals = state.meta.region_summary.map((r) => r.med_chi2).filter(Number.isFinite);
    histEl.innerHTML = buildHistogram(vals, `${vals.length} fitted regions`);
    return;
  }
  let [lo, hi] = bounds;
  const c = customRegionChi2(state.meta.fitpix, lo, hi);
  const rs = residualMetrics(state.meta.common_w, state.meta.mean_resid, state.meta.std_resid, lo, hi);
  if (!Number.isFinite(c.median_chi2)) {
    statsEl.innerHTML = `<div style="font-family:monospace;font-size:11px;color:#75705f">λ  ${lo.toFixed(3)} – ${hi.toFixed(3)} nm</div>`
      + `<div style="color:#9c9684;margin-top:8px;font-size:13px">No fitted pixels in this interval.</div>`;
    rangeEl.textContent = `${lo.toFixed(3)} – ${hi.toFixed(3)} nm  ·  no fitted pixels`;
    return;
  }
  statsEl.innerHTML = renderStats(c, rs, lo, hi);
  histEl.innerHTML = buildHistogram(c.per_star_chi2, `Region #${idx + 1}  ·  ${c.n_stars} stars`, "star");
  rangeEl.textContent = `${lo.toFixed(3)} – ${hi.toFixed(3)} nm  ·  χ²/N = ${c.median_chi2.toFixed(3)}`;
}

// register the store handler (fires when spectrum.js / keyboard.js click a region)
handlers["selected-region-store"] = (data) => {
  state.selected = data;            // {region_idx} or null
  syncSpectrum();                   // re-highlight in the plot
  renderSelectedStats();
};

// table navigation wiring (passed into renderAll)
function wire() {
  document.getElementById("table-body").addEventListener("click", (ev) => {
    const navBtn = ev.target.closest("[data-nav]");
    const row = ev.target.closest("[data-region]");
    const idx = navBtn ? Number(navBtn.dataset.nav) : (row ? Number(row.dataset.region) : null);
    if (idx == null) return;
    state.selected = { region_idx: idx };
    state.gotoTick += 1;
    syncSpectrum({ region_idx: idx, tick: state.gotoTick });   // spectrum.js frames the region
    renderSelectedStats();
  });
  document.getElementById("selected-clear-btn").addEventListener("click", () => {
    state.selected = null;
    document.getElementById("selected-region-container").style.display = "none";
    syncSpectrum();
    renderSelectedStats();
  });
}
```

Update the `boot()` tail to pass `wire`:
```js
  renderAll(state, { handlers, syncSpectrum, wire });
```
And in the `selected-region-store` handler + nav, also reflect the selected-region chip:
```js
function showSelectedChip(idx) {
  const cont = document.getElementById("selected-region-container");
  if (idx == null) { cont.style.display = "none"; return; }
  cont.style.display = "";
  document.getElementById("selected-region-label").textContent = `Region #${idx + 1}`;
}
```
Call `showSelectedChip(data ? data.region_idx : null)` in the handler and `showSelectedChip(idx)` in nav.

- [ ] **Step 2: Verify selection works (manual)**

Reload. Click a region in the spectrum → the stats panel fills (χ²/N median + tier badge + 16–84% + stars + pix + residual diagnostics), the histogram switches to the per-star distribution, the status bar shows the range + χ²/N, and the region highlights. Click a table `→` → the plot frames that region and stats update. Click "Deselect" → panel resets to the default histogram. Cross-check a couple of χ²/N values against the live Dash app on the same regions — they must match.

- [ ] **Step 3: Commit**

```bash
git add site/demo/main.mjs
git commit -m "feat(demo): live stats panel + table navigation on region select"
```

---

### Task 8: Drag + draw editing (local-only)

**Files:**
- Modify: `site/demo/main.mjs`

**Interfaces:**
- Consumes: the `drag-result-store` / `draw-region-store` events emitted by `spectrum.js`.
- Produces: handlers that mutate local `state.llEntries` / `state.pending` (no persistence), recompute, re-`syncSpectrum`, refresh stats + heatstrip. Draw mode is toggled via `#draw-mode-toggle` calling `window.activateDrawMode`.

- [ ] **Step 1: Add drag/draw handlers + draw-mode toggle**

```js
// site/demo/main.mjs  (add)
import { chi2Color } from "./theme.mjs";

function refreshHeatstrip() {
  const m = state.manifest;
  const span = Math.max(1e-6, m.lambdaMax - m.lambdaMin);
  const chi2Map = new Map(state.meta.region_summary.map((r) => [r.region_idx, r.med_chi2]));
  document.getElementById("heatstrip-regions").innerHTML = state.llEntries.map((e, idx) => {
    const eff = (state.pending[String(idx)] && typeof state.pending[String(idx)] === "object")
      ? state.pending[String(idx)] : e;
    const left = ((eff.lower - m.lambdaMin) / span) * 100;
    const width = Math.max(0.18, ((eff.upper - eff.lower) / span) * 100);
    const c2 = chi2Map.get(idx);
    const bg = c2 != null ? chi2Color(c2) : "#9c9684";
    return `<div class="heatstrip-region${eff.excluded ? " excluded" : ""}" style="left:${left.toFixed(4)}%;width:${width.toFixed(4)}%;background:${bg}"></div>`;
  }).join("");
}

handlers["drag-result-store"] = (data) => {
  if (!data) return;
  const { region_idx, bound, new_x_nm } = data;          // bound: "lower" | "upper"
  const base = state.llEntries[region_idx];
  if (!base) return;
  const edited = { ...(state.pending[String(region_idx)] || base) };
  edited[bound] = Number(new_x_nm);
  if (edited.lower > edited.upper) { const t = edited.lower; edited.lower = edited.upper; edited.upper = t; }
  state.pending[String(region_idx)] = edited;
  syncSpectrum();                 // redraw shapes with the pending geometry
  if (state.selected && state.selected.region_idx === region_idx) renderSelectedStats();
  refreshHeatstrip();
};

handlers["draw-region-store"] = (data) => {
  if (!data) return;              // {lo, hi}
  state.selected = { region_idx: null, custom: [Number(data.lo), Number(data.hi)] };
  renderCustomStats(Number(data.lo), Number(data.hi));
};

async function renderCustomStats(lo, hi) {
  const { renderStats, buildHistogram } = await import("./render.mjs");
  const c = customRegionChi2(state.meta.fitpix, lo, hi);
  const rs = residualMetrics(state.meta.common_w, state.meta.mean_resid, state.meta.std_resid, lo, hi);
  const statsEl = document.getElementById("candidate-stats");
  const rangeEl = document.getElementById("status-range");
  if (!Number.isFinite(c.median_chi2)) {
    statsEl.innerHTML = `<div style="color:#9c9684;font-size:13px">No fitted pixels in the drawn interval.</div>`;
    rangeEl.textContent = `${lo.toFixed(3)} – ${hi.toFixed(3)} nm · no fitted pixels`;
    return;
  }
  statsEl.innerHTML = renderStats(c, rs, lo, hi);
  document.getElementById("chi2-histogram").innerHTML =
    buildHistogram(c.per_star_chi2, `Drawn region · ${c.n_stars} stars`, "star");
  rangeEl.textContent = `${lo.toFixed(3)} – ${hi.toFixed(3)} nm · χ²/N = ${c.median_chi2.toFixed(3)} (drawn)`;
}

// draw-mode toggle button
document.getElementById("draw-mode-toggle").addEventListener("click", () => {
  state.drawActive = !state.drawActive;
  window.activateDrawMode(state.drawActive);
  document.getElementById("draw-mode-toggle").classList.toggle("btn-primary", state.drawActive);
});
```

(`renderSelectedStats` must be hoisted/defined before these handlers, or declared with `function`. Move its definition above the `handlers[...]` assignments if needed.)

- [ ] **Step 2: Verify drag + draw work (manual)**

Reload. Drag a region's edge → the shape moves and, if that region is selected, its χ²/N updates live; the heatstrip block resizes. Click "Draw Region", click-drag a new span on the plot, accept in the popover → the stats panel shows the drawn window's χ²/N across stars. Confirm nothing persists: reload the page and edits are gone (expected — local-only).

- [ ] **Step 3: Commit**

```bash
git add site/demo/main.mjs
git commit -m "feat(demo): local-only drag + draw editing with live recompute"
```

---

### Task 9: Star switcher + VALD controls

**Files:**
- Modify: `site/demo/main.mjs`

**Interfaces:**
- Consumes: `manifest.views`, `star_<slug>.json`; the `#star-select`, `#vald-toggle-btn`, `#vald-depth-min-slider` controls.
- Produces: view switching (mean ↔ full-range star) and VALD visibility/depth wiring, all via `syncSpectrum`.

- [ ] **Step 1: Add the switcher + VALD wiring**

```js
// site/demo/main.mjs  (add)
async function loadView(viewId) {
  if (!state.specByView[viewId]) {
    const v = state.manifest.views.find((x) => x.id === viewId);
    if (!v) return;
    state.specByView[viewId] = await getJSON(v.file);
  }
  state.view = viewId;
  syncSpectrum();      // spectrum.js resets to full λ-range when payload has fullRange:true
}

document.getElementById("star-select").addEventListener("change", (ev) => {
  loadView(ev.target.value);
});

document.getElementById("vald-toggle-btn").addEventListener("click", () => {
  state.valdVisible = !state.valdVisible;
  document.getElementById("vald-toggle-btn").classList.toggle("btn-primary", state.valdVisible);
  syncSpectrum();
});

document.getElementById("vald-depth-min-slider").addEventListener("input", (ev) => {
  state.valdDepthMin = Number(ev.target.value);
  syncSpectrum();
});
```

- [ ] **Step 2: Verify view switching + VALD (manual)**

Reload. Switch the dropdown to `ds_leo` → the plot loads that star's full-range spectrum (lines outside the fitted windows now visible) and resets the view to the full range; switch back to "All stars (mean)" → the windowed mean view returns. Toggle "VALD lines" → atomic/molecular line markers appear; move the min-depth slider → shallow lines filter out. Each star (`ds_leo`, `gl_581`, `gj_1289`) loads without error.

- [ ] **Step 3: Commit**

```bash
git add site/demo/main.mjs
git commit -m "feat(demo): star full-range switcher + VALD toggle/depth controls"
```

---

### Task 10: Explainer banner, local-only note, thesis link, visual-parity pass

**Files:**
- Modify: `site/index.html` (banner copy)
- Modify: `site/demo/main.mjs` (fill `#demo-note`)
- Create: `site/assets/demo.css` (banner styles; linked from `index.html`)

**Interfaces:**
- Produces: the reviewer-facing framing and a final faithfulness check against the live Dash app.

- [ ] **Step 1: Add the banner content + demo note**

In `index.html`, fill `#demo-banner`:
```html
  <div id="demo-banner" class="demo-banner">
    <h1>Wave Explorer</h1>
    <p>An interactive line-curation dashboard for ASAP magnetic-field retrievals.
       This is a live demo running entirely in your browser on <strong>preloaded
       <code>ds_leo</code>-campaign data</strong> — see the thesis for the science and methodology.</p>
    <p class="demo-hints"><strong>Try:</strong> scroll to zoom · drag to pan · click a region for its χ²/N statistics ·
       drag a region edge or use “Draw Region” to test curation · switch stars for the full-range model.
       <em>Edits are local to your browser and are not saved.</em></p>
    <p><a href="THESIS_URL_OR_DOI" target="_blank" rel="noopener">← Back to the thesis</a></p>
  </div>
```
(Replace `THESIS_URL_OR_DOI` with the final thesis URL/DOI when known.)

Add `<link rel="stylesheet" href="assets/demo.css" />` to `<head>`, and create `site/assets/demo.css`:
```css
.demo-banner { max-width: 1100px; margin: 24px auto 8px; padding: 0 20px; font-family: 'Inter', system-ui, sans-serif; color: #1a1814; }
.demo-banner h1 { font-family: 'Fraunces', Georgia, serif; margin: 0 0 6px; }
.demo-banner p { margin: 6px 0; line-height: 1.5; color: #4a4639; }
.demo-banner code { background: #efe9d8; padding: 1px 5px; border-radius: 4px; }
.demo-banner .demo-hints { font-size: 14px; color: #75705f; }
.demo-banner a { color: #b3553b; }
```

In `main.mjs`, set the header note:
```js
document.getElementById("demo-note").textContent = "demo · edits local to your browser";
```

- [ ] **Step 2: Side-by-side visual parity check**

Run the live Dash app and the static demo together and compare on `ds_leo`:
```bash
# live
cd /net/vdesk/data2/cobelens/MRP/new/obs-data-example
/net/vdesk/data2/cobelens/.conda/envs/asap/bin/python -m wave_explorer --suffix ds_leo
# static (separate terminal)
cd /net/vdesk/data2/cobelens/MRP/new/obs-data-example/wave_explorer/site
/net/vdesk/data2/cobelens/.conda/envs/asap/bin/python -m http.server 8123
```
Checklist (fix any divergence in `render.mjs`/`index.html` against the cited `layout.py` lines): header chips, spectrum obs/fit/resid, region shapes, cursor tooltip, heatstrip colors/positions, stats panel layout, histogram bars/legend, table rows + tier badges + colors, VALD overlay. The plot/drag/draw/tooltip come from the same `spectrum.js`, so they should be identical by construction.

- [ ] **Step 3: Commit**

```bash
git add site/index.html site/assets/demo.css site/demo/main.mjs
git commit -m "feat(demo): explainer banner, local-only note, thesis link + parity polish"
```

---

### Task 11: Publish to gh-pages + document the rebuild

**Files:**
- Create: `scripts/publish_gh_pages.sh`
- Modify: `README.md` (a "Static demo" section)

**Interfaces:**
- Produces: a one-command publish of `site/` to the `gh-pages` branch, and the documented rebuild procedure + URL.

- [ ] **Step 1: Write the publish script**

```bash
# scripts/publish_gh_pages.sh
#!/usr/bin/env bash
# Publish the prebuilt static demo (site/) to the gh-pages branch.
# Payloads must already be exported (scripts/export_demo.py) and committed/present.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
test -f site/index.html || { echo "site/index.html missing — build first"; exit 1; }
test -f site/payload/manifest.json || { echo "payloads missing — run export_demo.py"; exit 1; }
# git subtree push requires site/ to be committed on the current branch.
git add site && git commit -m "build: refresh static demo site" || echo "nothing to commit"
git subtree split --prefix site -b gh-pages-tmp
git push -f origin gh-pages-tmp:gh-pages
git branch -D gh-pages-tmp
echo "Published. URL: https://dionco.github.io/wave_explorer/"
```
Make it executable: `chmod +x scripts/publish_gh_pages.sh`.

- [ ] **Step 2: Document in `README.md`**

Add a section:
```markdown
## Static demo (GitHub Pages)

A fully interactive, server-free demo runs on preloaded `ds_leo` data at
**https://dionco.github.io/wave_explorer/**.

Rebuild (on the machine with the `asap` env + data + model grid):

    cd new/obs-data-example
    /net/vdesk/data2/cobelens/.conda/envs/asap/bin/python -m scripts.export_demo \
        --built-at "$(date +%F)" \
        --grid-path /net/vdesk/data2/cobelens/MRP/new/grid_models/hdf5-narval-full/
    node --test wave_explorer/tests/demo_compute.test.mjs   # parity gate
    bash wave_explorer/scripts/publish_gh_pages.sh

The demo is read-with-local-editing: drags/draws recompute χ² live but nothing
persists. The single-star full-range views (`ds_leo`, `gl_581`, `gj_1289`)
require a one-time `model-full.fits` precompute, handled by the export script.
```

- [ ] **Step 3: Publish and verify (manual)**

Run `bash scripts/publish_gh_pages.sh`, then in the GitHub repo settings enable Pages → Branch `gh-pages` / root, and confirm the repo is **public**. Wait for the build, then open `https://dionco.github.io/wave_explorer/` and run the Task 10 interaction checklist against the live URL.

- [ ] **Step 4: Commit**

```bash
git add scripts/publish_gh_pages.sh README.md
git commit -m "docs(demo): publish script + rebuild instructions + Pages URL"
```

---

## Self-Review

**1. Spec coverage**
- Exploration (pan/zoom/hover/click/table/VALD): Tasks 4,6,7,9 — covered (mostly inherited from `spectrum.js`). ✓
- In-browser editing (drag/draw, local-only, live χ²): Task 8 + compute Task 5. ✓
- Preloaded mean + full-range `ds_leo`/`gl_581`/`gj_1289`: Tasks 1,2,9. ✓
- gh-pages hosting + URL: Task 11. ✓
- Light explainer banner + thesis link: Task 10. ✓
- No persistence/no save: enforced by design (Task 8) + note (Task 10). ✓
- Reuse `spectrum.js` etc. verbatim: Task 3 vendoring + untouched constraint. ✓
- Compute parity gate: Task 5. ✓
- model-full pre-warm: Task 2. ✓
- Thesis URL placement: noted in Task 10 (actual thesis-repo edit is out of scope, per spec §6). ✓

**2. Placeholder scan:** `THESIS_URL_OR_DOI` in Task 10 is an intentional, flagged substitution (the URL is not yet minted), not a logic gap. No "TBD"/"handle edge cases"/"write tests for the above" placeholders remain.

**3. Type consistency:** `WaveExplorer.sync(specData, llEntries, pending, selected, drawActive, goto, vald, valdVisible, valdDepthMin)` used consistently in `syncSpectrum`. Store ids match the spec contract: `selected-region-store {region_idx}`, `drag-result-store {region_idx,bound,new_x_nm}`, `draw-region-store {lo,hi}`. `customRegionChi2`/`residualMetrics`/`regionChi2ForStar` signatures match between `compute.mjs`, the test, and `main.mjs`. `extract_fitpix` returns `{w,ff,fm,err}` used identically by the test, the meta export, and `regionChi2ForStar`.

## Execution Handoff

After saving this plan, choose an execution approach (subagent-driven vs inline).
