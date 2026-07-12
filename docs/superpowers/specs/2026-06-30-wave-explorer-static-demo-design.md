# Wave Explorer — Static GitHub Pages Demo

**Date:** 2026-06-30
**Status:** Design (awaiting review)
**Target repo:** `Dionco/wave_explorer`
**Published URL (goal):** `https://dionco.github.io/wave_explorer/`

## 1. Purpose

Publish a publicly accessible, fully interactive demo of `wave_explorer` so that
thesis reviewers can open a URL and *use* the tool on preloaded data — without
installing anything, running Python, or having access to the retrieval data or
the model grid. The URL goes into the thesis next to the `wave_explorer` figure.

The demo must run on **GitHub Pages**, which serves only static files (no Python,
no Flask, no server-side callbacks).

## 2. Goals & non-goals

### Goals
- Reviewers can, on preloaded data:
  - pan / zoom the spectrum, hover for per-region χ²/N tooltips
  - click a region to see its live statistics panel + χ²/N histogram
  - browse and filter the "worst regions" table; navigate to a region
  - toggle the VALD line overlay and its depth-min slider
  - **drag region boundaries and draw new candidate regions**, with the
    statistics panel recomputing χ²/N live for the edited/drawn window
  - switch the spectrum view between the campaign **mean view** and a few
    **single-star full-range** views
- The demo is permanent and low-maintenance: nothing to keep running, nothing
  that spins down or rots. Pure static assets + JSON.

### Non-goals (explicitly out of scope)
- **No persistence.** Edits (drags/draws) live only in the visitor's browser
  session; there is no "save to disk" and no server state. The save/discard/
  pending UI is replaced by a quiet "changes are local to your browser" note.
- **No live full-range model recompute.** The single-star full-range views are
  *precomputed* and read-only. The on-focus auto-compute subprocess (which needs
  ASAP + the ~350 MB model grid) is removed from the demo.
- **No multi-user / no backend.** Zero network traffic after the initial asset
  load.

## 3. Key decisions (locked)

| Decision | Choice |
|---|---|
| Demo fidelity | Exploration **+ in-browser editing** (drag/draw live, local-only) |
| Preloaded views | `ds_leo` campaign **mean view** (core) **+ a few single-star full-range views** |
| Hosting | **`gh-pages` branch** of `Dionco/wave_explorer` → `https://dionco.github.io/wave_explorer/` |
| Framing | **Light explainer banner** above the tool |

### Resolved during review
- **(a)** Editing is local-only; there is **no "save" of any kind** in the public
  demo (no download button either).
- **(b)** The bundled full-range views are an **explicit slug list**:
  **`ds_leo`, `gl_581`, `gj_1289`** — all verified present in the example
  campaign with `*_ds_leo` retrieval folders containing `fit-data.fits`.
- **(c)** The maintainer runs the one-time `export_demo.py` and `model-full.fits`
  pre-warm **on this machine** (where the `asap` env, the retrieval data, and the
  model grid exist). CI never rebuilds the payloads.
- **(d)** The `Dionco/wave_explorer` repo will be **public**, so the Pages URL
  resolves for reviewers.

## 4. Architecture

### 4.1 The integration boundary that makes this cheap

`spectrum.js` already renders the *entire* spectrum client-side: the SVG plot,
region shapes, VALD overlay, cursor tooltip, edge-drag, and draw mode. It has a
narrow, well-defined interface:

- **State in:** `window.WaveExplorer.sync(specData, entries, pending, selected,
  drawActive, goto, vald, valdVisible, valdDepthMin)`. Before init, the same
  argument list can be parked on `window.__weSpectrumPending` and `init()`
  replays it.
- **Events out:** exactly one channel — `window.dash_clientside.set_props(storeId,
  {data})`:
  - `selected-region-store` ← `{region_idx}` on region click (or `null` to clear)
  - `drag-result-store` ← `{region_idx, bound, new_x_nm}` on edge-drag commit
  - `draw-region-store` ← `{lo, hi}` on draw-confirm accept
- `heatstrip.js` uses only `WaveExplorer.getView/setView/onViewChange` (pure
  client-side). `keyboard.js` emits via the same `set_props` channel.

**Consequence:** the four vendored JS/CSS files (`spectrum.js`, `heatstrip.js`,
`keyboard.js`, `styles.css`) are reused **byte-for-byte**. The only things that
must be rebuilt for a static site are (1) the surrounding panels currently built
by `layout.py`, and (2) the handful of server callbacks in `callbacks/*.py` and
compute functions in `data_processing.py` — reimplemented as a small vanilla-JS
controller that intercepts `set_props`.

### 4.2 Components

```
site/
├── index.html         # explainer banner + tool DOM skeleton (exact layout.py IDs/classes)
├── assets/
│   ├── spectrum.js     # vendored verbatim
│   ├── heatstrip.js    # vendored verbatim
│   ├── keyboard.js     # vendored verbatim
│   └── styles.css      # vendored verbatim
├── demo.js            # NEW: the static controller (replaces Dash server)
└── payload/
    ├── manifest.json   # available views + metadata
    ├── mean.json       # build_spectrum_payload(dataset)
    ├── fitpix.json     # per-star fitted pixels + resid arrays + region_summary + ll_entries + vald_payload
    └── star_<slug>.json  # build_single_star_payload(...) for each bundled full-range star
```

#### `site/index.html`
- A light explainer banner: title, one-paragraph "what this is", a "preloaded
  demo data — see the thesis for context" note, brief usage hints (pan/zoom,
  click a region, drag edges, draw), and a link back to the thesis.
- Below it, the tool's DOM skeleton reproducing the structure from
  `layout.build_layout`, **using the same element IDs and CSS classes** so the
  vendored `styles.css` renders it identically (key IDs: `spectrum-graph`,
  `candidate-stats`, `chi2-histogram`, `status-range`, `table-body`,
  `heatstrip*`, `star-select`, `vald-toggle-btn`, `vald-depth-min-slider`,
  `draw-mode-toggle`, the `selected-region-*` controls, etc.).
- `<script>` tags load the vendored assets, then `demo.js`.

#### `site/demo.js` (the controller — the bulk of the new work)
1. **Dash shim.** Install `window.dash_clientside = { no_update: <sentinel>,
   set_props(id, payload) }`. `set_props` switches on `id` and routes to the
   appropriate local handler. This is the single universal integration point —
   it captures events from `spectrum.js` and `keyboard.js` unchanged.
2. **Bootstrap.** `fetch` `manifest.json` then `mean.json` + `fitpix.json`; build
   the initial `sync` argument list and set `window.__weSpectrumPending`
   (spectrum.js `init()` replays it). Render the static panels.
3. **Ported renderers** (translate the corresponding `layout.py` builders to JS
   string templates — 1:1, same markup/classes):
   - `render_stats(chi2, resid, lo, hi)` → stats panel DOM
   - `build_histogram(values, label, unit)` → χ²/N histogram SVG/DOM
   - `build_table_row` / `build_table_panel` → worst-regions table rows, element
     filter, and per-row nav buttons
   - selected-region header chrome (label, clear; exclude/restore/delete become
     local-only toggles or are hidden)
   - VALD toggle + depth-min slider behavior; star-select dropdown
4. **Ported compute** (translate from `data_processing.py`, ~30 lines each):
   - `compute_region_chi2_for_star(fitpix_star, lo, hi)` — mean of
     `((ff-fm)/err)²` over fitted pixels in `[lo,hi]`, + pixel count
   - `compute_custom_region_chi2(fitpix_all, lo, hi)` — median/p16/p84 across
     stars + `per_star_chi2`
   - `compute_residual_metrics(mean_resid, std_resid, w, lo, hi)`
5. **Interaction handlers** (all local, no persistence):
   - `selected-region-store` → look up bounds (respecting any local pending
     edit), `compute_custom_region_chi2` + `compute_residual_metrics`, render
     stats + per-region histogram + `status-range`.
   - `drag-result-store` → update the local `ll_entries` geometry for that
     region, recompute its χ², re-`sync()` so spectrum.js redraws the shape, and
     refresh the stats panel. Mark a transient "local change" indicator.
   - `draw-region-store` → set the candidate range `[lo,hi]`, compute custom χ²,
     render stats. Optionally append a session-only candidate region.
6. **Star switching.** The `star-select` dropdown lists `mean` + each bundled
   full-range slug. Selecting a star fetches `star_<slug>.json` (cached after
   first load) and re-`sync()`s spectrum.js with `fullRange: true`. The
   full-model spinner / auto-compute path is removed.

#### `scripts/export_demo.py` (run once on this machine, `asap` env)
Generates the `site/payload/` bundle. Steps:
1. `dataset = build_dataset(retrievals_dir, suffix="ds_leo", line_list_path=…,
   grid_step_nm=…, smooth_window=…, vald_path=…)`.
2. Write `payload/mean.json = build_spectrum_payload(dataset)`.
3. Write `payload/fitpix.json`: for each star in `dataset["fit_data_cache"]`,
   emit the **fitted pixels only** as `{slug: [{w, ff, fm, err}, …]}` (derived
   exactly as `compute_region_chi2_for_star` reads them: per order, restrict to
   `idxtofit`, convert `wvl/10` to nm, keep `flux_fit`, `fit`, `error`). Also
   include `mean_resid`, `std_resid`, `common_w` (for residual metrics),
   `region_summary`, `ll_entries`, and `vald_payload`.
4. Build the full-range views for the fixed slug list **`ds_leo`, `gl_581`,
   `gj_1289`**. For each: ensure `model-full.fits` exists (call the existing
   `wave_explorer.full_model` driver, honoring `--grid-path`/`--cache-dir`), then
   write `payload/star_<slug>.json = build_single_star_payload(fit_data,
   dataset)` plus its `build_single_star_vald_payload(...)`.
5. Write `payload/manifest.json` (view list, λ-range, star metadata, build
   timestamp, source suffix/line-list for provenance).
6. Floats are emitted compactly (round residuals/arrays to a sane precision, as
   `build_single_star_payload` already does for resid) to control size.

### 4.3 Runtime data flow (all in-browser)

```
index.html
  └─ demo.js: fetch manifest.json → mean.json + fitpix.json
       ├─ install window.dash_clientside shim (no_update, set_props)
       ├─ window.__weSpectrumPending = [meanPayload, llEntries, {}, null,
       │                                 false, null, valdPayload, false, 0]
       │       └─ spectrum.js init() replays → renders SVG
       └─ render panels/table/stats from payload
  ── user interacts ──
  spectrum.js / keyboard.js → set_props(storeId, {data})
       └─ shim → demo.js handler → recompute locally
            ├─ re-sync() spectrum.js (geometry/selection/view)
            └─ re-render stats / histogram / table
  (zero network after initial load)
```

## 5. Publishing pipeline

- The payloads can only be built where the data + grid + `asap` env live (this
  machine), so **CI cannot regenerate them**. The model is: build locally →
  publish the static `site/` directory to the `gh-pages` branch.
- Provide a small `scripts/publish_gh_pages.sh` (or `make publish`) that mirrors
  `site/` to the `gh-pages` branch and pushes. (No commit performed
  automatically by the assistant — the maintainer runs/commits per their
  workflow.)
- Enable GitHub Pages on the `gh-pages` branch (root). Confirm the repo is
  public so the URL resolves for reviewers.
- Document the exact URL and the rebuild steps in the repo README.

## 6. Thesis integration

- Add `https://dionco.github.io/wave_explorer/` near the `wave_explorer` figure,
  e.g. a `\url{}` footnote or a sentence in the tools/methods section ("an
  interactive demo on preloaded data is available at …").
- Optional: a QR code beside the figure for the print version.
- (Thesis edits happen in the thesis repo and are out of scope for the
  wave_explorer build; this spec only notes the wording/placement.)

## 7. Testing strategy

- **Compute parity:** unit-test the ported JS compute against the Python
  functions on the exported payload — for a set of `[lo,hi]` windows (every
  line-list region + several arbitrary windows), the JS `compute_custom_region_
  chi2` / `compute_residual_metrics` must match `data_processing.py` within
  float tolerance. (Drive Python from `export_demo.py`; compare to JS via a small
  Node harness or a headless-browser assertion.)
- **Visual parity:** open the static site and the local Dash app side by side on
  `ds_leo`; confirm the header, stats panel, histogram, table, heatstrip, and
  VALD overlay look and behave the same.
- **Interaction smoke test:** click a region (stats update), drag an edge (shape
  moves + χ² updates, no errors), draw a region (candidate stats appear), toggle
  VALD + slider, switch to each bundled full-range star and back to mean.
- **Payload size check:** assert the total `payload/` size (esp. `fitpix.json`)
  stays within a budget (target: a few MB pre-gzip); the export script logs
  per-file sizes.
- **No-network check:** after load, the network panel shows no further requests
  during interaction.

## 8. Risks & mitigations

| Risk | Mitigation |
|---|---|
| Faithful chrome reproduction (porting ~5 DOM builders to JS) | Reuse `styles.css` verbatim; keep IDs/classes identical; side-by-side visual test vs local Dash. |
| `fitpix.json` size (~42 stars) | Ship **only fitted pixels** (small fraction of each spectrum); measure in export; Pages gzips; fall back to fewer stars / coarser float precision if over budget. |
| `model-full.fits` precompute needs ASAP + grid | One-time, on this machine; documented with `--grid-path` override; pick stars whose grid corners exist. |
| `spectrum.js` assumes Dash store semantics in edge cases | The shim provides every store id it touches as plain state; verify the drag *preview* is pure-JS (per the SVG-rewrite design) and only the *commit* needs interception. |
| Compute drift between JS port and Python | Compute-parity test (§7) gates correctness. |

## 9. Effort estimate

~**1.5–2 days**: most of it is `demo.js` (controller + ported renderers/compute)
and the `index.html` skeleton; `export_demo.py` ~half a day; publishing + thesis
URL ~1 hour.

## 10. Review outcome

All open questions resolved (see §3 "Resolved during review"):
1. Editing is local-only, no save / no download. ✓
2. Bundled full-range stars: explicit list `ds_leo`, `gl_581`, `gj_1289`. ✓
3. Maintainer runs `export_demo.py` + `model-full.fits` pre-warm on this machine. ✓
4. Repo will be public. ✓
