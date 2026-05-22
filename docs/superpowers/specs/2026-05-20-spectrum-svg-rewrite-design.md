# Spectrum graph — custom-SVG rewrite

_Design spec · 2026-05-20_

## Goal

Replace the Plotly main graph in `wave_explorer` with a custom inline-SVG
spectrum component that reproduces the interaction model of the Claude
Design handoff (`spectrum.jsx`). The current Plotly-based main graph works
but its UX diverges from the design; the design's model — buttery-smooth
pan, visible drag handles on the selected region, χ²-quality coloring,
cursor crosshair + tooltip — is the target.

Scope is the **main graph**: the flux panel, the residual panel, and the
heat-strip mini-map rewiring (heat-strip navigation drives the graph view,
so it is coupled). Side panels, header, worst-regions table and tweaks
panel are out of scope — they keep consuming the same Dash stores
unchanged.

## Reference

- Design bundle: `spectrum.jsx`, `styles.css`, `data.js` from Claude Design
  (`claude.ai/design`), fetched 2026-05-20.
- Current implementation: `redesign-claude-design` branch of `wave_explorer`.

## Architecture

### Component placement

The Plotly `dcc.Graph(id="spectrum-graph")` is replaced by a plain
`html.Div(id="spectrum-graph")` host. A new client-side module,
`assets/spectrum.js` (vanilla JS, no build step — consistent with the
existing `assets/*.js`), renders an inline `<svg>` into that host and owns
all interaction.

### Files removed

- `figure_builder.py` — Plotly figure construction.
- `assets/drag_handles.js` — edge-drag + draw logic (moves into `spectrum.js`).
- `assets/tooltip.js` — hover tooltip (moves into `spectrum.js`).
- The `update_figure_shapes` callback in `callbacks/candidate.py` (the
  single Plotly figure owner) and `build_base_figure` usage in `app.py`.

### Files rewired

- `assets/heatstrip.js` — instead of reading `gd._fullLayout.xaxis.range`
  and calling `Plotly.relayout`, it reads/writes the view through the
  public API that `spectrum.js` exposes (see below).

### Files unchanged

- `assets/keyboard.js` — only clicks existing controls.
- `callbacks/regions.py`, `callbacks/table.py`, `callbacks/session.py` —
  persistence and side-panel logic; consume the same stores.
- `callbacks/candidate.py` keeps `nav_to_region` and `update_stats`; only
  the figure-owner callback is removed.

### Non-negotiable contracts preserved

Store IDs and payload shapes are unchanged, so all Python callbacks keep
working as-is:

- `ll-entries-store` — region geometry/state (0-based list).
- `pending-changes-store` — staged edits keyed by string index.
- `drag-result-store` — `{region_idx, bound, new_x_nm}` on edge-drag commit.
- `draw-region-store` — `{lo, hi}` on draw-confirm accept.
- `selected-region-store` — `{region_idx}` (0-based) on region click.
- `ll-stats-store` — per-region stats for the tooltip.
- Nav button id shape `{"type": "nav-btn", "index": i}`.

## Data flow

### New store: `spectrum-data-store`

Populated **once at startup** in `layout.py` with JSON-serializable data
the renderer needs (≈2500 points × 4 arrays — well within store limits):

```
{
  wavelengths:  [float, ...],      # dataset["common_w"]
  flux:         [float, ...],      # dataset["mean_obs_s"]   (smoothed obs)
  fitFlux:      [float, ...],      # dataset["mean_fit_s"]
  resid:        [float, ...],      # dataset["mean_resid_s"]
  lambdaMin:    float,
  lambdaMax:    float,
  chi2ByRegion: { "<idx>": float },# from dataset["region_summary"], same
                                   # construction as layout.build_heatstrip
  chi2Thresholds: [good, fair, poor],   # mirrors theme.py (5, 15, 30)
  elementColors: { "Fe": "#...", ... }, # element → hex; reuse the design's
                                        # --elem-* palette, neutral fallback
}
```

`theme.py` stays the single source of truth for χ² thresholds and colors;
they are copied into the store so the JS does not hard-code them.

### Reactive region updates

`spectrum.js` re-renders the region bands whenever `ll-entries-store` or
`pending-changes-store` changes, via a thin clientside callback (same
pattern as the current `__llEntriesData` sync in `app.py`). Region
geometry, `excluded`, and `added` flags come from those stores; static χ²
comes from `spectrum-data-store`.

### Client-owned state (no store)

- Current view (λ `{min, max}`) — pan/zoom state.
- Hovered region index, draw-mode flag, in-flight drag/draw gesture.

### Writes back to Dash

- Region click → `set_props("selected-region-store", {region_idx})`.
- Edge-drag commit → `set_props("drag-result-store", {...})`.
- Draw accept → existing `draw-confirm-popover` → `draw-region-store`.

### Public API exposed by `spectrum.js`

```
window.WaveExplorer = {
  getView():        {min, max},
  setView(min,max): void,          // used by heat-strip navigation
  onViewChange(cb): void,          // heat-strip viewport tracking
}
```

## Rendering

Two stacked panels sharing one X axis, geometry per `spectrum.jsx`
(`PLOT_W`, `MAIN`, `RESID`, `PAD` constants — kept as the design has them,
the SVG uses `preserveAspectRatio="none"` so it scales to the container).

**Main flux panel**

- Observation line — ink-grey (`.obs-line`).
- Fit line — terracotta accent (`.fit-line`).
- Dashed continuum reference at flux = 1.0.
- Y-range autoscaled from obs/fit with small padding (the design's fixed
  0.2–1.08 was synthetic; real data varies).

**Residual panel**

- `obs − fit` line, zero reference line.
- Outlier dots where `|resid|` exceeds a threshold (accent if positive,
  ink if negative), per the design.
- Y-range autoscaled symmetric from the residual data.

**Per region** (band spans both panels)

- Quality-colored fill + stroke (see χ² coding below).
- 2px quality stripe at the band top.
- 3px element rail at the band bottom, colored by species.
- Element label (`El <roman ion>`) when the band is wide enough.

**Chrome**

- Grid lines, X ticks/labels (adaptive step), Y ticks/labels for both
  panels, axis titles, in-plot legend (obs / fit / resid).

## Interaction model

All interaction uses pointer events with `setPointerCapture`, so a gesture
survives the pointer leaving the SVG. View updates are RAF-throttled.

### Pan

Drag an empty area of the plot. A 4px movement threshold gates pan
activation — below it, the gesture is a click (region select). View delta
is computed from the pixel delta against the **view locked at
pointer-down**, so pan does not drift at any zoom level. Clamped via a
single `clampView` helper (min span + full λ range max).

### Zoom

Mouse wheel, centered on the cursor's λ. Same `clampView` clamping.

### Select

A click (sub-threshold press) on a region writes `{region_idx}` to
`selected-region-store`. A click on empty space clears it. The selected
region glows; all other regions dim to opacity 0.4.

### Adjust bounds

Visible ink drag handles render **only on the selected region** — pill
handles with 16px transparent hit zones, a dashed guide line through both
panels, `ew-resize` cursor, accent on hover. Dragging an edge:

- previews live by calling the drag handler with `committed: false` (the
  band stretches; mirrors the current `stage_drag` preview path),
- on release commits `{region_idx, bound, new_x_nm}` to `drag-result-store`
  (`bound` is `"lower"`/`"upper"`), where the existing `stage_drag`
  callback stages it as a pending change.

Minimum region width is enforced client-side (0.005 nm) and re-clamped
server-side, as today.

### Draw

Toggling draw mode (`D` key or the draw button) sets the crosshair cursor.
A drag draws a dashed terracotta preview rectangle; on release, the
existing `draw-confirm-popover` opens at the pointer with the λ range and
Accept/Cancel. Accept writes `{lo, hi}` to `draw-region-store`; the
existing `accept_drawn_region` callback appends the new entry. `Escape`
cancels an in-flight draw and exits draw mode.

### Hover + tooltip

A dashed vertical crosshair tracks the cursor through both panels. A dark
cursor-following tooltip (`.cursor-tooltip`) shows:

- region # + quality badge (when over a region), λ bounds;
- the obs / fit / resid values sampled at the cursor λ.

The tooltip is fully client-side — no server round-trip (the current
implementation round-trips hover through `tooltip-sync-store`).

## χ² color coding & region states

Region bands are colored by **χ² quality tier** (the change explicitly
requested), using `theme.py`'s thresholds and the 4-tier ramp (identical
hex in the design and `theme.py`):

| tier | χ²/N        | color     |
|------|-------------|-----------|
| good | `< 5`       | `#4f7a4d` |
| fair | `5 – 15`    | `#b88829` |
| poor | `15 – 30`   | `#c87338` |
| bad  | `≥ 30`      | `#9c3d2e` |
| miss | non-finite  | `#9c9684` |

Region state overlays the quality color:

- **Excluded** — faint red fill `rgba(156,61,46,0.07)` + dashed red border;
  element rail and label dimmed. (Excluded regions stay visible for
  context — they are not removed.)
- **Pending** (unsaved edit, present in `pending-changes-store`) — a thin
  terracotta accent stripe near the band top, so the χ² color stays
  readable.
- **Selected** — glow outline; **hovered** — stroke outline.

Open assumption: thresholds `5 / 15 / 30` are kept from `theme.py` (tuned
for real ASAP data; the design's `1.5 / 3 / 6` were for synthetic data).
Change if real fit quality calls for different bins.

## Testing

- Module imports / app boots without the removed Plotly figure path.
- `python -m wave_explorer --suffix ds_leo` renders the SVG spectrum.
- Pan: no drift at min and max zoom; stationary click selects, does not pan.
- Zoom: wheel centers on cursor; clamps at min span and full range.
- Edge-drag: handles appear only on the selected region; release stages a
  pending change visible in the pending badge.
- Draw: `D` → drag → popover → Accept appends a region.
- Excluded region shows faint-red dashed styling; toggling restore reverts.
- Tooltip shows correct region # / χ² badge and sampled obs/fit/resid.
- Heat-strip click/drag moves the spectrum view; viewport box tracks pan.
- χ² coloring: bands match their quality tier; pending edits show the
  accent stripe without losing the quality color.
