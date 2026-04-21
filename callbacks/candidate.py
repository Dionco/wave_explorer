"""
Candidate Region Callbacks

Single owner of Output("spectrum-graph", "figure").
Uses @app.callback (instance-scoped) throughout to prevent duplicate
registration on Dash hot-reload.
"""

from typing import List, Optional, Tuple

import numpy as np
from dash import ALL, Input, Output, Patch, State, no_update
from dash import ctx as dash_ctx
from dash import html

from ..data_processing import compute_custom_region_chi2, compute_residual_metrics
from ..figure_builder import _cand_shapes
from ..layout import render_stats
from ..theme import C, MONO


# ══════════════════════════════════════════════════════════════════════════════
# Helpers
# ══════════════════════════════════════════════════════════════════════════════


def parse_zoom_range(
    relayout_data: Optional[dict],
) -> Optional[Tuple[float, float]]:
    if not relayout_data:
        return None
    if "xaxis.range[0]" in relayout_data and "xaxis.range[1]" in relayout_data:
        return (
            float(relayout_data["xaxis.range[0]"]),
            float(relayout_data["xaxis.range[1]"]),
        )
    if "xaxis.range" in relayout_data:
        rr = relayout_data["xaxis.range"]
        if isinstance(rr, list) and len(rr) == 2:
            return float(rr[0]), float(rr[1])
    return None


def clamp(lo: float, hi: float, mn: float, mx: float) -> Tuple[float, float]:
    lo = max(mn, min(mx, float(lo)))
    hi = max(mn, min(mx, float(hi)))
    return (lo, hi) if lo <= hi else (hi, lo)


# ══════════════════════════════════════════════════════════════════════════════
# Shape builders
# ══════════════════════════════════════════════════════════════════════════════

SAVED_FILL = "rgba(62, 173, 90, 0.18)"
SAVED_LINE = "rgba(40, 150, 70, 0.80)"
PENDING_FILL = "rgba(255, 167, 38, 0.25)"
PENDING_LINE = "rgba(245, 130, 10, 0.95)"
ADDED_FILL = "rgba(88, 209, 235, 0.20)"
ADDED_LINE = "rgba(88, 209, 235, 0.95)"
EXCLUDED_FILL = "rgba(248, 81, 73, 0.06)"
EXCLUDED_LINE = "rgba(248, 81, 73, 0.40)"

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
    line=dict(color="rgba(120,130,150,0.55)", width=1),
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
    line=dict(color="rgba(120,130,150,0.25)", width=1, dash="dot"),
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
    line=dict(color="rgba(120,130,150,0.25)", width=1, dash="dot"),
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
    # Callback 1 – update candidate bounds
    # ════════════════════════════════════════════════════════════
    @app.callback(
        Output("candidate-range", "value"),
        Output("manual-lo", "value"),
        Output("manual-hi", "value"),
        Output("src-hint", "children", allow_duplicate=True),
        Output("src-hint", "className", allow_duplicate=True),
        Input("use-zoom-btn", "n_clicks"),
        Input("apply-manual-btn", "n_clicks"),
        Input("candidate-range", "value"),
        Input({"type": "nav-btn", "index": ALL}, "n_clicks"),
        State("manual-lo", "value"),
        State("manual-hi", "value"),
        State("spectrum-graph", "relayoutData"),
        # [L2 FIX] Read live ll-entries so nav-btn uses current bounds,
        # not the stale all_rows closure from registration time.
        State("ll-entries-store", "data"),
        prevent_initial_call=True,
    )
    def update_candidate_bounds(
        zoom_clicks,
        apply_clicks,
        cand_range,
        nav_clicks,
        manual_lo,
        manual_hi,
        relayout_data,
        ll_entries_data,
    ):
        tid = dash_ctx.triggered_id

        if isinstance(tid, dict) and tid.get("type") == "nav-btn":
            idx = tid["index"]
            if ll_entries_data and 0 <= idx < len(ll_entries_data):
                e = ll_entries_data[idx]
                lo, hi = clamp(e["lower"], e["upper"], min_w, max_w)
                return (
                    [lo, hi],
                    lo,
                    hi,
                    (
                        f"Navigated to {e.get('element', '?')} {e.get('ion', '?')}"
                        f"  {lo:.3f} \u2013 {hi:.3f} nm"
                    ),
                    "src-hint zoom",
                )

        if tid == "use-zoom-btn":
            zoom = parse_zoom_range(relayout_data)
            if zoom is None:
                return (
                    no_update,
                    no_update,
                    no_update,
                    "No active zoom \u2014 draw a zoom box on the spectrum first.",
                    "src-hint none",
                )
            lo, hi = clamp(zoom[0], zoom[1], min_w, max_w)
            return (
                [lo, hi],
                lo,
                hi,
                f"Set from graph zoom  \u00b7  {lo:.3f} \u2013 {hi:.3f} nm",
                "src-hint zoom",
            )

        if tid == "apply-manual-btn":
            if manual_lo is None or manual_hi is None:
                return (
                    no_update,
                    no_update,
                    no_update,
                    "Enter both bounds and click Apply.",
                    "src-hint none",
                )
            lo, hi = clamp(float(manual_lo), float(manual_hi), min_w, max_w)
            return (
                [lo, hi],
                lo,
                hi,
                f"Set from manual input  \u00b7  {lo:.3f} \u2013 {hi:.3f} nm",
                "src-hint manual",
            )

        if tid == "candidate-range" and cand_range:
            lo, hi = clamp(cand_range[0], cand_range[1], min_w, max_w)
            return (
                no_update,
                lo,
                hi,
                f"Adjusted via slider  \u00b7  {lo:.3f} \u2013 {hi:.3f} nm",
                "src-hint slider",
            )

        return no_update, no_update, no_update, no_update, no_update

    # ════════════════════════════════════════════════════════════
    # Callback 2 – apply drawn region to candidate slider
    # ════════════════════════════════════════════════════════════
    @app.callback(
        Output("candidate-range", "value", allow_duplicate=True),
        Output("manual-lo", "value", allow_duplicate=True),
        Output("manual-hi", "value", allow_duplicate=True),
        Output("src-hint", "children", allow_duplicate=True),
        Output("src-hint", "className", allow_duplicate=True),
        Input("draw-region-store", "data"),
        prevent_initial_call=True,
    )
    def apply_draw_region(draw_data):
        if not draw_data:
            return no_update, no_update, no_update, no_update, no_update
        lo = draw_data.get("lo")
        hi = draw_data.get("hi")
        if lo is None or hi is None:
            return no_update, no_update, no_update, no_update, no_update
        lo, hi = clamp(float(lo), float(hi), min_w, max_w)
        return (
            [lo, hi],
            lo,
            hi,
            f"Region drawn  \u00b7  {lo:.3f} \u2013 {hi:.3f} nm",
            "src-hint zoom",
        )

    # ════════════════════════════════════════════════════════════
    # Callback 3 – live stats (no figure output)
    # ════════════════════════════════════════════════════════════
    @app.callback(
        Output("candidate-stats", "children"),
        Output("status-range", "children"),
        Input("candidate-range", "value"),
    )
    def update_stats(candidate_range):
        if not candidate_range or len(candidate_range) != 2:
            return "Select a candidate range.", ""

        lo, hi = clamp(candidate_range[0], candidate_range[1], min_w, max_w)
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
        Input("candidate-range", "value"),
        Input("ll-entries-store", "data"),
        Input("pending-changes-store", "data"),
        prevent_initial_call=True,
    )
    def update_figure_shapes(candidate_range, ll_entries_data, pending_changes):
        shapes = _build_ll_shapes(ll_entries_data, pending_changes)
        if candidate_range and len(candidate_range) == 2:
            lo, hi = clamp(candidate_range[0], candidate_range[1], min_w, max_w)
            shapes += _cand_shapes(lo, hi)
        fig_patch = Patch()
        fig_patch["layout"]["shapes"] = shapes
        return fig_patch

    # ════════════════════════════════════════════════════════════
    # Callback 5 – zoom hint
    # ════════════════════════════════════════════════════════════
    @app.callback(
        Output("src-hint", "children", allow_duplicate=True),
        Output("src-hint", "className", allow_duplicate=True),
        Input("spectrum-graph", "relayoutData"),
        prevent_initial_call=True,
    )
    def reflect_zoom_hint(relayout_data):
        zoom = parse_zoom_range(relayout_data)
        if zoom is None:
            return no_update, no_update
        lo, hi = clamp(zoom[0], zoom[1], min_w, max_w)
        return (
            (
                f"Zoom detected  {lo:.3f} \u2013 {hi:.3f} nm"
                f"  \u00b7  click \u2295 Use Zoom to apply"
            ),
            "src-hint zoom",
        )
