"""
Candidate Region Callbacks

Single owner of Output("spectrum-graph", "figure").
Uses @app.callback (instance-scoped) throughout to prevent duplicate
registration on Dash hot-reload.
"""

from typing import List, Optional, Tuple

import numpy as np
from dash import ALL, Input, Output, Patch, no_update
from dash import ctx as dash_ctx
from dash import html

from ..data_processing import compute_custom_region_chi2, compute_residual_metrics
from ..layout import render_stats
from ..theme import C, MONO


# ══════════════════════════════════════════════════════════════════════════════
# Helpers
# ══════════════════════════════════════════════════════════════════════════════


def clamp(lo: float, hi: float, mn: float, mx: float) -> Tuple[float, float]:
    lo = max(mn, min(mx, float(lo)))
    hi = max(mn, min(mx, float(hi)))
    return (lo, hi) if lo <= hi else (hi, lo)


# ══════════════════════════════════════════════════════════════════════════════
# Shape builders
# ══════════════════════════════════════════════════════════════════════════════

# Warm editorial region-band palette (Claude Design handoff).
SAVED_FILL = "rgba(79, 122, 77, 0.14)"     # good green
SAVED_LINE = "rgba(79, 122, 77, 0.55)"
PENDING_FILL = "rgba(184, 136, 41, 0.22)"  # fair amber
PENDING_LINE = "rgba(184, 136, 41, 0.90)"
ADDED_FILL = "rgba(179, 85, 59, 0.18)"     # terracotta accent
ADDED_LINE = "rgba(179, 85, 59, 0.90)"
EXCLUDED_FILL = "rgba(156, 61, 46, 0.07)"  # bad red, faint
EXCLUDED_LINE = "rgba(156, 61, 46, 0.42)"

# [H3 FIX] Residual reference lines, expressed as shapes so they survive
# Patch() updates (which replace the entire shapes array).
# Solid line at y=0, light dotted guides at y=+/-0.05.
HLINE_SHAPE = dict(
    type="line",
    xref="paper",
    yref="y2",
    x0=0,
    x1=1,
    y0=0,
    y1=0,
    line=dict(color="rgba(117,112,95,0.55)", width=1),
    layer="below",
)

HLINE_POS_GUIDE = dict(
    type="line",
    xref="paper",
    yref="y2",
    x0=0,
    x1=1,
    y0=0.05,
    y1=0.05,
    line=dict(color="rgba(117,112,95,0.30)", width=1, dash="dot"),
    layer="below",
)

HLINE_NEG_GUIDE = dict(
    type="line",
    xref="paper",
    yref="y2",
    x0=0,
    x1=1,
    y0=-0.05,
    y1=-0.05,
    line=dict(color="rgba(117,112,95,0.30)", width=1, dash="dot"),
    layer="below",
)


def _pick_style(entry, is_pending):
    """Pick fill / line color based on entry state + pending flag."""
    if entry.get("excluded", False):
        return EXCLUDED_FILL, EXCLUDED_LINE
    if is_pending:
        return PENDING_FILL, PENDING_LINE
    if entry.get("added", False):
        return ADDED_FILL, ADDED_LINE
    return SAVED_FILL, SAVED_LINE


def _build_ll_shapes(
    ll_entries: Optional[List[dict]],
    pending_changes: Optional[dict],
) -> List[dict]:
    """Build LL region shapes.

    Colors:
      - green: saved (baseline)
      - amber: pending (unsaved edits — adjust, exclude-toggle)
      - cyan : added in this session (not yet saved)
      - red-faint: excluded (kept on the plot for context)

    The residual y=0 reference hline is appended so Patch() updates preserve it.
    Shape index contract with drag_handles.js is maintained: 2 shapes per
    entry (y domain + y2 domain), in entry order.
    """
    pending_changes = pending_changes or {}
    shapes: List[dict] = []

    for idx, entry in enumerate(ll_entries or []):
        staged = pending_changes.get(str(idx))
        is_pending = staged is not None
        e = staged if is_pending else entry
        lower = float(e["lower"])
        upper = float(e["upper"])
        fill, line = _pick_style(e, is_pending)

        for yref in ("y domain", "y2 domain"):
            shapes.append(
                dict(
                    type="rect",
                    xref="x",
                    yref=yref,
                    x0=lower,
                    x1=upper,
                    y0=0,
                    y1=1,
                    fillcolor=fill,
                    line=dict(color=line, width=0.8),
                    layer="below",
                    editable=False,
                )
            )

    shapes.append(HLINE_SHAPE)
    shapes.append(HLINE_POS_GUIDE)
    shapes.append(HLINE_NEG_GUIDE)
    return shapes


# ══════════════════════════════════════════════════════════════════════════════
# Callback registration
# ══════════════════════════════════════════════════════════════════════════════


def register_candidate_callbacks(
    app, dataset, min_w, max_w, all_rows, debug_hover=False
):
    """Register all candidate region callbacks."""

    # ════════════════════════════════════════════════════════════
    # Callback 1 – nav-btn click selects the region
    #
    # The Candidate Region panel was removed; the old update_candidate_bounds
    # callback wrote nav clicks into candidate-range. Now a nav click
    # writes directly to selected-region-store so live stats and the
    # selected-region header both reflect the picked region.
    # ════════════════════════════════════════════════════════════
    @app.callback(
        Output("selected-region-store", "data", allow_duplicate=True),
        Input({"type": "nav-btn", "index": ALL}, "n_clicks"),
        prevent_initial_call=True,
    )
    def nav_to_region(nav_clicks):
        if not any(nav_clicks or []):
            return no_update
        tid = dash_ctx.triggered_id
        if not isinstance(tid, dict) or tid.get("type") != "nav-btn":
            return no_update
        idx = tid.get("index")
        if idx is None:
            return no_update
        return {"region_idx": int(idx)}


    # ════════════════════════════════════════════════════════════
    # Callback 3 – live stats (no figure output)
    #
    # Driven by the region clicked in the main figure
    # (selected-region-store, populated by the clientside clickData
    # handler in app.py, or by the table nav-btn via Callback 1).
    # Bounds follow pending edits so stats track drags before save.
    # ════════════════════════════════════════════════════════════
    @app.callback(
        Output("candidate-stats", "children"),
        Output("status-range", "children"),
        Input("selected-region-store", "data"),
        Input("ll-entries-store", "data"),
        Input("pending-changes-store", "data"),
    )
    def update_stats(selected_region, ll_entries_data, pending_changes):
        lo = hi = None
        if selected_region and ll_entries_data:
            idx = selected_region.get("region_idx")
            if idx is not None and 0 <= idx < len(ll_entries_data):
                base = ll_entries_data[idx]
                staged = (pending_changes or {}).get(str(idx))
                live = staged if isinstance(staged, dict) else base
                lo = float(live["lower"])
                hi = float(live["upper"])

        if lo is None or hi is None:
            return "Click a region in the spectrum to see statistics.", ""

        lo, hi = clamp(lo, hi, min_w, max_w)
        chi2 = compute_custom_region_chi2(dataset["fit_data_cache"], lo, hi)
        resid = compute_residual_metrics(dataset, lo, hi)

        if not np.isfinite(chi2["median_chi2"]):
            stats_div = html.Div(
                [
                    html.Div(
                        f"\u03bb  {lo:.3f} \u2013 {hi:.3f} nm",
                        style={
                            "fontFamily": MONO,
                            "fontSize": "11px",
                            "color": C["muted"],
                        },
                    ),
                    html.Div(
                        "No fitted pixels in this interval.",
                        style={
                            "color": C["dim"],
                            "marginTop": "8px",
                            "fontSize": "13px",
                        },
                    ),
                ]
            )
            return stats_div, f"{lo:.3f} \u2013 {hi:.3f} nm  \u00b7  no fitted pixels"

        return render_stats(chi2, resid, lo, hi), (
            f"{lo:.3f} \u2013 {hi:.3f} nm"
            f"  \u00b7  \u03c7\u00b2/N = {chi2['median_chi2']:.3f}"
        )

    # ════════════════════════════════════════════════════════════
    # Callback 4 – THE SINGLE FIGURE OWNER
    #
    # Always uses Patch() — preserves zoom/pan unconditionally, since
    # Patch does not touch axis state. _build_ll_shapes already computes
    # correct colors (saved/pending/added/excluded) from ll_entries_data
    # + pending_changes, so save / discard / drag / draw-accept all
    # produce visually correct output through the same path.
    #
    # Trade-off: hover overlays (added as Scatter traces in
    # build_base_figure) are NOT refreshed for newly-drawn regions until
    # the page reloads. Shapes are correct; tooltips for brand-new
    # regions show no overlay. Acceptable for curation workflow.
    # ════════════════════════════════════════════════════════════
    @app.callback(
        Output("spectrum-graph", "figure"),
        Input("ll-entries-store", "data"),
        Input("pending-changes-store", "data"),
        prevent_initial_call=True,
    )
    def update_figure_shapes(ll_entries_data, pending_changes):
        shapes = _build_ll_shapes(ll_entries_data, pending_changes)
        fig_patch = Patch()
        fig_patch["layout"]["shapes"] = shapes
        return fig_patch
