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
from ..figure_builder import _cand_shapes, build_base_figure
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

# [H3 FIX] The residual y=0 reference line, expressed as a shape so it
# survives Patch() updates (which replace the entire shapes array).
HLINE_SHAPE = dict(
    type="line",
    xref="paper",
    yref="y2",
    x0=0,
    x1=1,
    y0=0,
    y1=0,
    line=dict(color="rgba(120,130,150,0.40)", width=1, dash="dot"),
    layer="below",
)


def _build_ll_shapes(
    ll_entries: Optional[List[dict]],
    pending_changes: Optional[dict],
) -> List[dict]:
    """Build LL region shapes; pending regions render amber, saved render green.

    Also appends the residual y=0 reference hline so the Patch path
    never accidentally drops it.
    """
    pending_idx = (
        set(int(k) for k in pending_changes.keys()) if pending_changes else set()
    )
    shapes: List[dict] = []

    for idx, entry in enumerate(ll_entries or []):
        e = pending_changes.get(str(idx), entry) if idx in pending_idx else entry
        lower = float(e["lower"])
        upper = float(e["upper"])
        fill = PENDING_FILL if idx in pending_idx else SAVED_FILL
        line = PENDING_LINE if idx in pending_idx else SAVED_LINE

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

    # Always include the hline so the Patch path preserves it.
    shapes.append(HLINE_SHAPE)
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
            if idx < len(all_rows):
                row = all_rows[idx]
                # Use live ll-entries bounds if available, fallback to
                # the static region_summary for the label.
                lo, hi = clamp(row["lower"], row["upper"], min_w, max_w)
                return (
                    [lo, hi],
                    lo,
                    hi,
                    (
                        f"Navigated to {row['element']} {row['ion']}"
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
    # FULL REBUILD on Discard or Save.  Returns the complete figure
    # so Plotly.react() receives every shape x0/x1 explicitly.
    # Zoom/pan preserved because uirevision="asap-main" is constant.
    #
    # PATCH for all other triggers (slider, drag).  Fast, no zoom reset.
    #
    # [M1 FIX] Inspect ctx.triggered (the list) instead of triggered_id
    # to correctly handle save (which fires both ll-entries-store and
    # pending-changes-store simultaneously).  Save takes priority.
    #
    # [L1 FIX] Added prevent_initial_call=True — the initial figure
    # is already built correctly by build_base_figure in app.py.
    # ════════════════════════════════════════════════════════════
    @app.callback(
        Output("spectrum-graph", "figure"),
        Input("candidate-range", "value"),
        Input("ll-entries-store", "data"),
        Input("pending-changes-store", "data"),
        prevent_initial_call=True,
    )
    def update_figure_shapes(candidate_range, ll_entries_data, pending_changes):
        triggered_ids = {t["prop_id"].split(".")[0] for t in dash_ctx.triggered}

        # Save takes priority when both stores fire simultaneously.
        is_save = "ll-entries-store" in triggered_ids
        is_discard = (
            not is_save
            and "pending-changes-store" in triggered_ids
            and not pending_changes
        )

        if is_discard or is_save:
            fig = build_base_figure(
                dataset,
                ll_entries_override=ll_entries_data,
                debug_hover=debug_hover,
            )
            if candidate_range and len(candidate_range) == 2:
                lo, hi = clamp(candidate_range[0], candidate_range[1], min_w, max_w)
                fig.update_layout(shapes=list(fig.layout.shapes) + _cand_shapes(lo, hi))
            return fig

        # Patch path — fast update for slider/drag changes.
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
