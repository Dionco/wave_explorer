"""
Candidate Region Callbacks

This module is the SINGLE OWNER of Output("spectrum-graph", "figure").
All shape changes — LL regions, pending edits, candidate highlight — are
patched through update_figure_shapes(). No other callback may output to
spectrum-graph.figure.
"""

from typing import Optional, Tuple

import numpy as np
from dash import ALL, Input, Output, Patch, State, callback, ctx, html, no_update

from ..data_processing import compute_custom_region_chi2, compute_residual_metrics
from ..figure_builder import _cand_shapes
from ..layout import render_stats
from ..theme import C, MONO


def parse_zoom_range(relayout_data: Optional[dict]) -> Optional[Tuple[float, float]]:
    """Extract xaxis zoom range from relayout_data."""
    if not relayout_data:
        return None
    if "xaxis.range[0]" in relayout_data and "xaxis.range[1]" in relayout_data:
        return float(relayout_data["xaxis.range[0]"]), float(relayout_data["xaxis.range[1]"])
    if "xaxis.range" in relayout_data:
        rr = relayout_data["xaxis.range"]
        if isinstance(rr, list) and len(rr) == 2:
            return float(rr[0]), float(rr[1])
    return None


def clamp(lo: float, hi: float, mn: float, mx: float) -> Tuple[float, float]:
    """Clamp bounds to [mn, mx] and ensure lo <= hi."""
    lo = max(mn, min(mx, float(lo)))
    hi = max(mn, min(mx, float(hi)))
    return (lo, hi) if lo <= hi else (hi, lo)


def _build_ll_shapes(ll_entries, pending_changes):
    """
    Build LL region shapes with pending-aware coloring.
    Pending regions render amber; saved regions render green.
    """
    saved_fill   = "rgba(62, 173, 90, 0.18)"
    saved_line   = "rgba(40, 150, 70, 0.80)"
    pending_fill = "rgba(255, 167, 38, 0.25)"
    pending_line = "rgba(245, 130, 10, 0.95)"

    pending_idx = set(int(k) for k in pending_changes.keys()) if pending_changes else set()
    shapes = []

    for idx, entry in enumerate(ll_entries or []):
        # Use the pending version of this entry if one exists.
        e = pending_changes.get(str(idx), entry) if idx in pending_idx else entry
        lower = float(e["lower"])
        upper = float(e["upper"])
        fill  = pending_fill if idx in pending_idx else saved_fill
        line  = pending_line if idx in pending_idx else saved_line

        for yref in ("y domain", "y2 domain"):
            shapes.append(dict(
                type="rect", xref="x", yref=yref,
                x0=lower, x1=upper, y0=0, y1=1,
                fillcolor=fill, line=dict(color=line, width=0.8),
                layer="below", editable=False,
            ))

    return shapes


def register_candidate_callbacks(app, dataset, min_w, max_w, all_rows, debug_hover=False):
    """Register all candidate region callbacks."""

    # ════════════════════════════════════════════════════════════
    # Callback 1 – update candidate bounds (zoom / manual / slider / draw)
    # ════════════════════════════════════════════════════════════
    @callback(
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
        prevent_initial_call=True,
    )
    def update_candidate_bounds(
        zoom_clicks, apply_clicks, cand_range, nav_clicks,
        manual_lo, manual_hi, relayout_data,
    ):
        tid = ctx.triggered_id

        # ── Navigate from table row ────────────────────────────
        if isinstance(tid, dict) and tid.get("type") == "nav-btn":
            idx = tid["index"]
            if idx < len(all_rows):
                row = all_rows[idx]
                lo, hi = clamp(row["lower"], row["upper"], min_w, max_w)
                msg = f"Navigated to {row['element']} {row['ion']}  {lo:.3f} – {hi:.3f} nm"
                return [lo, hi], lo, hi, msg, "src-hint zoom"

        # ── Use current zoom ───────────────────────────────────
        if tid == "use-zoom-btn":
            zoom = parse_zoom_range(relayout_data)
            if zoom is None:
                return (no_update, no_update, no_update,
                        "No active zoom — draw a zoom box on the spectrum first.",
                        "src-hint none")
            lo, hi = clamp(zoom[0], zoom[1], min_w, max_w)
            return ([lo, hi], lo, hi,
                    f"Set from graph zoom  ·  {lo:.3f} – {hi:.3f} nm",
                    "src-hint zoom")

        # ── Apply manual ───────────────────────────────────────
        if tid == "apply-manual-btn":
            if manual_lo is None or manual_hi is None:
                return (no_update, no_update, no_update,
                        "Enter both bounds and click Apply.", "src-hint none")
            lo, hi = clamp(float(manual_lo), float(manual_hi), min_w, max_w)
            return ([lo, hi], lo, hi,
                    f"Set from manual input  ·  {lo:.3f} – {hi:.3f} nm",
                    "src-hint manual")

        # ── Slider moved ───────────────────────────────────────
        if tid == "candidate-range" and cand_range:
            lo, hi = clamp(cand_range[0], cand_range[1], min_w, max_w)
            return (no_update, lo, hi,
                    f"Adjusted via slider  ·  {lo:.3f} – {hi:.3f} nm",
                    "src-hint slider")

        return no_update, no_update, no_update, no_update, no_update

    # ════════════════════════════════════════════════════════════
    # Callback 2 – apply drawn region to candidate slider  (Bug 4 fix)
    # ════════════════════════════════════════════════════════════
    @callback(
        Output("candidate-range", "value", allow_duplicate=True),
        Output("manual-lo", "value", allow_duplicate=True),
        Output("manual-hi", "value", allow_duplicate=True),
        Output("src-hint", "children", allow_duplicate=True),
        Output("src-hint", "className", allow_duplicate=True),
        Input("draw-region-store", "data"),
        prevent_initial_call=True,
    )
    def apply_draw_region(draw_data):
        """Wire the draw-confirm popover result into the candidate slider."""
        if not draw_data:
            return no_update, no_update, no_update, no_update, no_update
        lo = draw_data.get("lo")
        hi = draw_data.get("hi")
        if lo is None or hi is None:
            return no_update, no_update, no_update, no_update, no_update
        lo, hi = clamp(float(lo), float(hi), min_w, max_w)
        return (
            [lo, hi], lo, hi,
            f"Region drawn  ·  {lo:.3f} – {hi:.3f} nm",
            "src-hint zoom",
        )

    # ════════════════════════════════════════════════════════════
    # Callback 3 – live stats (candidate-range only, no figure)
    # ════════════════════════════════════════════════════════════
    @callback(
        Output("candidate-stats", "children"),
        Output("status-range", "children"),
        Input("candidate-range", "value"),
    )
    def update_stats(candidate_range):
        if not candidate_range or len(candidate_range) != 2:
            return "Select a candidate range.", ""

        lo, hi = clamp(candidate_range[0], candidate_range[1], min_w, max_w)
        chi2   = compute_custom_region_chi2(dataset["fit_data_cache"], lo, hi)
        resid  = compute_residual_metrics(dataset, lo, hi)

        if not np.isfinite(chi2["median_chi2"]):
            stats_div = html.Div([
                html.Div(f"λ  {lo:.3f} – {hi:.3f} nm",
                         style={"fontFamily": MONO, "fontSize": "11px", "color": C["muted"]}),
                html.Div("No fitted pixels in this interval.",
                         style={"color": C["dim"], "marginTop": "8px", "fontSize": "13px"}),
            ])
            status_txt = f"{lo:.3f} – {hi:.3f} nm  ·  no fitted pixels"
        else:
            stats_div  = render_stats(chi2, resid, lo, hi)
            status_txt = (
                f"{lo:.3f} – {hi:.3f} nm  ·  "
                f"χ²/N = {chi2['median_chi2']:.3f}"
            )

        return stats_div, status_txt

    # ════════════════════════════════════════════════════════════
    # Callback 4 – THE SINGLE FIGURE OWNER (Bug 1, 2, 3 fix)
    #
    # Uses Patch() so zoom/pan state is never reset.
    # All shape types are rebuilt together to avoid last-writer-wins
    # conflicts between LL shapes and candidate shapes.
    # ════════════════════════════════════════════════════════════
    @callback(
        Output("spectrum-graph", "figure"),
        Input("candidate-range", "value"),
        Input("ll-entries-store", "data"),
        Input("pending-changes-store", "data"),
    )
    def update_figure_shapes(candidate_range, ll_entries_data, pending_changes):
        """
        Patch ONLY the shapes layer of the figure.
        Never rebuilds traces or layout — preserves zoom, pan, and trace state.
        """
        shapes = _build_ll_shapes(ll_entries_data, pending_changes)

        if candidate_range and len(candidate_range) == 2:
            lo, hi = clamp(candidate_range[0], candidate_range[1], min_w, max_w)
            shapes += _cand_shapes(lo, hi)

        fig_patch = Patch()
        fig_patch["layout"]["shapes"] = shapes
        return fig_patch

    # ════════════════════════════════════════════════════════════
    # Callback 5 – zoom hint reflected to source hint
    # ════════════════════════════════════════════════════════════
    @callback(
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
            f"Zoom detected  {lo:.3f} – {hi:.3f} nm  ·  click ⊕ Use Zoom to apply",
            "src-hint zoom",
        )