"""
Candidate Region Callbacks

Single owner of Output("spectrum-graph", "figure").
Uses @app.callback (instance-scoped) throughout to prevent duplicate
registration on Dash hot-reload.
"""

from typing import Tuple

import numpy as np
from dash import ALL, Input, Output, State, no_update
from dash import ctx as dash_ctx
from dash import html

from ..data_processing import compute_custom_region_chi2, compute_residual_metrics
from ..layout import build_histogram, region_chi2_values, render_stats
from ..theme import C, MONO


# ══════════════════════════════════════════════════════════════════════════════
# Helpers
# ══════════════════════════════════════════════════════════════════════════════


def clamp(lo: float, hi: float, mn: float, mx: float) -> Tuple[float, float]:
    lo = max(mn, min(mx, float(lo)))
    hi = max(mn, min(mx, float(hi)))
    return (lo, hi) if lo <= hi else (hi, lo)


# ══════════════════════════════════════════════════════════════════════════════
# Callback registration
# ══════════════════════════════════════════════════════════════════════════════


def register_candidate_callbacks(app, dataset, min_w, max_w):
    """Register all candidate region callbacks."""

    # Default histogram — median χ²/N across every fitted region. The
    # summary is immutable after registration, so build it once here and
    # reuse it instead of rebuilding on every update_stats trigger.
    default_vals = region_chi2_values(dataset["region_summary"])
    default_hist = build_histogram(
        default_vals, f"{len(default_vals)} fitted regions"
    )

    # ════════════════════════════════════════════════════════════
    # Callback 1 – nav-btn click selects the region AND frames it
    #
    # A nav click writes selected-region-store (live stats + selected-
    # region header) and goto-region-store. spectrum.js watches the
    # goto-region-store `tick` and moves/zooms the graph view to frame
    # the picked region. `tick` is strictly monotonic (previous tick + 1):
    # summing n_clicks would go DOWN whenever refresh_table rebuilds the
    # nav buttons with n_clicks=0, making spectrum.js's tick dedup drop
    # navigations. Incrementing also means re-clicking the same row still
    # registers as a fresh change.
    # ════════════════════════════════════════════════════════════
    @app.callback(
        Output("selected-region-store", "data", allow_duplicate=True),
        Output("goto-region-store", "data"),
        Input({"type": "nav-btn", "index": ALL}, "n_clicks"),
        State("goto-region-store", "data"),
        prevent_initial_call=True,
    )
    def nav_to_region(nav_clicks, goto_prev):
        if not any(nav_clicks or []):
            return no_update, no_update
        tid = dash_ctx.triggered_id
        if not isinstance(tid, dict) or tid.get("type") != "nav-btn":
            return no_update, no_update
        idx = tid.get("index")
        if idx is None:
            return no_update, no_update
        try:
            prev_tick = int((goto_prev or {}).get("tick") or 0)
        except (TypeError, ValueError):
            prev_tick = 0
        return (
            {"region_idx": int(idx)},
            {"region_idx": int(idx), "tick": prev_tick + 1},
        )


    # ════════════════════════════════════════════════════════════
    # Callback 2 – live stats (no figure output)
    #
    # Driven by the region clicked in the main figure
    # (selected-region-store, populated by the clientside clickData
    # handler in app.py, or by the table nav-btn via Callback 1).
    # Bounds follow pending edits so stats track drags before save.
    # ════════════════════════════════════════════════════════════
    @app.callback(
        Output("candidate-stats", "children"),
        Output("status-range", "children"),
        Output("chi2-histogram", "children"),
        Input("selected-region-store", "data"),
        Input("ll-entries-store", "data"),
        Input("pending-changes-store", "data"),
    )
    def update_stats(selected_region, ll_entries_data, pending_changes):
        # default_hist (precomputed above) is shown whenever no eligible
        # region is selected.
        lo = hi = idx = None
        if selected_region and ll_entries_data:
            ridx = selected_region.get("region_idx")
            if ridx is not None and 0 <= ridx < len(ll_entries_data):
                idx = ridx
                base = ll_entries_data[ridx]
                staged = (pending_changes or {}).get(str(ridx))
                live = staged if isinstance(staged, dict) else base
                lo = float(live["lower"])
                hi = float(live["upper"])

        if lo is None or hi is None:
            return (
                "Click a region in the spectrum to see statistics.",
                "",
                default_hist,
            )

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
            # Region not eligible (no fitted pixels) \u2014 keep the default view.
            return (
                stats_div,
                f"{lo:.3f} \u2013 {hi:.3f} nm  \u00b7  no fitted pixels",
                default_hist,
            )

        # Eligible region \u2014 show the per-star \u03c7\u00b2/N distribution for it.
        region_hist = build_histogram(
            chi2.get("per_star_chi2", []),
            f"Region #{idx + 1}  \u00b7  {chi2['n_stars']} stars",
            unit="star",
        )
        return (
            render_stats(chi2, resid, lo, hi),
            (
                f"{lo:.3f} \u2013 {hi:.3f} nm"
                f"  \u00b7  \u03c7\u00b2/N = {chi2['median_chi2']:.3f}"
            ),
            region_hist,
        )

