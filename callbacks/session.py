"""
Session Management Callbacks (Add, Clear, Export)
"""

import numpy as np
from dash import Input, Output, State, callback, ctx, dcc, no_update

from ..data_processing import compute_custom_region_chi2


def register_session_callbacks(app, dataset):
    """Register session management callbacks."""

    # ════════════════════════════════════════════════════════════
    # Callback – add/clear session entries
    # ════════════════════════════════════════════════════════════
    @callback(
        Output("session-store", "data"),
        Input("add-session-btn", "n_clicks"),
        Input("clear-session-btn", "n_clicks"),
        State("candidate-range", "value"),
        State("session-store", "data"),
        prevent_initial_call=True,
    )
    def manage_session(add_clicks, clear_clicks, cand_range, session_data):
        tid = ctx.triggered_id
        if tid == "clear-session-btn":
            return []
        if tid == "add-session-btn" and cand_range and len(cand_range) == 2:
            lo, hi = float(cand_range[0]), float(cand_range[1])
            chi2 = compute_custom_region_chi2(dataset["fit_data_cache"], lo, hi)
            entry = dict(
                lo=round(lo, 4), hi=round(hi, 4),
                width=round(hi - lo, 4),
                chi2=round(chi2["median_chi2"], 3) if np.isfinite(chi2["median_chi2"]) else None,
                n_stars=chi2["n_stars"],
                label="",
            )
            # Avoid exact duplicates
            existing = {(r["lo"], r["hi"]) for r in session_data}
            if (entry["lo"], entry["hi"]) not in existing:
                return session_data + [entry]
        return no_update

    # ════════════════════════════════════════════════════════════
    # Callback – render session log
    # ════════════════════════════════════════════════════════════
    @callback(
        Output("session-log", "children"),
        Input("session-store", "data"),
    )
    def render_session(session_data):
        from dash import html
        from ..theme import C, chi2_color
        
        if not session_data:
            return [html.Div("No candidates added yet.", className="log-empty")]
        items = []
        for i, r in enumerate(session_data):
            c2val = r.get("chi2")
            c2str = f"{c2val:.3f}" if c2val is not None else "—"
            c2col = chi2_color(c2val if c2val is not None else np.nan)
            items.append(html.Div(className="log-item", children=[
                html.Span(f"{i+1:02d}", style={"color": C["dim"], "width": "20px",
                                                "flexShrink": "0"}),
                html.Span(f"{r['lo']:.3f} – {r['hi']:.3f} nm", className="log-range"),
                html.Span(f"Δ{r['width']:.3f}", className="log-elem"),
                html.Span(f"χ² {c2str}", className="log-chi",
                          style={"color": c2col}),
                html.Span(f"{r['n_stars']} ★",
                          style={"color": C["dim"], "fontSize": "10px"}),
            ]))
        return items

    # ════════════════════════════════════════════════════════════
    # Callback – export session as line-list file
    # ════════════════════════════════════════════════════════════
    @callback(
        Output("download-session", "data"),
        Input("export-btn", "n_clicks"),
        State("session-store", "data"),
        prevent_initial_call=True,
    )
    def export_session(n_clicks, session_data):
        if not session_data:
            return no_update
        lines = [
            f"# ASAP line curation session export — suffix: {dataset['suffix']}",
            f"# {len(session_data)} candidate region(s)",
            "# center    lower    upper    chi2_med  n_stars",
        ]
        for r in session_data:
            cen = round((r["lo"] + r["hi"]) / 2, 4)
            c2s = f"{r['chi2']:.3f}" if r.get("chi2") is not None else "nan"
            lines.append(
                f"{cen:<10.4f} {r['lo']:<10.4f} {r['hi']:<10.4f}"
                f" {c2s:<10}  {r['n_stars']}"
            )
        content = "\n".join(lines) + "\n"
        return dcc.send_string(content, filename=f"candidates_{dataset['suffix']}.txt")
