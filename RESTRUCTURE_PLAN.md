# Wave Explorer — Architectural Rebuild Plan

## Context

The current `wave_explorer/` Dash app (at `/net/vdesk/data2/cobelens/MRP/new/obs-data-example/wave_explorer/`) has working features — curate line-list regions, adjust/exclude/draw, save — but it keeps producing subtle interaction bugs (recent: "discarded regions stay green", "zoom resets on discard", shape/mirror drift, hover overlay staleness after draw).

Each bug has a patch, but the patches accumulate (see `[H3 FIX]`, `[C2 FIX]`, `[H5 FIX]`, `[M4-figbuild FIX]`, `[L4 PARTIAL FIX]` markers across the codebase). Root cause isn't any single bug — it's architecture: **state is mirrored across too many places, and the figure has two independent owners (Python Patch + JS `Plotly.relayout`)**.

This plan describes how to rebuild the UI layer (not the data pipeline) around a single source of truth, eliminate the custom drag JS in favour of native Plotly primitives, and collapse ~20 callbacks + 15 stores + 625 lines of JS into something maintainable.

## Goals

1. **One source of truth** for curation state (entries + their edit baselines). No mirrors, no signal stores.
2. **One owner** of `spectrum-graph.figure`. No JS relayout calls racing Python Patch.
3. **Stable region identity** via UUID, not positional index. Kills the "shape index contract" coupling.
4. **Native Plotly editing** for drag/draw. Delete 600+ lines of custom JS.
5. **No cross-file duplication** of color logic or shape builders.
6. **Zoom/pan preservation** guaranteed by construction (Patch-only updates).
7. Keep data pipeline (`build_dataset`, chi² metrics, line list I/O) unchanged — it is solid.

## Root-cause analysis of current bugs

| # | Architectural flaw | Symptom(s) |
|---|--------------------|------------|
| A1 | State split across `ll-entries-store` + `pending-changes-store` + `window.__llEntriesData` + `llEntries` (JS module-scoped) + `dataset["ll_entries"]` closure | "Discarded region stays green", stale hover, mutation-during-drag races |
| A2 | Figure has TWO writers: Python `update_figure_shapes` (`Patch`) and JS `resetShapesToEntries`/`stretchRegionShape` (`Plotly.relayout`) | Zoom resets on discard, intermittent visual glitches |
| A3 | Region identity = array index. JS keeps a shape-index contract "region `i` → shapes `i*2, i*2+1`" | Any change that reorders or inserts shapes silently breaks drag/hover |
| A4 | `_ll_shapes()` (figure_builder) and `_build_ll_shapes()` (candidate) are near-duplicate; colors defined in 4 files | Pending state not reflected on full rebuilds; drift between Patch path and initial render |
| A5 | 15 `dcc.Store` instances, 19 callbacks, 20 `allow_duplicate=True` outputs, signal stores (`discard-signal-store`, `save-toast-trigger`, `handles-sync-store`, `handles-hover-sync-store`) to route events between Python and JS | Ordering fragility; each new feature adds another `allow_duplicate` branch |
| A6 | Custom SVG overlay + mouse listeners + `window.dash_clientside.set_props` directly write Dash stores, bypassing callback DAG | Debugging requires reading 600 lines of JS + Python together |

## Proposed architecture

### Single state model

One store: `curation-state`. Structure:

```python
{
  "entries": [
    {
      "id": "u-a1b2c3",            # stable UUID assigned at load / draw time
      "lower": 540.123, "upper": 540.456,
      "element": "Fe", "ion": "1", "order": "0",
      "comment": "",
      "excluded": False,
      "origin": "loaded" | "added",
      "baseline": {"lower": 540.123, "upper": 540.456, "excluded": False}
                  # None for origin="added" (means "new, never saved")
    },
    ...
  ],
  "saved_path": "/path/to/last/curated.txt" | None
}
```

**Key idea:** an entry is "pending" iff `(lower, upper, excluded) != baseline`. No separate pending store. Discard = restore each entry from its baseline and drop `origin="added"` entries that were never saved.

### Single action dispatcher

One store: `action-store`. Every UI event (button click, shape drag-end, range draw, nav click) writes a small action dict:

```python
{"type": "drag_edit", "id": "u-a1b2c3", "lower": 540.1, "upper": 540.6}
{"type": "toggle_exclude", "id": "u-a1b2c3"}
{"type": "draw_accept", "lower": 541.0, "upper": 541.3}
{"type": "save"}
{"type": "discard"}
{"type": "nav", "id": "u-a1b2c3"}
```

One reducer callback: `Input("action-store", "data")`, `State("curation-state", "data")`, `Output("curation-state", "data")`. All mutation logic lives in one place, one function, testable in isolation.

### Single figure callback

```python
@callback(
    Output("spectrum-graph", "figure"),
    Input("curation-state", "data"),
    Input("candidate-range", "value"),
    prevent_initial_call=True,
)
def render(state, candidate):
    patch = Patch()
    patch["layout"]["shapes"] = build_shapes(state, candidate)
    return patch
```

`build_shapes(state, candidate)` lives in one place (`shapes.py`) and derives colors from entry state (loaded+baseline-match=green, loaded+diff=amber, added=cyan, excluded=red-faint). No duplication.

### Native Plotly shape editing (delete custom JS)

Plotly supports `editable=True` on shapes. When the user drags an edge, `relayoutData` contains `{"shapes[N].x0": <new>, "shapes[N].x1": <new>}`. A clientside callback (10 lines) translates this into an `action-store` write keyed by the UUID stored in the shape's `name` field.

Drawing: `dragmode="drawrect"` on a dedicated toggle. On release, `relayoutData` contains the new shape; clientside callback converts to `{"type": "draw_accept", ...}`.

This replaces `drag_handles.js` (625 lines) with ~40 lines of clientside JS for translation only. No SVG overlay, no shape-index math, no mouse listeners, no JS-side state.

### Tooltip strategy

Plotly's built-in hover already works. If we need richer tooltips (chi² per region), embed the stats into the shape's `label` / `hovertext` at build time rather than via separate hover overlay traces. This removes the per-region Scatter traces entirely and simplifies `figure_builder`.

### Store and callback budget

| Current | Proposed |
|---------|----------|
| 15 `dcc.Store` | 3 (`curation-state`, `action-store`, `ui-prefs` for filters/zoom hint) |
| 19 `@app.callback` | ~8 (reducer, figure, table render, element filter, stats, toast, draw-mode toggle, candidate-range sync) |
| 20 `allow_duplicate=True` outputs | 0 expected; 1–2 tolerable |
| 625 lines JS | ~40 lines clientside translators |
| 2 shape builders + 4 color locations | 1 of each |

## File plan

### Keep unchanged
- `data_processing.py` — I/O, chi², residual metrics. Good.
- `theme.py` — extend with full region-state color map; remove ad-hoc duplicates elsewhere.
- `__main__.py` — CLI entry.

### Rewrite
- `layout.py` — trim to essentials, drop signal stores, add uuid generation on load.
- `figure_builder.py` — pure shape rendering; delete hover overlay traces (replaced by native hover).
- `callbacks/` — collapse `candidate.py`, `regions.py`, `session.py`, `table.py` into:
  - `callbacks/reducer.py` — the single state reducer
  - `callbacks/figure.py` — the single figure render
  - `callbacks/ui.py` — nav, filter, toast, draw-mode toggle
- `app.py` — only Dash factory + cache; clientside callbacks live beside layout.

### New
- `shapes.py` — `build_shapes(state, candidate) -> list[dict]` + `REGION_COLORS` dict. Single source.
- `state.py` — `assign_uuids(entries)`, `reduce(action, state) -> new_state`, `is_pending(entry)` predicates. Pure functions, unit-testable without Dash.

### Delete
- `assets/drag_handles.js` (625 lines)
- `assets/tooltip.js` (if Plotly native hover is adequate) — evaluate during build
- All `*-signal-store`, `handles-sync-store`, `handles-hover-sync-store`, `draw-mode-active-store` (absorbed into `ui-prefs` or eliminated)

## Migration strategy

Big-bang in a side-by-side directory rather than incremental refactor. Reasons:
- The coupling is pervasive; incremental changes require keeping the old contracts alive and would not reduce bug surface.
- Data pipeline is stable and can be imported as-is.
- New build can live at `wave_explorer_v2/` until parity is reached, then swap the entry point.

Milestones:
1. **M1 Scaffolding** — `wave_explorer_v2/` with new `layout`, `figure_builder`, `shapes`, `state`. Renders static figure from the dataset.
2. **M2 Read-only** — table + candidate stats + nav + zoom. No mutations yet.
3. **M3 Edits** — native shape edit → action-store → reducer → figure Patch. Exclude toggle via table button.
4. **M4 Draw + Save/Discard** — draw mode, save to timestamped file, discard restores baselines.
5. **M5 Polish** — toast, last-saved chip, legend row, keyboard shortcuts (optional).
6. **M6 Swap** — replace `wave_explorer/` with `wave_explorer_v2/`, archive old. Update CLI in `__main__.py`.

Each milestone ends with a browser smoke test on `gj_1289` dataset.

## Critical files to reference during rebuild

- `/net/vdesk/data2/cobelens/MRP/new/obs-data-example/wave_explorer/data_processing.py` — reuse `build_dataset`, `load_line_list`, `save_curated_line_list`, `summarize_region_chi2`, `compute_custom_region_chi2`, `compute_residual_metrics`
- `/net/vdesk/data2/cobelens/MRP/new/obs-data-example/wave_explorer/theme.py` — reuse `C`, `MONO`, `chi2_color`, `chi2_label`, `_fmt`
- `/net/vdesk/data2/cobelens/MRP/new/obs-data-example/wave_explorer/layout.py:218-243` — existing color definitions to consolidate
- `/net/vdesk/data2/cobelens/MRP/new/obs-data-example/wave_explorer/figure_builder.py:234-474` — base figure layout (subplot structure, axis config, uirevision) — port as-is minus hover overlay traces
- `/net/vdesk/data2/cobelens/MRP/new/obs-data-example/wave_explorer/callbacks/table.py` — table row rendering logic — port with minor UUID adaptation

## Verification

End-to-end manual test matrix (run against `ds_leo` and `gj_1289`):

1. **Load + render** — 83 entries visible with correct colors; zoom preserved across all following steps.
2. **Exclude + Discard** — click exclude on a region → region turns red-faint → click Discard → region snaps back to green, zoom unchanged.
3. **Drag edge + Discard** — drag an edge → region turns amber → click Discard → edge snaps back, zoom unchanged.
4. **Drag edge + Save** — drag → Save → new `line_list_*_curated_<ts>.txt` written; region turns green (now baseline); toast shows success; last-saved chip updates.
5. **Draw + Save** — toggle draw mode → click-drag → confirm → new region (cyan) → Save → region turns green.
6. **Draw + Discard** — draw → Discard → new region disappears; zoom unchanged.
7. **Nav** — click table row → candidate range jumps to region; spectrum does NOT re-zoom (only candidate highlight moves).
8. **Element filter** — filter by Fe → table filters; spectrum unchanged.
9. **File round-trip** — reload saved file → all edits (adjusted bounds, exclusions, additions) persist; comments preserved.

Automated sanity:

```bash
cd /net/vdesk/data2/cobelens/MRP/new/obs-data-example && \
  /net/vdesk/data2/cobelens/.conda/envs/asap/bin/python -c \
  "from wave_explorer_v2.app import create_app; \
   from wave_explorer.data_processing import build_dataset; \
   from pathlib import Path; \
   ds = build_dataset(Path('06_retrievals'), 'ds_leo', None, 0.01, 1); \
   app = create_app(ds); print('OK', len(app.callback_map))"
```

Unit tests for `state.reduce` — pure Python, no Dash needed:

```python
def test_drag_edit_marks_pending():
    state = {"entries": [{"id": "a", "lower": 1.0, "upper": 2.0,
                          "baseline": {"lower": 1.0, "upper": 2.0, "excluded": False},
                          "excluded": False, "origin": "loaded"}],
             "saved_path": None}
    new = reduce({"type": "drag_edit", "id": "a", "lower": 1.1, "upper": 2.0}, state)
    assert is_pending(new["entries"][0])
    assert new["entries"][0]["lower"] == 1.1
```

## Risks & open questions

- **Plotly native edit UX differs** — native handles are small corner dots, not full-height edge stripes. Acceptable? If not, we can style shape `line.width` and keep `editable=True`; handles still appear.
- **Per-region hover without overlay traces** — Plotly shape `label.text` works but positioning/styling is limited. If the current rich tooltip (χ², star count, etc.) is required, we may need a minimal `tooltip.js` (~50 lines) reading from `hoverData` — still far less than today's.
- **Dash hot-reload still duplicates clientside callbacks** — mitigated by instance-scoped registration (already done in current code); carry that pattern.
- **Effort estimate** — milestones M1–M6 realistically ~3–4 focused sessions. Not a weekend job, but bounded.
