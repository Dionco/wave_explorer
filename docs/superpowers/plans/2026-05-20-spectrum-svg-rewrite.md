# Spectrum SVG Rewrite Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the Plotly main graph in `wave_explorer` with a custom inline-SVG spectrum component that reproduces the Claude Design `spectrum.jsx` interaction model (smooth pan/zoom, χ²-quality region coloring, visible drag handles on the selected region, cursor crosshair + tooltip).

**Architecture:** A new vanilla-JS module `assets/spectrum.js` renders an inline `<svg>` into a plain `html.Div` host and owns all interaction. A `dcc.Store` carries static spectrum data to the browser; region geometry/state stays in the existing `ll-entries-store` / `pending-changes-store`. All Python persistence callbacks (`drag-result-store`, `draw-region-store`, `selected-region-store`) are unchanged — only the rendering layer is replaced.

**Tech Stack:** Python 3.9, Dash 4.1, vanilla JS (no build step, matches existing `assets/*.js`), pytest 8.3 for the one pure-Python unit.

**Conventions:**
- Per the repo owner's standing preference, **no git commit steps** are included. Commit yourself when ready.
- JS has no unit-test harness in this project. JS tasks are verified by running the app (`python -m wave_explorer --suffix ds_leo` from `new/obs-data-example/`) and checking behavior — the project's own "Done Criteria" from `.github/instructions/wave-explorer.instructions.md`.
- Spec: `docs/superpowers/specs/2026-05-20-spectrum-svg-rewrite-design.md`.

---

## File Structure

**Create:**
- `wave_explorer/tests/test_spectrum_payload.py` — unit test for the data payload builder.
- `wave_explorer/assets/spectrum.js` — the SVG renderer + interaction module.

**Modify:**
- `wave_explorer/theme.py` — expose χ² thresholds + element color map.
- `wave_explorer/data_processing.py` — add `build_spectrum_payload(dataset)`.
- `wave_explorer/layout.py` — replace `dcc.Graph` host with `html.Div`, add `spectrum-data-store`, restructure cursor-tooltip; drop the `base_fig` parameter.
- `wave_explorer/app.py` — drop `build_base_figure`; replace Plotly hover/click clientside callbacks with one spectrum-sync callback.
- `wave_explorer/callbacks/candidate.py` — remove the `update_figure_shapes` Plotly figure callback (keep `nav_to_region`, `update_stats`).
- `wave_explorer/assets/styles.css` — add SVG spectrum classes + dark tooltip classes.
- `wave_explorer/assets/heatstrip.js` — read/write the view through `window.WaveExplorer` instead of Plotly.

**Delete:**
- `wave_explorer/figure_builder.py`
- `wave_explorer/assets/drag_handles.js`
- `wave_explorer/assets/tooltip.js`

All paths below are relative to `new/obs-data-example/wave_explorer/` unless noted. Run commands from `new/obs-data-example/`.

---

## Task 1: χ² thresholds + element colors in theme.py

**Files:**
- Modify: `theme.py`

- [ ] **Step 1: Add the threshold list and element palette to `theme.py`**

Append after the existing `chi2_pct` function (the colors mirror the design's `--elem-*` palette in `styles.css`):

```python
# χ²/N quality thresholds as a list, for client-side serialization.
# [good_max, fair_max, poor_max] — tier is good < 5, fair < 15, poor < 30, bad >= 30.
CHI2_THRESHOLDS = [_CHI2_GOOD, _CHI2_FAIR, _CHI2_BAD]

# Per-element rail colors (warm editorial palette — Claude Design handoff).
ELEMENT_COLORS = {
    "Fe": "#4a6c8a",
    "Mg": "#7a4f7e",
    "Ca": "#2e7a64",
    "Na": "#b88829",
    "Si": "#8a4a4a",
    "Ni": "#6c5a8e",
    "Ti": "#2e6a8a",
}
ELEMENT_COLOR_FALLBACK = "#75705f"
```

- [ ] **Step 2: Verify the module imports**

Run: `cd new/obs-data-example && python -c "from wave_explorer.theme import CHI2_THRESHOLDS, ELEMENT_COLORS, ELEMENT_COLOR_FALLBACK; print(CHI2_THRESHOLDS, len(ELEMENT_COLORS))"`
Expected: `[5.0, 15.0, 30.0] 7`

---

## Task 2: `build_spectrum_payload` in data_processing.py (TDD)

The payload builder is a pure transform of the `dataset` dict into a JSON-serializable structure for `spectrum-data-store`. It is the one piece with enough pure logic to unit-test.

**Files:**
- Create: `tests/test_spectrum_payload.py`
- Modify: `data_processing.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_spectrum_payload.py`:

```python
"""Unit test for build_spectrum_payload — the spectrum-data-store builder."""
import json
import math

from wave_explorer.data_processing import build_spectrum_payload


def _fake_dataset():
    """Minimal dataset dict with the fields build_spectrum_payload reads."""
    return {
        "common_w": [515.0, 515.5, 516.0, 516.5],
        "mean_obs_s": [1.0, 0.8, 0.9, 1.0],
        "mean_fit_s": [1.0, 0.82, 0.88, 1.0],
        "mean_resid_s": [0.0, -0.02, 0.02, 0.0],
        "ll_entries": [
            {"lower": 515.1, "upper": 515.3, "element": "Fe", "ion": "1"},
            {"lower": 515.8, "upper": 516.1, "element": "Mg", "ion": "2"},
        ],
        "ll_hover_stats": [
            {"region_idx": 1, "n_stars": 30, "med_npix": 6},
            {"region_idx": 2, "n_stars": 25, "med_npix": 5},
        ],
        "region_summary": [
            {"region_idx": 0, "med_chi2": 3.2},
            {"region_idx": 1, "med_chi2": float("nan")},
        ],
    }


def test_payload_has_arrays_and_bounds():
    p = build_spectrum_payload(_fake_dataset())
    assert p["wavelengths"] == [515.0, 515.5, 516.0, 516.5]
    assert p["flux"] == [1.0, 0.8, 0.9, 1.0]
    assert p["fitFlux"] == [1.0, 0.82, 0.88, 1.0]
    assert p["resid"] == [0.0, -0.02, 0.02, 0.0]
    assert p["lambdaMin"] == 515.0
    assert p["lambdaMax"] == 516.5


def test_payload_regions_carry_chi2_and_stats():
    p = build_spectrum_payload(_fake_dataset())
    assert len(p["regions"]) == 2
    r0, r1 = p["regions"]
    assert r0 == {"idx": 0, "chi2": 3.2, "n_stars": 30, "n_pix": 6}
    # region_summary has no entry keyed 1 with a finite chi2 -> None
    assert r1["idx"] == 1 and r1["chi2"] is None
    assert r1["n_stars"] == 25 and r1["n_pix"] == 5


def test_payload_thresholds_and_element_colors():
    p = build_spectrum_payload(_fake_dataset())
    assert p["chi2Thresholds"] == [5.0, 15.0, 30.0]
    assert p["elementColors"]["Fe"] == "#4a6c8a"
    assert p["elementColorFallback"] == "#75705f"


def test_payload_is_json_serializable():
    p = build_spectrum_payload(_fake_dataset())
    # Must round-trip cleanly — no numpy scalars, no NaN leaking as float.
    text = json.dumps(p, allow_nan=False)
    assert isinstance(text, str)
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd new/obs-data-example && python -m pytest wave_explorer/tests/test_spectrum_payload.py -v`
Expected: FAIL — `ImportError: cannot import name 'build_spectrum_payload'`.

- [ ] **Step 3: Implement `build_spectrum_payload`**

Add to `data_processing.py`. Put the import at the top with the other imports:

```python
import math

from .theme import CHI2_THRESHOLDS, ELEMENT_COLORS, ELEMENT_COLOR_FALLBACK
```

Add this function at module scope (near the other public builders):

```python
def build_spectrum_payload(dataset: dict) -> dict:
    """Build the JSON-serializable payload for the spectrum-data-store.

    Carries the static data the client-side SVG renderer needs: the
    obs/fit/resid arrays, the wavelength axis, and a per-region χ² + star
    count list aligned to ll_entries by 0-based index.

    χ² is keyed by region_summary's `region_idx` (region_summary may be a
    subset of ll_entries — only regions with a fit). Star/pixel counts come
    from ll_hover_stats, which build_base_figure keeps 1:1 with ll_entries
    by position. Non-finite χ² becomes None so the payload is strict-JSON.
    """
    def _floats(seq):
        return [float(v) for v in seq]

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

    wavelengths = _floats(dataset["common_w"])
    return {
        "wavelengths": wavelengths,
        "flux": _floats(dataset["mean_obs_s"]),
        "fitFlux": _floats(dataset["mean_fit_s"]),
        "resid": _floats(dataset["mean_resid_s"]),
        "lambdaMin": wavelengths[0],
        "lambdaMax": wavelengths[-1],
        "regions": regions,
        "chi2Thresholds": [float(t) for t in CHI2_THRESHOLDS],
        "elementColors": dict(ELEMENT_COLORS),
        "elementColorFallback": ELEMENT_COLOR_FALLBACK,
    }
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd new/obs-data-example && python -m pytest wave_explorer/tests/test_spectrum_payload.py -v`
Expected: PASS — all 4 tests green.

---

## Task 3: Layout — div host + spectrum-data-store

**Files:**
- Modify: `layout.py`
- Modify: `app.py`

- [ ] **Step 1: Add the payload import to `layout.py`**

In `layout.py`, add `build_spectrum_payload` to the existing `data_processing` import. If `layout.py` has no such import yet, add at the top:

```python
from .data_processing import build_spectrum_payload
```

- [ ] **Step 2: Replace the `dcc.Graph` host with a div**

In `layout.py`, inside `build_layout`, replace the entire `dcc.Graph(...)` element (the `id="spectrum-graph"` block, currently `layout.py:821-837`) AND the sibling `drag-handles-overlay` div (`layout.py:838-849`) with a single host div:

```python
                                    html.Div(
                                        id="spectrum-graph",
                                        className="spectrum-canvas",
                                    ),
```

The `spectrum-canvas-wrap` parent div stays.

- [ ] **Step 3: Add the `spectrum-data-store`**

In `layout.py`, in the hidden-stores block, add next to `ll-entries-store`:

```python
            dcc.Store(
                id="spectrum-data-store",
                data=build_spectrum_payload(dataset),
            ),
```

- [ ] **Step 4: Restructure the cursor-tooltip div**

In `layout.py`, replace the `html.Div(id="cursor-tooltip", ...)` block (`layout.py:904-921`) with a class-styled empty container — `spectrum.js` fills `innerHTML`:

```python
            html.Div(id="cursor-tooltip", className="cursor-tooltip",
                     style={"display": "none"}),
```

- [ ] **Step 5: Drop the `base_fig` parameter from `build_layout`**

In `layout.py`, change the signature `def build_layout(dataset: dict, base_fig, debug_hover: bool = False)` to:

```python
def build_layout(dataset: dict, debug_hover: bool = False) -> html.Div:
```

- [ ] **Step 6: Update `app.py` to stop building the Plotly figure**

In `app.py`, remove the `from .figure_builder import build_base_figure` import. Remove the `base_fig = build_base_figure(dataset, debug_hover=debug_hover)` assignment (`app.py:31-34`). Change the layout call (`app.py:41`) to:

```python
    app.layout = build_layout(dataset, debug_hover=debug_hover)
```

- [ ] **Step 7: Verify the app boots**

Run: `cd new/obs-data-example && timeout 8 python -m wave_explorer --suffix ds_leo 2>&1 | head -25`
Expected: the startup banner prints and the server line `→ http://127.0.0.1:8050` appears with no traceback. (The graph area is an empty div at this stage — that is expected.)

---

## Task 4: Remove the Plotly figure path

**Files:**
- Delete: `figure_builder.py`, `assets/drag_handles.js`, `assets/tooltip.js`
- Modify: `callbacks/candidate.py`, `app.py`

- [ ] **Step 1: Delete the obsolete files**

Run: `cd new/obs-data-example/wave_explorer && rm figure_builder.py assets/drag_handles.js assets/tooltip.js`

- [ ] **Step 2: Remove the figure-owner callback from `callbacks/candidate.py`**

In `callbacks/candidate.py`, delete the entire `update_figure_shapes` callback (the `@app.callback` decorator + function, `candidate.py:257-267`) and the section banner comment above it (`candidate.py:243-256`).

Also delete the now-unused shape-builder code at the top of the file: the constants `SAVED_FILL`, `SAVED_LINE`, `PENDING_FILL`, `PENDING_LINE`, `ADDED_FILL`, `ADDED_LINE`, `EXCLUDED_FILL`, `EXCLUDED_LINE`, `HLINE_SHAPE`, `HLINE_POS_GUIDE`, `HLINE_NEG_GUIDE`, and the functions `_pick_style` and `_build_ll_shapes` (`candidate.py:32-144`).

Update the imports at the top of `callbacks/candidate.py` — change:

```python
from dash import ALL, Input, Output, Patch, no_update
```

to (drop `Patch`, no longer used):

```python
from dash import ALL, Input, Output, no_update
```

Keep everything else: `nav_to_region`, `update_stats`, the `clamp` helper, and the `compute_custom_region_chi2` / `compute_residual_metrics` / `render_stats` imports.

- [ ] **Step 3: Remove the Plotly hover/click clientside callbacks from `app.py`**

In `app.py`, delete these three `app.clientside_callback(...)` blocks:
- the `tooltip-sync-store` callback driven by `Input("spectrum-graph", "hoverData")` (`app.py:110-122`),
- the `handles-hover-sync-store` callback (`app.py:124-135`),
- the `selected-region-store` click callback driven by `Input("spectrum-graph", "clickData")` (`app.py:142-169`).

Also delete the `ll-entries-store` → `__llEntriesData` sync callback (`app.py:48-69`) and the `discard-signal-store` reset callback (`app.py:81-108`) — Task 6 replaces both with a single spectrum-sync callback.

Keep the `register_all_callbacks(...)` call.

- [ ] **Step 4: Verify the app still boots**

Run: `cd new/obs-data-example && timeout 8 python -m wave_explorer --suffix ds_leo 2>&1 | head -25`
Expected: startup banner + server line, no traceback. (Browser graph is still an empty div.)

---

## Task 5: Spectrum SVG styles

The current `styles.css` already has `.plot-wrap`, `.spectrum-toolbar`, `.zoom-readout`, `.spectrum-canvas-wrap`, `.cursor-tooltip`, `.q-badge`, the heat-strip classes, and the design's CSS custom properties (`--paper`, `--accent`, `--good`/`--fair`/`--poor`/`--bad`, `--ink`/`--ink-2`/`--ink-3`, `--hairline*`, `--muted*`, `--dark`, `--on-dark*`, `--elem-*`, `--font-mono`, `--r-md`). This task adds only the SVG-specific classes.

**Files:**
- Modify: `assets/styles.css`

- [ ] **Step 1: Append the SVG spectrum classes**

Append to the end of `assets/styles.css`:

```css
/* ============================================================
   Spectrum SVG (custom renderer — replaces Plotly)
   ============================================================ */
.spectrum-canvas { position: relative; width: 100%; }
.spectrum-svg {
  display: block; width: 100%; height: auto;
  cursor: grab; touch-action: none;
  user-select: none; -webkit-user-select: none;
}
.spectrum-svg.panning { cursor: grabbing; }
.spectrum-svg.drawing { cursor: crosshair; }

.region-band { transition: opacity 120ms ease; }
.region-band.dim { opacity: 0.4; }

.region-edge { cursor: ew-resize; fill: rgba(0,0,0,0); }
.drag-handle {
  fill: var(--ink); stroke: var(--paper); stroke-width: 1.5;
  cursor: ew-resize; transition: fill 80ms;
}
.drag-handle:hover { fill: var(--accent); }

.spectrum-grid line { stroke: var(--hairline); stroke-width: 0.5; }
body.theme-dark .spectrum-grid line { stroke: rgba(255,255,255,0.06); }
.spectrum-axis-label { font-family: var(--font-mono); font-size: 10px; fill: var(--muted); }

.flux-line, .obs-line, .fit-line, .resid-line { fill: none; }
.obs-line { stroke: var(--ink-3); stroke-width: 1.1; opacity: 0.65; }
.fit-line { stroke: var(--accent); stroke-width: 1.6; }
.resid-line { stroke: var(--ink-3); stroke-width: 1; opacity: 0.85; }
body.theme-dark .obs-line { stroke: #b8b09a; opacity: 0.75; }
body.theme-dark .resid-line { stroke: #b8b09a; opacity: 0.85; }
.continuum-line {
  stroke: var(--muted-soft); stroke-width: 0.8;
  stroke-dasharray: 3 3; fill: none; opacity: 0.5;
}
.element-label {
  font-family: var(--font-mono); font-size: 9px; font-weight: 600;
  text-anchor: middle; pointer-events: none;
}

/* Dark cursor tooltip */
.cursor-tooltip {
  position: fixed; pointer-events: none; z-index: 1000;
  background: var(--dark); color: var(--on-dark);
  border-radius: var(--r-md); padding: 10px 12px;
  font-family: var(--font-mono); font-size: 11px; line-height: 1.5;
  box-shadow: 0 10px 30px rgba(0,0,0,0.25);
  min-width: 200px; max-width: 280px;
}
.cursor-tooltip .tt-title {
  font-family: var(--font-sans); font-weight: 600; font-size: 12px;
  color: var(--on-dark); margin-bottom: 6px;
  display: flex; align-items: center; justify-content: space-between; gap: 8px;
}
.cursor-tooltip .tt-row { display: flex; justify-content: space-between; gap: 12px; }
.cursor-tooltip .tt-row > span:first-child { color: var(--on-dark-soft); }
.cursor-tooltip .tt-row > span:last-child {
  color: var(--on-dark); font-variant-numeric: tabular-nums;
}
.cursor-tooltip .tt-sep {
  height: 1px; background: rgba(255,255,255,0.08); margin: 6px -12px;
}
```

- [ ] **Step 2: Verify the rule was appended**

Run: `cd new/obs-data-example/wave_explorer && grep -c "spectrum-svg" assets/styles.css`
Expected: a non-zero count (the new rules are present).

---

## Task 6: The spectrum.js SVG component

This is the core deliverable — a vanilla-JS port of the design's `spectrum.jsx`. It renders the SVG, owns pan/zoom/select/drag/draw/hover, writes to Dash stores, and exposes `window.WaveExplorer` for the heat-strip.

**Files:**
- Create: `assets/spectrum.js`
- Modify: `app.py` (one sync callback)

- [ ] **Step 1: Create `assets/spectrum.js`**

Create `assets/spectrum.js` with exactly this content:

```javascript
/**
 * Wave Explorer — custom SVG spectrum component.
 *
 * Vanilla-JS port of the Claude Design `spectrum.jsx` handoff. Renders the
 * flux + residual panels into #spectrum-graph, owns pan / zoom / select /
 * edge-drag / draw / hover, and writes results back to Dash stores:
 *   - selected-region-store : {region_idx} on click  (null clears)
 *   - drag-result-store     : {region_idx, bound, new_x_nm} on edge-drag commit
 *   - draw-region-store     : {lo, hi} when the draw-confirm popover is accepted
 *
 * window.WaveExplorer exposes getView/setView/onViewChange for heatstrip.js.
 * window.activateDrawMode(bool) is kept for the existing draw-mode callbacks.
 */
(function () {
  "use strict";

  // ── Geometry (from spectrum.jsx) ─────────────────────────────────────────
  var PLOT_W = 1380;
  var MAIN = { top: 20, h: 320 };
  var GAP = 14;
  var RESID = { top: MAIN.top + MAIN.h + GAP, h: 130 };
  var X_LABEL_Y = RESID.top + RESID.h + 18;
  var PLOT_H = X_LABEL_Y + 14;
  var PAD = { right: 28, left: 60 };
  var innerW = PLOT_W - PAD.left - PAD.right;
  var fullBottom = RESID.top + RESID.h;

  var DRAG_THRESHOLD = 4; // px (SVG units) gate for click-vs-pan
  var MIN_SPAN = 0.4;     // nm — min zoom span
  var MIN_REGION_W = 0.005; // nm — min region width on edge-drag
  var EDGE_HIT = 8;       // half-width of an edge hit zone, SVG units

  // ── Module state ─────────────────────────────────────────────────────────
  var data = null;          // spectrum-data-store payload
  var llEntries = [];       // live region geometry/state (ll-entries-store)
  var pendingChanges = {};   // staged edits, keyed by string index
  var view = null;          // {min, max}
  var selectedIdx = null;
  var hoveredIdx = null;
  var cursorPx = null;       // SVG-space cursor x, or null
  var drawMode = false;
  var fluxRange = null;      // {min, max}
  var residMax = 1;          // symmetric resid half-range

  var interaction = null;    // active gesture (mutable during a drag)
  var rafPending = false;
  var viewChangeCbs = [];
  var svgEl = null;

  // ── Quality coding ───────────────────────────────────────────────────────
  function qualityTier(c2) {
    if (c2 == null || !isFinite(c2)) return "miss";
    var t = (data && data.chi2Thresholds) || [5, 15, 30];
    if (c2 < t[0]) return "good";
    if (c2 < t[1]) return "fair";
    if (c2 < t[2]) return "poor";
    return "bad";
  }
  var Q_COLOR = {
    good: "#4f7a4d", fair: "#b88829", poor: "#c87338",
    bad: "#9c3d2e", miss: "#9c9684",
  };
  var Q_FILL = {
    good: "rgba(79,122,77,0.16)", fair: "rgba(184,136,41,0.16)",
    poor: "rgba(200,115,56,0.18)", bad: "rgba(156,61,46,0.20)",
    miss: "rgba(156,150,132,0.14)",
  };
  function qualityLabel(c2) {
    return { good: "GOOD", fair: "FAIR", poor: "POOR", bad: "BAD", miss: "—" }[
      qualityTier(c2)
    ];
  }
  function romanize(n) {
    return { 1: "I", 2: "II", 3: "III", 4: "IV", 5: "V" }[parseInt(n, 10)] ||
      String(n);
  }
  function elementColor(sym) {
    if (!data) return "#75705f";
    return (data.elementColors && data.elementColors[sym]) ||
      data.elementColorFallback || "#75705f";
  }

  // ── Accessors ────────────────────────────────────────────────────────────
  function host() { return document.getElementById("spectrum-graph"); }

  function effRegion(i) {
    // Region geometry/state merged with any staged pending edit.
    var base = llEntries[i];
    if (!base) return null;
    var pc = pendingChanges[String(i)] || {};
    return {
      idx: i,
      lower: pc.lower != null ? +pc.lower : +base.lower,
      upper: pc.upper != null ? +pc.upper : +base.upper,
      excluded: pc.excluded != null ? !!pc.excluded : !!base.excluded,
      element: String(base.element || "?"),
      ion: String(base.ion || "1"),
      pending: Object.keys(pc).length > 0,
    };
  }
  function regionChi2(i) {
    var r = data && data.regions && data.regions[i];
    return r ? r.chi2 : null;
  }
  function regionStats(i) {
    var r = (data && data.regions && data.regions[i]) || {};
    return { n_stars: r.n_stars || 0, n_pix: r.n_pix || 0 };
  }

  // ── Scales ───────────────────────────────────────────────────────────────
  function xScale(w) {
    return PAD.left + ((w - view.min) / (view.max - view.min)) * innerW;
  }
  function xInvert(px, v) {
    v = v || view;
    return v.min + ((px - PAD.left) / innerW) * (v.max - v.min);
  }
  function yMain(f) {
    var r = fluxRange;
    return MAIN.top + (1 - (f - r.min) / (r.max - r.min)) * MAIN.h;
  }
  function yResid(rv) {
    return RESID.top + RESID.h / 2 - (rv / residMax) * (RESID.h / 2);
  }

  function clampView(nmin, nmax) {
    var lo = data.lambdaMin, hi = data.lambdaMax;
    var maxSpan = hi - lo;
    var span = nmax - nmin;
    if (span < MIN_SPAN) {
      var c = (nmin + nmax) / 2;
      nmin = c - MIN_SPAN / 2; nmax = c + MIN_SPAN / 2; span = MIN_SPAN;
    }
    if (span > maxSpan) return { min: lo, max: hi };
    if (nmin < lo) { nmax += lo - nmin; nmin = lo; }
    if (nmax > hi) { nmin -= nmax - hi; nmax = hi; }
    return { min: nmin, max: nmax };
  }

  function sampleAt(key, lambda) {
    var arr = data[key], w = data.wavelengths;
    var frac = (lambda - data.lambdaMin) / (data.lambdaMax - data.lambdaMin);
    var i = Math.round(frac * (w.length - 1));
    i = Math.max(0, Math.min(w.length - 1, i));
    return arr[i];
  }

  // ── Path building ────────────────────────────────────────────────────────
  function buildPath(arr, yFn) {
    var w = data.wavelengths, d = "", started = false;
    for (var i = 0; i < w.length; i++) {
      if (w[i] < view.min - 0.05 || w[i] > view.max + 0.05) continue;
      var x = xScale(w[i]).toFixed(2), y = yFn(arr[i]).toFixed(2);
      d += (started ? "L" : "M") + x + "," + y;
      started = true;
    }
    return d;
  }

  function ticks() {
    var span = view.max - view.min, step;
    if (span < 2) step = 0.2;
    else if (span < 5) step = 0.5;
    else if (span < 12) step = 1;
    else if (span < 25) step = 2;
    else step = 5;
    var arr = [], start = Math.ceil(view.min / step) * step;
    for (var t = start; t <= view.max; t += step) arr.push(t);
    return { arr: arr, step: step };
  }

  // ── SVG element helper ───────────────────────────────────────────────────
  var NS = "http://www.w3.org/2000/svg";
  function el(tag, attrs, text) {
    var n = document.createElementNS(NS, tag);
    for (var k in attrs) {
      if (attrs[k] != null) n.setAttribute(k, attrs[k]);
    }
    if (text != null) n.textContent = text;
    return n;
  }

  // ── Render ───────────────────────────────────────────────────────────────
  function render() {
    var h = host();
    if (!h || !data || !view) return;
    if (!svgEl) {
      svgEl = el("svg", {
        class: "spectrum-svg",
        viewBox: "0 0 " + PLOT_W + " " + PLOT_H,
        preserveAspectRatio: "none",
      });
      svgEl.style.touchAction = "none";
      h.appendChild(svgEl);
      bindPointer();
    }
    svgEl.setAttribute(
      "class",
      "spectrum-svg" +
        (interaction && interaction.kind === "pan" && interaction.activated
          ? " panning"
          : "") +
        (drawMode || (interaction && interaction.kind === "draw")
          ? " drawing"
          : "")
    );

    var tk = ticks();
    var fluxTicks = niceTicks(fluxRange.min, fluxRange.max, 5);
    var residTicks = [-residMax * 0.66, 0, residMax * 0.66];
    var parts = [];

    // backgrounds
    parts.push(rect(PAD.left, MAIN.top, innerW, MAIN.h, "var(--paper)"));
    parts.push(rect(PAD.left, RESID.top, innerW, RESID.h, "var(--paper-soft)"));

    // grid
    var grid = el("g", { class: "spectrum-grid" });
    tk.arr.forEach(function (t) {
      grid.appendChild(line(xScale(t), MAIN.top, xScale(t), MAIN.top + MAIN.h));
      grid.appendChild(line(xScale(t), RESID.top, xScale(t), RESID.top + RESID.h));
    });
    fluxTicks.forEach(function (f) {
      grid.appendChild(line(PAD.left, yMain(f), PAD.left + innerW, yMain(f)));
    });
    residTicks.forEach(function (rv) {
      grid.appendChild(line(PAD.left, yResid(rv), PAD.left + innerW, yResid(rv)));
    });
    parts.push(grid);

    // continuum + zero lines
    parts.push(el("line", {
      class: "continuum-line",
      x1: PAD.left, x2: PAD.left + innerW, y1: yMain(1.0), y2: yMain(1.0),
    }));
    parts.push(el("line", {
      x1: PAD.left, x2: PAD.left + innerW, y1: yResid(0), y2: yResid(0),
      stroke: "var(--ink-3)", "stroke-width": 0.8, opacity: 0.5,
    }));

    // region bands
    parts.push(renderRegions());

    // draw-in-progress preview
    if (interaction && interaction.kind === "draw" && interaction.preview) {
      var p = interaction.preview;
      var dx1 = xScale(Math.min(p.x0, p.x1)), dx2 = xScale(Math.max(p.x0, p.x1));
      parts.push(el("rect", {
        x: dx1, y: MAIN.top, width: Math.max(1, dx2 - dx1),
        height: fullBottom - MAIN.top, fill: "rgba(179,85,59,0.18)",
        stroke: "var(--accent)", "stroke-width": 1.5, "stroke-dasharray": "4 3",
      }));
    }

    // data lines
    parts.push(el("path", { class: "obs-line", d: buildPath(data.flux, yMain) }));
    parts.push(el("path", { class: "fit-line", d: buildPath(data.fitFlux, yMain) }));
    parts.push(el("path", { class: "resid-line", d: buildPath(data.resid, yResid) }));

    // residual outlier dots
    var dots = el("g", {});
    var w = data.wavelengths, rd = data.resid;
    for (var i = 0; i < w.length; i++) {
      if (w[i] < view.min || w[i] > view.max) continue;
      if (Math.abs(rd[i]) > residMax * 0.55) {
        dots.appendChild(el("circle", {
          cx: xScale(w[i]), cy: yResid(rd[i]), r: 1.6,
          fill: rd[i] > 0 ? "var(--accent)" : "var(--ink)", opacity: 0.7,
        }));
      }
    }
    parts.push(dots);

    // cursor crosshair
    if (cursorPx != null && cursorPx > PAD.left && cursorPx < PAD.left + innerW) {
      parts.push(el("line", {
        x1: cursorPx, x2: cursorPx, y1: MAIN.top, y2: fullBottom,
        stroke: "var(--ink)", "stroke-width": 0.6, "stroke-dasharray": "2 3",
        opacity: 0.35, "pointer-events": "none",
      }));
    }

    // axes
    parts.push(renderAxes(tk, fluxTicks, residTicks));

    // commit
    svgEl.textContent = "";
    parts.forEach(function (n) { svgEl.appendChild(n); });
  }

  function rect(x, y, w, h, fill) {
    return el("rect", { x: x, y: y, width: w, height: h, fill: fill });
  }
  function line(x1, y1, x2, y2) {
    return el("line", { x1: x1, y1: y1, x2: x2, y2: y2 });
  }

  function renderRegions() {
    var g = el("g", {});
    for (var i = 0; i < llEntries.length; i++) {
      var r = effRegion(i);
      if (!r) continue;
      if (r.upper < view.min || r.lower > view.max) continue;
      var x1 = xScale(r.lower), x2 = xScale(r.upper);
      var bw = Math.max(1, x2 - x1);
      var c2 = regionChi2(i);
      var tier = qualityTier(c2);
      var fill = r.excluded ? "rgba(156,61,46,0.07)" : Q_FILL[tier];
      var stroke = r.excluded ? "rgba(156,61,46,0.5)" : Q_COLOR[tier];
      var isSel = i === selectedIdx;
      var isHov = i === hoveredIdx;
      var dim = selectedIdx != null && !isSel;

      var rg = el("g", { class: "region-band" + (dim ? " dim" : "") });

      // main + resid bands
      rg.appendChild(el("rect", {
        x: x1, y: MAIN.top, width: bw, height: MAIN.h, fill: fill,
        stroke: r.excluded ? stroke : "none",
        "stroke-dasharray": r.excluded ? "3 3" : null,
        "stroke-width": r.excluded ? 1 : 0,
        "data-region": i, style: "cursor:pointer",
      }));
      rg.appendChild(el("rect", {
        x: x1, y: RESID.top, width: bw, height: RESID.h, fill: fill,
        opacity: 0.7, "data-region": i, style: "cursor:pointer",
      }));
      // element rail (bottom of main)
      rg.appendChild(el("rect", {
        x: x1, y: MAIN.top + MAIN.h - 3, width: bw, height: 3,
        fill: elementColor(r.element), opacity: r.excluded ? 0.3 : 0.9,
      }));
      // quality stripe (top of main)
      rg.appendChild(el("rect", {
        x: x1, y: MAIN.top, width: bw, height: 2, fill: stroke,
        opacity: r.excluded ? 0.25 : 1,
      }));
      // pending accent stripe
      if (r.pending && !r.excluded) {
        rg.appendChild(el("rect", {
          x: x1, y: MAIN.top + 4, width: bw, height: 2, fill: "var(--accent)",
        }));
      }
      // selection glow
      if (isSel) {
        rg.appendChild(el("rect", {
          x: x1 - 2, y: MAIN.top - 2, width: x2 - x1 + 4,
          height: fullBottom - MAIN.top + 4, rx: 3, fill: "none",
          stroke: "var(--accent)", "stroke-width": 2, opacity: 0.85,
        }));
      } else if (isHov) {
        rg.appendChild(el("rect", {
          x: x1 - 1, y: MAIN.top, width: x2 - x1 + 2,
          height: fullBottom - MAIN.top, fill: "none", stroke: stroke,
          "stroke-width": 1.5, opacity: 0.6,
        }));
      }
      // edge handles — only on the selected region
      if (isSel) {
        [["lo", x1], ["hi", x2]].forEach(function (pair) {
          var edge = pair[0], hx = pair[1];
          rg.appendChild(el("rect", {
            class: "region-edge", "data-region-edge": edge, "data-region": i,
            x: hx - EDGE_HIT, y: MAIN.top, width: EDGE_HIT * 2,
            height: fullBottom - MAIN.top,
          }));
          var hg = el("g", {
            transform: "translate(" + hx + "," + (MAIN.top + MAIN.h / 2) + ")",
            style: "pointer-events:none",
          });
          hg.appendChild(el("line", {
            x1: 0, x2: 0, y1: MAIN.top - (MAIN.top + MAIN.h / 2),
            y2: fullBottom - (MAIN.top + MAIN.h / 2), stroke: stroke,
            "stroke-width": 1, opacity: 0.6, "stroke-dasharray": "3 2",
          }));
          hg.appendChild(el("rect", {
            class: "drag-handle", x: -5, y: -16, width: 10, height: 32, rx: 2.5,
          }));
          rg.appendChild(hg);
        });
      }
      // element label
      if (bw > 30) {
        rg.appendChild(el("text", {
          class: "element-label", x: (x1 + x2) / 2, y: MAIN.top + 14,
          fill: elementColor(r.element), opacity: r.excluded ? 0.45 : 1,
        }, r.element + " " + romanize(r.ion)));
      }
      g.appendChild(rg);
    }
    return g;
  }

  function renderAxes(tk, fluxTicks, residTicks) {
    var g = el("g", {});
    // x-axis
    g.appendChild(el("line", {
      x1: PAD.left, x2: PAD.left + innerW, y1: fullBottom, y2: fullBottom,
      stroke: "var(--hairline)",
    }));
    tk.arr.forEach(function (t) {
      g.appendChild(el("line", {
        x1: xScale(t), x2: xScale(t), y1: fullBottom, y2: fullBottom + 4,
        stroke: "var(--hairline)",
      }));
      g.appendChild(el("text", {
        class: "spectrum-axis-label", x: xScale(t), y: fullBottom + 18,
        "text-anchor": "middle",
      }, t.toFixed(tk.step < 1 ? 1 : 0)));
    });
    g.appendChild(el("text", {
      class: "spectrum-axis-label", x: PLOT_W - PAD.right, y: fullBottom + 18,
      "text-anchor": "end", style: "font-weight:600",
    }, "λ (nm)"));
    // main y-axis
    g.appendChild(el("line", {
      x1: PAD.left, x2: PAD.left, y1: MAIN.top, y2: MAIN.top + MAIN.h,
      stroke: "var(--hairline)",
    }));
    fluxTicks.forEach(function (f) {
      g.appendChild(el("text", {
        class: "spectrum-axis-label", x: PAD.left - 8, y: yMain(f) + 3,
        "text-anchor": "end",
      }, f.toFixed(2)));
    });
    g.appendChild(el("text", {
      class: "spectrum-axis-label", x: PAD.left + 6, y: MAIN.top + 12,
      "text-anchor": "start", style: "font-weight:600",
    }, "normalized flux"));
    // resid y-axis
    g.appendChild(el("line", {
      x1: PAD.left, x2: PAD.left, y1: RESID.top, y2: RESID.top + RESID.h,
      stroke: "var(--hairline)",
    }));
    residTicks.forEach(function (rv) {
      g.appendChild(el("text", {
        class: "spectrum-axis-label", x: PAD.left - 8, y: yResid(rv) + 3,
        "text-anchor": "end",
      }, (rv > 0 ? "+" : "") + rv.toFixed(3)));
    });
    g.appendChild(el("text", {
      class: "spectrum-axis-label", x: PAD.left + 6, y: RESID.top + 12,
      "text-anchor": "start", style: "font-weight:600",
    }, "obs − fit"));
    // legend
    var lg = el("g", {
      transform: "translate(" + (PLOT_W - PAD.right - 200) + "," +
        (MAIN.top + 8) + ")",
    });
    lg.appendChild(el("rect", {
      x: 0, y: 0, width: 196, height: 26, rx: 5, fill: "var(--paper)",
      stroke: "var(--hairline-soft)",
    }));
    lg.appendChild(el("line", {
      x1: 10, x2: 28, y1: 13, y2: 13, stroke: "var(--ink-3)", "stroke-width": 1.4,
    }));
    lg.appendChild(el("text", {
      class: "spectrum-axis-label", x: 32, y: 16,
    }, "obs"));
    lg.appendChild(el("line", {
      x1: 66, x2: 84, y1: 13, y2: 13, stroke: "var(--accent)", "stroke-width": 1.6,
    }));
    lg.appendChild(el("text", {
      class: "spectrum-axis-label", x: 88, y: 16,
    }, "fit"));
    lg.appendChild(el("line", {
      x1: 118, x2: 136, y1: 13, y2: 13, stroke: "var(--ink-3)",
      "stroke-width": 1.2, "stroke-dasharray": "3 2",
    }));
    lg.appendChild(el("text", {
      class: "spectrum-axis-label", x: 140, y: 16,
    }, "resid"));
    g.appendChild(lg);
    return g;
  }

  function niceTicks(lo, hi, count) {
    var step = (hi - lo) / (count - 1), out = [];
    for (var i = 0; i < count; i++) out.push(lo + i * step);
    return out;
  }

  // ── Render scheduling ────────────────────────────────────────────────────
  function scheduleRender() {
    if (rafPending) return;
    rafPending = true;
    window.requestAnimationFrame(function () {
      rafPending = false;
      render();
    });
  }

  // ── Pointer interaction ──────────────────────────────────────────────────
  function svgCoords(e) {
    var rect = svgEl.getBoundingClientRect();
    var px = ((e.clientX - rect.left) / rect.width) * PLOT_W;
    return { px: px, lambda: xInvert(px), clientX: e.clientX, clientY: e.clientY };
  }

  function bindPointer() {
    svgEl.addEventListener("pointerdown", onDown);
    svgEl.addEventListener("pointermove", onMove);
    svgEl.addEventListener("pointerup", onUp);
    svgEl.addEventListener("pointercancel", onCancel);
    svgEl.addEventListener("pointerleave", onLeave);
    svgEl.addEventListener("wheel", onWheel, { passive: false });
  }

  function onDown(e) {
    if (e.button !== 0) return;
    var p = svgCoords(e);
    svgEl.setPointerCapture(e.pointerId);

    if (drawMode) {
      interaction = { kind: "draw", startLambda: p.lambda,
        preview: { x0: p.lambda, x1: p.lambda }, pointerId: e.pointerId };
      scheduleRender();
      return;
    }

    var edge = e.target && e.target.getAttribute &&
      e.target.getAttribute("data-region-edge");
    if (edge && selectedIdx != null) {
      var r = effRegion(selectedIdx);
      if (r) {
        interaction = { kind: "edge", regionIdx: selectedIdx, edge: edge,
          originalLo: r.lower, originalHi: r.upper, pointerId: e.pointerId };
        return;
      }
    }

    interaction = { kind: "pan", startClientX: e.clientX,
      viewMin: view.min, viewMax: view.max, pointerId: e.pointerId,
      downLambda: p.lambda, activated: false };
  }

  function onMove(e) {
    var p = svgCoords(e);
    cursorPx = p.px;
    var it = interaction;

    if (it && it.kind === "edge") {
      var lo = it.originalLo, hi = it.originalHi;
      if (it.edge === "lo") lo = Math.min(p.lambda, hi - MIN_REGION_W);
      else hi = Math.max(p.lambda, lo + MIN_REGION_W);
      stageEdgePreview(it.regionIdx, lo, hi);
      scheduleRender();
      return;
    }
    if (it && it.kind === "draw") {
      it.preview = { x0: it.startLambda, x1: p.lambda };
      scheduleRender();
      return;
    }
    if (it && it.kind === "pan") {
      var dxPx = e.clientX - it.startClientX;
      if (!it.activated) {
        var dxSvgGate = (dxPx / svgEl.getBoundingClientRect().width) * PLOT_W;
        if (Math.abs(dxSvgGate) < DRAG_THRESHOLD) return;
        it.activated = true;
      }
      var dxSvg = (dxPx / svgEl.getBoundingClientRect().width) * PLOT_W;
      var span = it.viewMax - it.viewMin;
      var dLambda = -(dxSvg / innerW) * span;
      view = clampView(it.viewMin + dLambda, it.viewMax + dLambda);
      emitViewChange();
      scheduleRender();
      return;
    }

    // hover
    var hit = hitRegion(p.lambda);
    hoveredIdx = hit;
    updateTooltip(p);
    scheduleRender();
  }

  function onUp(e) {
    var it = interaction;
    try { svgEl.releasePointerCapture(e.pointerId); } catch (_) {}

    if (it && it.kind === "edge") {
      var r = effRegion(it.regionIdx);
      if (r) {
        var bound = it.edge === "lo" ? "lower" : "upper";
        var newX = it.edge === "lo" ? r.lower : r.upper;
        setProps("drag-result-store",
          { region_idx: it.regionIdx, bound: bound, new_x_nm: newX });
      }
      interaction = null;
      return;
    }
    if (it && it.kind === "draw") {
      var p = svgCoords(e);
      var lo = Math.min(it.startLambda, p.lambda);
      var hi = Math.max(it.startLambda, p.lambda);
      interaction = null;
      if (hi - lo > 0.01) openDrawPopover(lo, hi, e.clientX, e.clientY);
      else scheduleRender();
      return;
    }
    if (it && it.kind === "pan") {
      if (!it.activated) {
        var sel = hitRegion(it.downLambda);
        selectedIdx = sel;
        setProps("selected-region-store", sel == null ? null : { region_idx: sel });
      }
      interaction = null;
      scheduleRender();
      return;
    }
  }

  function onCancel(e) {
    try { svgEl.releasePointerCapture(e.pointerId); } catch (_) {}
    interaction = null;
    scheduleRender();
  }

  function onLeave() {
    if (interaction) return;
    cursorPx = null;
    hoveredIdx = null;
    hideTooltip();
    scheduleRender();
  }

  function onWheel(e) {
    e.preventDefault();
    var p = svgCoords(e);
    var factor = e.deltaY > 0 ? 1.15 : 1 / 1.15;
    var span = view.max - view.min;
    var newSpan = Math.max(MIN_SPAN,
      Math.min(data.lambdaMax - data.lambdaMin, span * factor));
    var nmin = p.lambda - ((p.lambda - view.min) / span) * newSpan;
    view = clampView(nmin, nmin + newSpan);
    emitViewChange();
    scheduleRender();
  }

  function hitRegion(lambda) {
    for (var i = 0; i < llEntries.length; i++) {
      var r = effRegion(i);
      if (r && lambda >= r.lower && lambda <= r.upper) return i;
    }
    return null;
  }

  // Stage an in-flight edge preview into pendingChanges so the band stretches
  // live. Mirrors the server's stage_drag; the committed value is sent on up.
  function stageEdgePreview(i, lo, hi) {
    var pc = Object.assign({}, pendingChanges[String(i)] || {});
    pc.lower = lo; pc.upper = hi; pc.center = 0.5 * (lo + hi);
    pendingChanges = Object.assign({}, pendingChanges);
    pendingChanges[String(i)] = pc;
  }

  // ── Tooltip ──────────────────────────────────────────────────────────────
  function updateTooltip(p) {
    var tip = document.getElementById("cursor-tooltip");
    if (!tip || !data) return;
    var cl = p.lambda;
    var head;
    if (hoveredIdx != null) {
      var r = effRegion(hoveredIdx), c2 = regionChi2(hoveredIdx);
      var st = regionStats(hoveredIdx);
      head =
        '<div class="tt-title"><span>Region #' + (hoveredIdx + 1) +
        '</span><span class="q-badge q-' + qualityTier(c2) + '">' +
        qualityLabel(c2) + "</span></div>" +
        ttRow("χ²/N", c2 != null && isFinite(c2) ? c2.toFixed(3) : "—") +
        ttRow("range", r.lower.toFixed(3) + " – " + r.upper.toFixed(3)) +
        ttRow("width", (r.upper - r.lower).toFixed(3) + " nm") +
        ttRow("n stars", st.n_stars) +
        ttRow("n pix", st.n_pix) +
        '<div class="tt-sep"></div>';
    } else {
      head = '<div class="tt-title"><span>cursor</span></div>';
    }
    var resid = sampleAt("resid", cl);
    tip.innerHTML = head +
      ttRow("cursor λ", cl.toFixed(3)) +
      ttRow("obs flux", sampleAt("flux", cl).toFixed(4)) +
      ttRow("fit", sampleAt("fitFlux", cl).toFixed(4)) +
      ttRow("resid", (resid >= 0 ? "+" : "") + resid.toFixed(4));
    tip.style.display = "block";
    tip.style.left = (p.clientX + 16) + "px";
    tip.style.top = (p.clientY + 16) + "px";
  }
  function ttRow(k, v) {
    return '<div class="tt-row"><span>' + k + "</span><span>" + v +
      "</span></div>";
  }
  function hideTooltip() {
    var tip = document.getElementById("cursor-tooltip");
    if (tip) tip.style.display = "none";
  }

  // ── Draw-confirm popover ─────────────────────────────────────────────────
  function openDrawPopover(lo, hi, clientX, clientY) {
    var pop = document.getElementById("draw-confirm-popover");
    if (!pop) return;
    var rt = document.getElementById("draw-confirm-range-text");
    if (rt) rt.textContent = lo.toFixed(3) + " – " + hi.toFixed(3) + " nm";
    pop.setAttribute("data-lo", lo);
    pop.setAttribute("data-hi", hi);
    pop.style.display = "block";
    pop.style.left = clientX + "px";
    pop.style.top = (clientY - 40) + "px";
  }
  function wirePopover() {
    var acc = document.getElementById("draw-confirm-accept");
    var can = document.getElementById("draw-confirm-cancel");
    if (acc && !acc.__weBound) {
      acc.__weBound = true;
      acc.addEventListener("click", function () {
        var pop = document.getElementById("draw-confirm-popover");
        if (!pop) return;
        var lo = parseFloat(pop.getAttribute("data-lo"));
        var hi = parseFloat(pop.getAttribute("data-hi"));
        if (isFinite(lo) && isFinite(hi)) {
          setProps("draw-region-store", { lo: lo, hi: hi });
        }
        pop.style.display = "none";
      });
    }
    if (can && !can.__weBound) {
      can.__weBound = true;
      can.addEventListener("click", function () {
        var pop = document.getElementById("draw-confirm-popover");
        if (pop) pop.style.display = "none";
      });
    }
  }

  // ── Dash store writes ────────────────────────────────────────────────────
  function setProps(id, value) {
    if (window.dash_clientside && window.dash_clientside.set_props) {
      window.dash_clientside.set_props(id, { data: value });
    }
  }

  // ── View-change notification (heatstrip) ─────────────────────────────────
  function emitViewChange() {
    viewChangeCbs.forEach(function (cb) {
      try { cb(view.min, view.max); } catch (_) {}
    });
  }

  // ── Public sync entry — called by the Dash clientside callback ───────────
  function sync(specData, entries, pending, selected, drawActive) {
    var firstData = false;
    if (specData && specData.wavelengths) {
      if (!data) firstData = true;
      data = specData;
    }
    if (!data) return;
    if (firstData) {
      var fmin = Infinity, fmax = -Infinity, rmax = 0;
      for (var i = 0; i < data.flux.length; i++) {
        fmin = Math.min(fmin, data.flux[i], data.fitFlux[i]);
        fmax = Math.max(fmax, data.flux[i], data.fitFlux[i]);
        rmax = Math.max(rmax, Math.abs(data.resid[i]));
      }
      var fpad = 0.04 * (fmax - fmin || 1);
      fluxRange = { min: fmin - fpad, max: fmax + fpad };
      residMax = Math.max(0.01, rmax * 1.15);
      view = { min: data.lambdaMin, max: data.lambdaMax };
    }
    if (entries != null) llEntries = entries;
    if (pending != null) pendingChanges = pending || {};
    selectedIdx = selected && selected.region_idx != null
      ? selected.region_idx : null;
    drawMode = !!drawActive;
    wirePopover();
    scheduleRender();
  }

  // ── window.WaveExplorer API + draw-mode hook ─────────────────────────────
  window.WaveExplorer = {
    sync: sync,
    getView: function () { return view ? { min: view.min, max: view.max } : null; },
    setView: function (min, max) {
      if (!data) return;
      view = clampView(min, max);
      emitViewChange();
      scheduleRender();
    },
    onViewChange: function (cb) { viewChangeCbs.push(cb); },
  };
  window.activateDrawMode = function (active) {
    drawMode = !!active;
    if (drawMode && interaction && interaction.kind !== "draw") {
      interaction = null;
    }
    scheduleRender();
  };

  // ── Init — wait for the host div ─────────────────────────────────────────
  function init() {
    if (!host()) { setTimeout(init, 100); return; }
    if (window.__weSpectrumPending) {
      var a = window.__weSpectrumPending;
      sync(a[0], a[1], a[2], a[3], a[4]);
    }
  }
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
```

- [ ] **Step 2: Add the spectrum-sync clientside callback to `app.py`**

In `app.py`, inside `create_app`, before the `register_all_callbacks(...)` call, add:

```python
    # ── Clientside: feed the SVG spectrum component ──────────────────────────
    # One callback pushes static data + live region state into spectrum.js.
    # If spectrum.js has not initialised yet, the args are cached on window
    # and replayed by its init().
    app.clientside_callback(
        """
        function(specData, llEntries, pending, selected, drawActive) {
            var args = [specData, llEntries, pending, selected, drawActive];
            window.__weSpectrumPending = args;
            if (window.WaveExplorer && window.WaveExplorer.sync) {
                window.WaveExplorer.sync.apply(null, args);
            }
            return window.dash_clientside
                ? window.dash_clientside.no_update : null;
        }
        """,
        Output("handles-sync-store", "data"),
        Input("spectrum-data-store", "data"),
        Input("ll-entries-store", "data"),
        Input("pending-changes-store", "data"),
        Input("selected-region-store", "data"),
        Input("draw-mode-active-store", "data"),
    )
```

- [ ] **Step 3: Run the app and verify static rendering + interaction**

Run: `cd new/obs-data-example && python -m wave_explorer --suffix ds_leo`
Open `http://127.0.0.1:8050` and confirm:
- The spectrum SVG renders: obs line (grey), fit line (terracotta), residual panel, grid, axes, legend.
- Region bands are colored by χ² tier; a poorly-fit region is amber/orange/red, a good one green; the quality stripe and element rail show.
- Drag an empty area → the view pans smoothly with no drift; a quick click on a band selects it (glow appears, other bands dim, drag handles appear on the selected region only).
- Mouse wheel zooms toward the cursor.
- Hover a band → dashed crosshair + dark tooltip with region #, χ² badge, and cursor obs/fit/resid.
- Drag a handle on the selected region → the band stretches; release → the pending badge increments (a `drag-result-store` change staged by `stage_drag`).
- Press `D`, drag across the plot → dashed preview → release → the draw-confirm popover; Accept → a new region appears.
- An excluded region (use the X key on a selected region) shows the faint-red dashed style.

Stop the server (Ctrl-C) when done.

---

## Task 7: Rewire heatstrip.js

The heat-strip currently reads `gd._fullLayout.xaxis.range` and calls `Plotly.relayout`. Repoint it at `window.WaveExplorer`.

**Files:**
- Modify: `assets/heatstrip.js`

- [ ] **Step 1: Replace the Plotly accessors and binding in `heatstrip.js`**

Replace the entire body of the `heatstrip.js` IIFE (everything between `(function () {` `"use strict";` and the closing `})();`) with:

```javascript
  "use strict";

  var rafPending = false;
  var dragging = false;

  function clamp(v, lo, hi) {
    return v < lo ? lo : v > hi ? hi : v;
  }

  function bounds(strip) {
    var lmin = parseFloat(strip.dataset.lmin);
    var lmax = parseFloat(strip.dataset.lmax);
    if (!isFinite(lmin) || !isFinite(lmax) || lmax <= lmin) return null;
    return { lmin: lmin, lmax: lmax, span: lmax - lmin };
  }

  // -- Viewport sync --------------------------------------------------------

  function syncViewport() {
    rafPending = false;
    var strip = document.getElementById("heatstrip");
    var vp = document.getElementById("heatstrip-viewport");
    if (!strip || !vp || !window.WaveExplorer) return;
    var b = bounds(strip);
    var r = window.WaveExplorer.getView();
    if (!b || !r) return;
    var left = clamp(((r.min - b.lmin) / b.span) * 100, 0, 100);
    var right = clamp(((r.max - b.lmin) / b.span) * 100, 0, 100);
    vp.style.left = left + "%";
    vp.style.width = Math.max(0.4, right - left) + "%";
  }

  function scheduleSync() {
    if (rafPending) return;
    rafPending = true;
    window.requestAnimationFrame(syncViewport);
  }

  // -- Navigation -----------------------------------------------------------

  function jumpToClientX(clientX) {
    var strip = document.getElementById("heatstrip");
    if (!strip || !window.WaveExplorer) return;
    var b = bounds(strip);
    var r = window.WaveExplorer.getView();
    if (!b || !r) return;
    var rect = strip.getBoundingClientRect();
    var frac = clamp((clientX - rect.left) / rect.width, 0, 1);
    var lam = b.lmin + frac * b.span;
    var viewSpan = Math.min(b.span, r.max - r.min);
    var lo = lam - viewSpan / 2;
    var hi = lam + viewSpan / 2;
    if (lo < b.lmin) { hi += b.lmin - lo; lo = b.lmin; }
    if (hi > b.lmax) { lo -= hi - b.lmax; hi = b.lmax; }
    window.WaveExplorer.setView(clamp(lo, b.lmin, b.lmax),
      clamp(hi, b.lmin, b.lmax));
  }

  function setupStrip() {
    var strip = document.getElementById("heatstrip");
    if (!strip) return;
    strip.addEventListener("pointerdown", function (e) {
      dragging = true;
      try { strip.setPointerCapture(e.pointerId); } catch (err) {}
      jumpToClientX(e.clientX);
      e.preventDefault();
    });
    strip.addEventListener("pointermove", function (e) {
      if (dragging) jumpToClientX(e.clientX);
    });
    function endDrag(e) {
      dragging = false;
      try { strip.releasePointerCapture(e.pointerId); } catch (err) {}
    }
    strip.addEventListener("pointerup", endDrag);
    strip.addEventListener("pointercancel", endDrag);
  }

  // -- Init -----------------------------------------------------------------

  function bindViewChange(attempt) {
    if (window.WaveExplorer && window.WaveExplorer.onViewChange) {
      window.WaveExplorer.onViewChange(scheduleSync);
      scheduleSync();
      return;
    }
    if (attempt < 80) {
      setTimeout(function () { bindViewChange(attempt + 1); }, 150);
    }
  }

  function init() {
    setupStrip();
    bindViewChange(0);
    window.addEventListener("resize", scheduleSync);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
```

- [ ] **Step 2: Verify heat-strip navigation**

Run: `cd new/obs-data-example && python -m wave_explorer --suffix ds_leo`
Open `http://127.0.0.1:8050` and confirm:
- The heat-strip viewport box reflects the current spectrum x-range.
- Clicking the heat-strip jumps the spectrum view; dragging it scrubs the view.
- Panning/zooming the spectrum moves the viewport box in real time.

Stop the server when done.

---

## Task 8: Full integration verification

**Files:** none (verification only).

- [ ] **Step 1: Run the Python unit test**

Run: `cd new/obs-data-example && python -m pytest wave_explorer/tests/test_spectrum_payload.py -v`
Expected: 4 passed.

- [ ] **Step 2: Confirm no dead references to removed modules**

Run: `cd new/obs-data-example/wave_explorer && grep -rn "figure_builder\|build_base_figure\|drag_handles\|tooltip\.js\|update_figure_shapes" --include=*.py --include=*.js .`
Expected: no matches (only — if anything — comments you intentionally left). Any import or call site found must be cleaned up.

- [ ] **Step 3: Walk the spec's testing checklist**

Run: `cd new/obs-data-example && python -m wave_explorer --suffix ds_leo`, open `http://127.0.0.1:8050`, and verify each item from the spec's "Testing" section:
- App boots with no traceback; SVG spectrum renders.
- Pan: no drift at min and max zoom; a stationary click selects, does not pan.
- Zoom: wheel centers on cursor; clamps at min span (0.4 nm) and full range.
- Edge-drag: handles appear only on the selected region; release stages a pending change (pending badge increments).
- Draw: `D` → drag → popover → Accept appends a region.
- Excluded region shows faint-red dashed styling; X again (restore) reverts it.
- Tooltip shows the correct region # / χ² badge and the sampled obs/fit/resid.
- Heat-strip click/drag moves the view; the viewport box tracks pan.
- χ² coloring: bands match their quality tier; a pending edit shows the accent stripe without losing the quality color.
- Undo (`Z`) and Save (`⌘S`) still work — the side-panel callbacks were untouched.

Stop the server when done. Any failing item is a bug to fix before the plan is complete.

---

## Self-Review notes

- **Spec coverage:** Architecture (Tasks 3–4 remove the Plotly path; Task 6 adds `spectrum.js`); data flow / `spectrum-data-store` (Tasks 2–3, Task 6 sync callback); rendering (Task 6 `render*`); pan/zoom/select/drag/draw/hover (Task 6 pointer handlers); χ² coloring + states (Task 6 `qualityTier`/`renderRegions`); heat-strip rewiring (Task 7); CSS (Task 5); testing checklist (Task 8). All spec sections map to a task.
- **Contracts:** `drag-result-store` (`{region_idx, bound, new_x_nm}`), `draw-region-store` (`{lo, hi}`), `selected-region-store` (`{region_idx}`), `ll-entries-store`, `pending-changes-store`, and the `nav-btn` id shape are all consumed/produced exactly as the existing callbacks expect — `callbacks/regions.py`, `callbacks/table.py`, `callbacks/session.py` are untouched.
- **Naming consistency:** `window.WaveExplorer.{sync,getView,setView,onViewChange}` and `window.activateDrawMode` are defined in Task 6 and consumed in Task 7 and by the unchanged draw-mode callbacks in `callbacks/regions.py`. The `handles-sync-store` output id reused for the sync callback already exists in `layout.py`.
