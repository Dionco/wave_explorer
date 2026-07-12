# VALD Line Overlay Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a toolbar toggle to the Wave Explorer SVG spectrum that overlays VALD atomic/molecular line positions as vertical dashed lines so the user can identify which transitions produce each observed absorption feature. The line catalogue is read from `new/vald_lists/DionCobelens.017597` (VALD3 short format, ~9913 entries, 700–1000 nm vacuum).

**Architecture:** A new pure-Python module `wave_explorer/vald.py` parses the VALD file and projects entries into a compact JSON payload. The payload is shipped to the browser through a new `dcc.Store(id="vald-lines-store")`. The existing `spectrum.js` renderer gains a viewport-clipped pass that draws one dashed `<line>` per VALD entry plus a short label, gated by a `vald-visible-store` (boolean toggle) and a `vald-depth-min-store` (slider). The toggle button lives in the spectrum toolbar next to the existing zoom readout. No Python ↔ Python callback is required — the toggle's `n_clicks` flips a clientside store and `spectrum.js` re-renders.

**Tech Stack:** Python 3.9, Dash 4.1, vanilla JS (no build step), pytest 8.3.

**Conventions:**
- Per the repo owner's standing preference, **no git commit steps** are included. Commit yourself when ready.
- JS has no unit-test harness in this project. JS tasks are verified by running the app (`python -m wave_explorer --suffix ds_leo --vald-list /net/vdesk/data2/cobelens/MRP/new/vald_lists/DionCobelens.017597` from `new/obs-data-example/`) and checking behavior.
- Run all Python commands from `new/obs-data-example/` with the `asap` conda env active.

**Critical detail — vacuum vs air wavelengths:** VALD's `WL_vac` column is the vacuum wavelength in nm. The current Wave Explorer spectra come from ASAP/PHOENIX models which (for the NIR ds_leo / SPIRou regime, 700+ nm) are already vacuum. **Task 0 verifies this** before any code is written. If the spectra turn out to be in air for some other dataset, an air↔vacuum conversion (Ciddor 1996 / Morton 2000) must be added; the plan flags that branch but does not pre-implement it.

---

## File Structure

**Create:**
- `wave_explorer/vald.py` — VALD parser + payload builder (≈80 lines).
- `wave_explorer/tests/test_vald.py` — pytest unit tests for the parser and payload builder.

**Modify:**
- `wave_explorer/data_processing.py` — call `load_vald_list` from `build_dataset` when a path is provided; attach `dataset["vald_lines"]`.
- `wave_explorer/app.py` — add `--vald-list` CLI arg; add `vald-lines-store` / `vald-visible-store` / `vald-depth-min-store` inputs to the existing `WaveExplorer.sync` clientside callback; print VALD line count in the startup banner.
- `wave_explorer/layout.py` — embed VALD payload as `dcc.Store(id="vald-lines-store")`; add `vald-visible-store` + `vald-depth-min-store`; insert the toggle button and depth-min slider into the spectrum toolbar.
- `wave_explorer/assets/spectrum.js` — extend `sync()` to receive `vald`, `valdVisible`, `valdDepthMin`; add a `renderVald()` pass; extend the cursor tooltip to list nearby VALD lines.
- `wave_explorer/assets/styles.css` — add `.vald-line`, `.vald-label`, `.vald-toolbar-controls` rules.

All paths below are relative to `new/obs-data-example/wave_explorer/` unless noted.

---

## Task 0: Verify spectrum wavelength reference frame

**Files:** (read-only)
- Read: `wave_explorer/data_processing.py`, the `ds_leo` source spectra metadata, and the existing line list `wave_explorer/output_ds_leo_bic_optimal_blue_trimmed_llist`.

- [ ] **Step 1: Confirm the existing pipeline uses vacuum wavelengths**

Run from `new/obs-data-example/`:

```bash
grep -nE "vacuum|air|wl_vac|airvac|air2vac" -r ../code_vibing/helper_functions/ 2>/dev/null | head -40
grep -nE "vacuum|air" wave_explorer/data_processing.py
head -5 wave_explorer/output_ds_leo_bic_optimal_blue_trimmed_llist
```

Expected: PHOENIX models and the ds_leo / SPIRou pipeline use vacuum nm (no explicit air→vacuum conversion in `data_processing.py`). The existing line list centres (e.g. `700.0xx`) should line up with the VALD `WL_vac` values for the same transitions to within ~0.01 nm.

- [ ] **Step 2: Cross-check a single Fe I line**

Pick a strong line that exists in both: e.g. VALD line `Fe 1`, `700.18136 nm`, `Excit 4.1034 eV`, `log gf -1.560` from line 24 of the VALD file. Open `wave_explorer/output_ds_leo_bic_optimal_blue_trimmed_llist` and confirm the nearest Fe I region centre is ≤0.05 nm away.

Expected: yes → proceed assuming vacuum. If the offset is ~0.2 nm (air-vacuum shift at 700 nm is ≈0.193 nm) → add an `--air-input` flag to Task 1 + the Edlén/Ciddor conversion. **Do not code the conversion now; flag it and ask.**

---

## Task 1: VALD parser

**Files:**
- Create: `wave_explorer/vald.py`
- Create: `wave_explorer/tests/test_vald.py`

- [ ] **Step 1: Write the failing parser test**

Create `wave_explorer/tests/test_vald.py`:

```python
"""Tests for the VALD3-short-format parser in wave_explorer.vald."""
import textwrap

import pytest

from wave_explorer.vald import parse_vald_lines


VALD_SAMPLE = textwrap.dedent("""\
     700.00000, 1000.00000, 9913, 9817511, 1.0 Wavelength region, lines selected, lines processed, Vmicro
                                                     Damping parameters   Lande  Central
    Spec Ion      WL_vac(nm) Excit(eV) Vmic log gf*  Rad.   Stark  Waals  factor  depth  Reference
    'TiO 1',       700.00316,  0.9562, 1.0,  0.389, 6.944, 0.000, 0.000, 99.000, 0.123, '   1 wl:PPN2012 (48)TiO       '
    'Fe 1',        700.18136,  4.1034, 1.0, -1.560, 8.410,-5.270,-7.208,  1.410, 0.103, '   2 wl:K14   2 K14 Fe            '
    'Ca 2',        702.50000,  3.0000, 1.0,  0.500, 8.000, 0.000, 0.000,  1.000, 0.250, '   3 ref Ca            '
""")


def test_parse_skips_header_and_returns_entries(tmp_path):
    p = tmp_path / "vald.txt"
    p.write_text(VALD_SAMPLE)
    entries = parse_vald_lines(p)
    assert len(entries) == 3
    e0 = entries[0]
    assert e0["element"] == "TiO"
    assert e0["ion"] == 1
    assert e0["wavelength_nm"] == pytest.approx(700.00316)
    assert e0["excit_ev"] == pytest.approx(0.9562)
    assert e0["log_gf"] == pytest.approx(0.389)
    assert e0["central_depth"] == pytest.approx(0.123)


def test_parse_handles_negative_log_gf_and_ion_2(tmp_path):
    p = tmp_path / "vald.txt"
    p.write_text(VALD_SAMPLE)
    entries = parse_vald_lines(p)
    fe = entries[1]
    assert fe["element"] == "Fe" and fe["ion"] == 1
    assert fe["log_gf"] == pytest.approx(-1.560)
    ca = entries[2]
    assert ca["element"] == "Ca" and ca["ion"] == 2


def test_parse_ignores_blank_and_short_rows(tmp_path):
    p = tmp_path / "vald.txt"
    p.write_text(VALD_SAMPLE + "\n   \nnot-a-line\n")
    entries = parse_vald_lines(p)
    assert len(entries) == 3


def test_parse_returns_sorted_by_wavelength(tmp_path):
    p = tmp_path / "vald.txt"
    p.write_text(VALD_SAMPLE)
    entries = parse_vald_lines(p)
    assert entries == sorted(entries, key=lambda e: e["wavelength_nm"])
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
cd new/obs-data-example/
pytest wave_explorer/tests/test_vald.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'wave_explorer.vald'`.

- [ ] **Step 3: Implement the parser**

Create `wave_explorer/vald.py`:

```python
"""VALD3 short-format line-list parser.

VALD download files (Vienna Atomic Line Database, http://vald.astro.uu.se/)
in short format have a 3-line header followed by one data row per line.
Each data row is comma-separated and looks like:

    'Spec Ion',  WL_vac(nm), Excit(eV), Vmic, log gf, Rad., Stark,
                 Waals, Lande factor, Central depth, 'Reference...'

Where `'Spec Ion'` is the element symbol + ionisation stage (1 = neutral,
2 = singly ionised, ...) in single quotes — e.g. `'Fe 1'`, `'TiO 1'`,
`'Ca 2'`. Wavelengths are vacuum.

This module reads the file and returns a list of plain Python dicts —
no astropy dependency, no numpy.
"""

from pathlib import Path
from typing import List


def parse_vald_lines(path) -> List[dict]:
    """Parse a VALD3 short-format file and return per-transition dicts.

    Skips the standard 3-line header. Silently ignores any subsequent row
    that does not have at least 10 numeric fields after the quoted species
    label (these include trailing reference blocks and stray blank lines).
    The returned list is sorted by wavelength.
    """
    entries: List[dict] = []
    with open(Path(path)) as fh:
        for idx, raw in enumerate(fh):
            if idx < 3:
                continue
            row = _parse_row(raw)
            if row is not None:
                entries.append(row)
    entries.sort(key=lambda e: e["wavelength_nm"])
    return entries


def _parse_row(raw: str):
    s = raw.strip()
    if not s or not s.startswith("'"):
        return None
    species_end = s.find("'", 1)
    if species_end <= 1:
        return None
    species = s[1:species_end].strip()
    rest = s[species_end + 1:].lstrip(", ").strip()
    if not rest:
        return None
    # Drop the trailing reference (also quoted), if present.
    ref_start = rest.find("'")
    if ref_start >= 0:
        rest = rest[:ref_start]
    parts = [p.strip() for p in rest.split(",") if p.strip()]
    if len(parts) < 10:
        return None
    try:
        wavelength_nm = float(parts[0])
        excit_ev = float(parts[1])
        log_gf = float(parts[3])
        central_depth = float(parts[9])
    except ValueError:
        return None
    element, _, ion_str = species.partition(" ")
    try:
        ion = int(ion_str.strip() or "1")
    except ValueError:
        ion = 1
    return {
        "element": element,
        "ion": ion,
        "wavelength_nm": wavelength_nm,
        "excit_ev": excit_ev,
        "log_gf": log_gf,
        "central_depth": central_depth,
    }
```

- [ ] **Step 4: Run the test to verify it passes**

```bash
cd new/obs-data-example/
pytest wave_explorer/tests/test_vald.py -v
```

Expected: PASS for all four tests.

- [ ] **Step 5: Sanity-check against the real VALD file**

```bash
cd new/obs-data-example/
python -c "from wave_explorer.vald import parse_vald_lines; e = parse_vald_lines('/net/vdesk/data2/cobelens/MRP/new/vald_lists/DionCobelens.017597'); print(len(e), e[0], e[-1])"
```

Expected: `9911` or `9913` entries, first entry `TiO 1` at `700.00316 nm`, last entry `Ti 1` at `995.17343 nm`.

---

## Task 2: VALD payload builder

**Files:**
- Modify: `wave_explorer/vald.py`
- Modify: `wave_explorer/tests/test_vald.py`

- [ ] **Step 1: Write the failing payload-builder test**

Append to `wave_explorer/tests/test_vald.py`:

```python
import json
import math

from wave_explorer.vald import build_vald_payload


def _entries():
    return [
        {"element": "Fe", "ion": 1, "wavelength_nm": 700.18,
         "excit_ev": 4.10, "log_gf": -1.56, "central_depth": 0.10},
        {"element": "TiO", "ion": 1, "wavelength_nm": 700.00,
         "excit_ev": 0.96, "log_gf":  0.39, "central_depth": 0.12},
        {"element": "Ca", "ion": 2, "wavelength_nm": 850.00,
         "excit_ev": 3.00, "log_gf":  0.50, "central_depth": 0.25},
    ]


def test_payload_clips_to_wavelength_range():
    p = build_vald_payload(_entries(), lambda_min=700.0, lambda_max=701.0)
    assert len(p["lines"]) == 2
    # sorted by wavelength
    assert [ln["wavelength_nm"] for ln in p["lines"]] == [700.00, 700.18]


def test_payload_uses_parallel_arrays():
    p = build_vald_payload(_entries(), lambda_min=600.0, lambda_max=900.0)
    assert p["count"] == 3
    assert "wavelengths" in p and "elements" in p and "ions" in p
    assert "depths" in p and "logGf" in p and "excitEv" in p
    assert len(p["wavelengths"]) == 3
    assert len(p["elements"]) == 3
    # alignment
    i_fe = p["elements"].index("Fe")
    assert p["ions"][i_fe] == 1
    assert math.isclose(p["wavelengths"][i_fe], 700.18)


def test_payload_is_json_serializable():
    p = build_vald_payload(_entries(), lambda_min=600.0, lambda_max=900.0)
    json.dumps(p, allow_nan=False)


def test_payload_handles_empty_input():
    p = build_vald_payload([], lambda_min=600.0, lambda_max=900.0)
    assert p == {"count": 0, "wavelengths": [], "elements": [], "ions": [],
                 "depths": [], "logGf": [], "excitEv": [], "lines": [],
                 "depthMin": 0.0, "depthMax": 0.0}
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
pytest wave_explorer/tests/test_vald.py -v
```

Expected: FAIL with `ImportError: cannot import name 'build_vald_payload'`.

- [ ] **Step 3: Implement `build_vald_payload`**

Append to `wave_explorer/vald.py`:

```python
def build_vald_payload(
    entries: List[dict], lambda_min: float, lambda_max: float
) -> dict:
    """Build the JSON-serializable payload for the vald-lines-store.

    Filters entries to the [lambda_min, lambda_max] window and emits parallel
    arrays (wavelengths, elements, ions, depths, logGf, excitEv) keyed by
    index. Parallel arrays keep the payload compact and let the JS renderer
    do per-index lookups during a tight render loop without object churn.

    Also returns a `lines` list of dicts for compatibility with code that
    prefers row-oriented access (tests, future tooltips), and the
    [depthMin, depthMax] range so the UI can configure the depth slider.
    """
    in_range = [
        e for e in entries
        if lambda_min <= e["wavelength_nm"] <= lambda_max
    ]
    in_range.sort(key=lambda e: e["wavelength_nm"])
    depths = [float(e["central_depth"]) for e in in_range]
    return {
        "count": len(in_range),
        "wavelengths": [float(e["wavelength_nm"]) for e in in_range],
        "elements":    [str(e["element"]) for e in in_range],
        "ions":        [int(e["ion"]) for e in in_range],
        "depths":      depths,
        "logGf":       [float(e["log_gf"]) for e in in_range],
        "excitEv":     [float(e["excit_ev"]) for e in in_range],
        "lines": [dict(e) for e in in_range],
        "depthMin": min(depths) if depths else 0.0,
        "depthMax": max(depths) if depths else 0.0,
    }
```

- [ ] **Step 4: Run the test to verify it passes**

```bash
pytest wave_explorer/tests/test_vald.py -v
```

Expected: all 8 tests PASS.

---

## Task 3: Wire VALD into the dataset + CLI flag

**Files:**
- Modify: `wave_explorer/data_processing.py`
- Modify: `wave_explorer/app.py`

- [ ] **Step 1: Add `vald_path` parameter to `build_dataset`**

In `wave_explorer/data_processing.py`, find the `build_dataset` function signature (around line 538) and add an optional `vald_path` parameter:

```python
def build_dataset(
    retrievals_dir: Path,
    suffix: str,
    line_list_path: Optional[str],
    grid_step_nm: float = 0.01,
    smooth_window: int = 1,
    vald_path: Optional[str] = None,
) -> dict:
```

- [ ] **Step 2: Load VALD entries when a path is given**

Inside `build_dataset`, after `ll_entries = load_line_list(resolved_ll)` (around line 567), add:

```python
    from .vald import parse_vald_lines
    vald_entries: List[dict] = []
    if vald_path:
        vald_entries = parse_vald_lines(Path(vald_path).expanduser().resolve())
```

Then, in the returned dict (around line 630), add `vald_entries=vald_entries,` and a `vald_path=str(vald_path) if vald_path else None,` field.

- [ ] **Step 3: Add the `--vald-list` CLI flag and print the count**

In `wave_explorer/app.py`, in `main()` (around line 87), add a new argument after `--line-list`:

```python
    parser.add_argument(
        "--vald-list",
        default=None,
        help="Optional VALD3 short-format line list for the absorption-feature overlay.",
    )
```

In the call to `build_dataset` (around line 114), add the new keyword:

```python
    dataset = build_dataset(
        retrievals_dir=Path(args.retrievals_dir).resolve(),
        suffix=args.suffix,
        line_list_path=args.line_list,
        grid_step_nm=args.grid_step,
        smooth_window=args.smooth_window,
        vald_path=args.vald_list,
    )
```

And add a print line in the startup banner (after the `LL regions` line):

```python
    print(
        f"  VALD lines     : {len(dataset.get('vald_entries', []))}"
        f"  ({dataset.get('vald_path') or 'none'})"
    )
```

- [ ] **Step 4: Verify the CLI flag end-to-end**

```bash
cd new/obs-data-example/
python -m wave_explorer --suffix ds_leo \
  --vald-list /net/vdesk/data2/cobelens/MRP/new/vald_lists/DionCobelens.017597 \
  --port 8060 &
APP_PID=$!
sleep 4
curl -s http://127.0.0.1:8060/ -o /dev/null -w "%{http_code}\n"
kill $APP_PID
```

Expected: the startup banner prints `VALD lines     : 9911` (or similar) and the HTTP probe returns `200`.

---

## Task 4: Layout — VALD stores, toggle button, depth-min slider

**Files:**
- Modify: `wave_explorer/layout.py`

- [ ] **Step 1: Build the VALD payload at layout time**

At the top of `build_layout(dataset, debug_hover=...)` (around line 800), where `ll_entries_jsonable` is computed, add:

```python
    from .vald import build_vald_payload
    _common_w = dataset["common_w"]
    _vald_payload = build_vald_payload(
        dataset.get("vald_entries", []),
        lambda_min=float(_common_w[0]),
        lambda_max=float(_common_w[-1]),
    )
    _vald_loaded = _vald_payload["count"] > 0
```

- [ ] **Step 2: Add the toggle button + depth slider to the spectrum toolbar**

Find the `spectrum-toolbar` div (around line 819). Replace the existing children with:

```python
                                children=[
                                    html.Div(
                                        className="spectrum-toolbar-left",
                                        children=[
                                            html.Div(
                                                "Spectrum", className="eyebrow"
                                            ),
                                            html.Div(
                                                "Observation, fit & residuals",
                                                className="display-md",
                                            ),
                                        ],
                                    ),
                                    html.Div(
                                        className="vald-toolbar-controls",
                                        style={
                                            "display": "flex" if _vald_loaded
                                            else "none",
                                            "gap": "10px",
                                            "alignItems": "center",
                                        },
                                        children=[
                                            html.Button(
                                                "│ VALD lines",
                                                id="vald-toggle-btn",
                                                n_clicks=0,
                                                className="btn btn-sm",
                                                title="Show VALD atomic/"
                                                "molecular line positions",
                                            ),
                                            html.Span(
                                                "min depth",
                                                className="eyebrow",
                                            ),
                                            dcc.Slider(
                                                id="vald-depth-min-slider",
                                                min=0.0,
                                                max=1.0,
                                                step=0.05,
                                                value=0.10,
                                                marks={
                                                    0.0: "0",
                                                    0.25: "0.25",
                                                    0.5: "0.5",
                                                    0.75: "0.75",
                                                    1.0: "1",
                                                },
                                                tooltip={
                                                    "always_visible": False,
                                                    "placement": "bottom",
                                                },
                                            ),
                                        ],
                                    ),
                                    html.Div(
                                        "scroll to zoom · drag to pan · "
                                        "double-click resets",
                                        className="zoom-readout",
                                    ),
                                ],
```

- [ ] **Step 3: Add the three new stores + a toggle-state callback**

In the hidden-state-store block (around line 887), add:

```python
            dcc.Store(id="vald-lines-store", data=_vald_payload),
            dcc.Store(id="vald-visible-store", data=False),
            dcc.Store(id="vald-depth-min-store", data=0.10),
```

- [ ] **Step 4: Verify the layout still imports**

```bash
cd new/obs-data-example/
python -c "from wave_explorer.layout import build_layout; print('ok')"
```

Expected: `ok` (no ImportError, no runtime error).

---

## Task 5: Wire the toggle button + depth slider into Dash stores

**Files:**
- Modify: `wave_explorer/callbacks/__init__.py` (or `callbacks/candidate.py`)
- Modify: `wave_explorer/app.py`

- [ ] **Step 1: Register a clientside callback that flips `vald-visible-store` on button click**

In `wave_explorer/app.py`, after the existing `app.clientside_callback(...)` block (around line 61), add:

```python
    app.clientside_callback(
        """
        function(n) {
            if (!n) return false;
            return n % 2 === 1;
        }
        """,
        Output("vald-visible-store", "data"),
        Input("vald-toggle-btn", "n_clicks"),
    )

    app.clientside_callback(
        """
        function(v) { return v; }
        """,
        Output("vald-depth-min-store", "data"),
        Input("vald-depth-min-slider", "value"),
    )
```

- [ ] **Step 2: Wire the two new stores into the spectrum-sync callback**

In the same file, update the existing `app.clientside_callback` that feeds `WaveExplorer.sync` (around line 41) to also pass `valdLines`, `valdVisible`, `valdDepthMin`:

```python
    app.clientside_callback(
        """
        function(specData, llEntries, pending, selected, drawActive, goto,
                vald, valdVisible, valdDepthMin) {
            var args = [specData, llEntries, pending, selected, drawActive,
                        goto, vald, valdVisible, valdDepthMin];
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
        Input("goto-region-store", "data"),
        Input("vald-lines-store", "data"),
        Input("vald-visible-store", "data"),
        Input("vald-depth-min-store", "data"),
    )
```

- [ ] **Step 3: Verify the app still starts and the new button is in the DOM**

```bash
cd new/obs-data-example/
python -m wave_explorer --suffix ds_leo \
  --vald-list /net/vdesk/data2/cobelens/MRP/new/vald_lists/DionCobelens.017597 \
  --port 8060 &
APP_PID=$!
sleep 4
curl -s http://127.0.0.1:8060/ | grep -o 'vald-toggle-btn' | head -1
kill $APP_PID
```

Expected: prints `vald-toggle-btn` once.

---

## Task 6: spectrum.js — render VALD vertical dashed lines

**Files:**
- Modify: `wave_explorer/assets/spectrum.js`

- [ ] **Step 1: Add module-level VALD state**

At the top of the IIFE, after `var fluxRange = null;` (around line 42), add:

```javascript
  // ── VALD overlay state ───────────────────────────────────────────────────
  var vald = null;          // {wavelengths, elements, ions, depths, ...}
  var valdVisible = false;
  var valdDepthMin = 0.10;
```

- [ ] **Step 2: Add the `renderVald()` pass**

After the `renderRegions()` function (around line 393), add:

```javascript
  function renderVald() {
    var g = el("g", { class: "vald-overlay", "pointer-events": "none" });
    if (!valdVisible || !vald || !vald.wavelengths) return g;
    var w = vald.wavelengths;
    var labelStepPx = 36;
    var lastLabelPx = -Infinity;
    var topY = MAIN.top + 4;
    var botY = MAIN.top + MAIN.h;
    for (var i = 0; i < w.length; i++) {
      var lam = w[i];
      if (lam < view.min || lam > view.max) continue;
      if (vald.depths[i] < valdDepthMin) continue;
      var x = xScale(lam);
      var col = elementColor(vald.elements[i]);
      // depth maps to opacity so weak lines are quiet
      var opacity = Math.min(1, 0.35 + 0.65 * vald.depths[i]);
      g.appendChild(el("line", {
        class: "vald-line",
        x1: x, x2: x, y1: topY, y2: botY,
        stroke: col, "stroke-width": 1, "stroke-dasharray": "3 3",
        opacity: opacity,
      }));
      if (x - lastLabelPx >= labelStepPx) {
        g.appendChild(el("text", {
          class: "vald-label", x: x + 2, y: topY + 9,
          fill: col, opacity: opacity,
        }, vald.elements[i] + " " + romanize(vald.ions[i])));
        lastLabelPx = x;
      }
    }
    return g;
  }
```

- [ ] **Step 3: Insert the VALD pass into the main `render()` pipeline**

In `render()` (around line 244), after `parts.push(renderRegions());` and before the data-lines block, add:

```javascript
    // VALD line overlay (vertical dashed markers, below data lines so they
    // do not occlude the obs/fit curves)
    parts.push(renderVald());
```

- [ ] **Step 4: Extend `sync()` to receive the three new args**

Replace the `sync` function signature + body (around line 764) so it accepts and stores the new args:

```javascript
  function sync(specData, entries, pending, selected, drawActive, goto,
                valdPayload, visible, depthMin) {
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
    if (valdPayload != null) vald = valdPayload;
    if (visible != null) valdVisible = !!visible;
    if (depthMin != null && isFinite(+depthMin)) valdDepthMin = +depthMin;
    wirePopover();

    if (goto && goto.tick != null && goto.tick !== lastGotoTick) {
      lastGotoTick = goto.tick;
      if (goto.region_idx != null) frameRegion(goto.region_idx);
    }
    scheduleRender();
  }
```

- [ ] **Step 5: Verify in the browser**

```bash
cd new/obs-data-example/
python -m wave_explorer --suffix ds_leo \
  --vald-list /net/vdesk/data2/cobelens/MRP/new/vald_lists/DionCobelens.017597 \
  --port 8060 --debug
```

Open `http://127.0.0.1:8060/` and:
1. Verify the spectrum renders as before (toggle OFF by default → no VALD lines).
2. Click `| VALD lines` → vertical dashed lines appear coloured per element, with small element labels at the top.
3. Drag the `min depth` slider down to 0 → many more (faint) lines appear; up to 0.5 → only the strongest lines remain.
4. Pan and zoom → VALD lines redraw at the new positions without lag.

If lines do not appear or appear shifted by ~0.2 nm, this is the vacuum/air problem from Task 0 — stop and ask.

---

## Task 7: VALD lines in the cursor tooltip

**Files:**
- Modify: `wave_explorer/assets/spectrum.js`

- [ ] **Step 1: Add a nearest-VALD-lines lookup helper**

After `regionStats()` (around line 109), add:

```javascript
  function nearbyVald(lambda, halfWidthNm, maxRows) {
    if (!vald || !vald.wavelengths || !valdVisible) return [];
    var w = vald.wavelengths;
    var hits = [];
    for (var i = 0; i < w.length; i++) {
      if (vald.depths[i] < valdDepthMin) continue;
      var dl = w[i] - lambda;
      if (dl < -halfWidthNm) continue;
      if (dl > halfWidthNm) break;  // sorted → can short-circuit
      hits.push({ idx: i, dist: Math.abs(dl) });
    }
    hits.sort(function (a, b) { return a.dist - b.dist; });
    return hits.slice(0, maxRows);
  }
```

- [ ] **Step 2: Render VALD rows in `updateTooltip`**

In `updateTooltip` (around line 660), before the `tip.innerHTML = head + ...` line, build a VALD block:

```javascript
    var valdHtml = "";
    var near = nearbyVald(cl, 0.08, 4);
    if (near.length) {
      valdHtml = '<div class="tt-sep"></div>'
        + '<div class="tt-row"><span>VALD nearby</span><span></span></div>';
      for (var k = 0; k < near.length; k++) {
        var ni = near[k].idx;
        var lab = vald.elements[ni] + " " + romanize(vald.ions[ni]);
        var lamS = vald.wavelengths[ni].toFixed(3);
        var dpS = vald.depths[ni].toFixed(2);
        valdHtml += ttRow(lab + " @ " + lamS, "d=" + dpS);
      }
    }
```

Then append it to the tooltip HTML:

```javascript
    tip.innerHTML = head +
      ttRow("cursor λ", cl.toFixed(3)) +
      ttRow("obs flux", sampleAt("flux", cl).toFixed(4)) +
      ttRow("fit", sampleAt("fitFlux", cl).toFixed(4)) +
      ttRow("resid", (resid >= 0 ? "+" : "") + resid.toFixed(4)) +
      valdHtml;
```

- [ ] **Step 3: Verify in the browser**

Restart the app, enable the VALD toggle, hover over a strong absorption feature. The tooltip should list up to 4 nearby VALD lines with element label, wavelength, and central depth.

---

## Task 8: CSS — VALD line styling

**Files:**
- Modify: `wave_explorer/assets/styles.css`

- [ ] **Step 1: Add `.vald-line`, `.vald-label`, and toolbar control rules**

Append to `wave_explorer/assets/styles.css`:

```css
/* ── VALD line overlay ─────────────────────────────────────────────────── */
.vald-line {
  pointer-events: none;
}
.vald-label {
  font-family: var(--font-mono, monospace);
  font-size: 9px;
  font-weight: 600;
  text-anchor: start;
  pointer-events: none;
}
.vald-toolbar-controls {
  font-size: 12px;
}
.vald-toolbar-controls .rc-slider {
  width: 160px;
  margin: 0 8px;
}
```

- [ ] **Step 2: Verify the toolbar layout in the browser**

Restart the app and confirm the VALD button + slider sit cleanly inside the spectrum toolbar without overlapping the zoom-readout text.

---

## Task 9: End-to-end manual verification

**Files:** (no edits)

- [ ] **Step 1: Launch the app with VALD enabled**

```bash
cd new/obs-data-example/
python -m wave_explorer --suffix ds_leo \
  --vald-list /net/vdesk/data2/cobelens/MRP/new/vald_lists/DionCobelens.017597 \
  --port 8060
```

- [ ] **Step 2: Checklist**

In the browser:

- [ ] Default state: VALD toggle OFF, no overlay.
- [ ] Click toggle → vertical dashed lines appear, coloured by element (Fe blue, TiO/Ti teal, Ca green, Na amber, …).
- [ ] Min-depth slider at `0.10` (default) shows ~tens of lines per visible nm; at `0` shows hundreds; at `0.5` shows a sparse selection.
- [ ] Pan / zoom / mouse-wheel zoom keep the lines anchored to the wavelength axis with no lag.
- [ ] Tooltip shows a "VALD nearby" section with up to 4 entries near the cursor.
- [ ] Region edit, region drag, draw-mode, undo, save, table "Go to" all still work unchanged.
- [ ] Click the toggle again → VALD lines disappear; toolbar slider remains.

- [ ] **Step 3: Launch WITHOUT `--vald-list`**

```bash
python -m wave_explorer --suffix ds_leo --port 8060
```

- [ ] Verify the VALD toolbar controls are hidden (display:none) and everything else works.

- [ ] **Step 4: Re-run the Python test suite**

```bash
cd new/obs-data-example/
pytest wave_explorer/tests/ -v
```

Expected: all tests PASS (the existing `test_spectrum_payload.py` plus the new `test_vald.py`).

---

## Self-Review Checklist

- [x] Spec coverage: toggle button (Task 4 + 5), vertical dashed lines (Task 6), data from VALD file (Task 1 + 3) — all covered.
- [x] Vacuum/air branch flagged but not pre-implemented (Task 0).
- [x] No placeholders — every step has either code or a runnable command with expected output.
- [x] Type/name consistency: `vald-lines-store`, `vald-visible-store`, `vald-depth-min-store`, `parse_vald_lines`, `build_vald_payload`, `vald_entries`, `vald_path` used uniformly across all tasks.
- [x] No git commit steps (per project convention).
