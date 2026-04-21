"""
ASAP Figure & Shape Building
"""

from typing import List, Optional

import numpy as np
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from .theme import C, MONO, _fmt


# ══════════════════════════════════════════════════════════════════════════════
# Shape builders for line-list regions and candidates
# ══════════════════════════════════════════════════════════════════════════════

# Canonical colours — shared with candidate.py's _build_ll_shapes via import
# of the constants from candidate.py, or duplicated here with the same values.
# Using the theme dict keeps them in sync.
_LL_FILL = C["ll_fill"]
_LL_LINE = C["ll_line"]


_ADDED_FILL = "rgba(88, 209, 235, 0.20)"
_ADDED_LINE = "rgba(88, 209, 235, 0.95)"
_EXCLUDED_FILL = "rgba(248, 81, 73, 0.06)"
_EXCLUDED_LINE = "rgba(248, 81, 73, 0.40)"


def _shape_style(entry: dict):
    if entry.get("excluded", False):
        return _EXCLUDED_FILL, _EXCLUDED_LINE
    if entry.get("added", False):
        return _ADDED_FILL, _ADDED_LINE
    return _LL_FILL, _LL_LINE


def _ll_shapes(ll_entries: List[dict]) -> List[dict]:
    """Return rectangular region spans for fitted line-list regions.

    Colors follow the session state of each entry:
      - green   — saved / baseline
      - cyan    — added in this session (saved)
      - red-faint — excluded (kept for context)

    Draggable handles are rendered as SVG overlays in JavaScript, not as
    Plotly shapes. This function only returns the background rectangles.
    """
    shapes: List[dict] = []
    for e in ll_entries:
        fill, line = _shape_style(e)
        for yref in ("y domain", "y2 domain"):
            shapes.append(
                dict(
                    type="rect",
                    xref="x",
                    yref=yref,
                    x0=e["lower"],
                    x1=e["upper"],
                    y0=0,
                    y1=1,
                    fillcolor=fill,
                    line=dict(color=line, width=0.8),
                    layer="below",
                    editable=False,
                )
            )

    # [H3 FIX] Residual reference lines as shapes — keeps them in sync
    # with the Patch path in candidate.py which also appends them.
    # Solid y=0 baseline plus dotted guides at +/-0.05.
    shapes.append(
        dict(
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
    )
    shapes.append(
        dict(
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
    )
    shapes.append(
        dict(
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
    )

    return shapes


def _cand_shapes(lo: float, hi: float) -> List[dict]:
    """Return candidate region spans (amber highlight)."""
    return [
        dict(
            type="rect",
            xref="x",
            yref="y domain",
            x0=lo,
            x1=hi,
            y0=0,
            y1=1,
            fillcolor=C["cand_fill"],
            line=dict(color=C["cand_line"], width=1.8),
            layer="below",
        ),
        dict(
            type="rect",
            xref="x",
            yref="y2 domain",
            x0=lo,
            x1=hi,
            y0=0,
            y1=1,
            fillcolor="rgba(255,167,38,0.13)",
            line=dict(color=C["cand_line"], width=1.2),
            layer="below",
        ),
    ]


# ══════════════════════════════════════════════════════════════════════════════
# Hover overlay traces
# ══════════════════════════════════════════════════════════════════════════════


def _add_region_hover_overlays(
    fig: go.Figure,
    ll_hover_stats: List[dict],
    y_min: float,
    y_max: float,
    debug_hover: bool = False,
) -> None:
    """Add hover overlay traces for region interaction.

    One trace per region — this is required for correct hit-testing.
    Plotly's hoveron="fills" with None-separated polygons in a single trace
    always returns data from the first polygon, making region identification
    impossible. Per-region traces are the only reliable approach.
    """
    # Overlay traces are transparent in normal use: they exist purely as
    # hover hit targets (per-region tooltip with chi2/etc). The visible
    # region appearance comes from layout.shapes (which Patch updates on
    # drag/save). Coloring the overlay would leave a stale ghost rectangle
    # at the pre-drag position because traces don't move with shapes.
    fillcol = "rgba(255,80,80,0.16)" if debug_hover else "rgba(0,0,0,0)"
    linecol = "rgba(255,120,120,0.55)" if debug_hover else "rgba(0,0,0,0)"

    for rs in ll_hover_stats:
        lo = rs["lower"]
        hi = rs["upper"]
        ridx = int(rs["region_idx"])

        hover_text = (
            f"<b>Region #{ridx}</b><br>"
            f"\u03bb {lo:.3f} \u2013 {hi:.3f} nm<br>"
            f"\u03c7\u00b2/N (med): {_fmt(rs['med_chi2'], '.3f')}<br>"
            f"Mean residual: {_fmt(rs['mean_resid'], '+.4f')}<br>"
            f"Stars: {rs['n_stars']}  \u00b7  Median pix: {rs['med_npix']}"
        )

        fig.add_trace(
            go.Scatter(
                x=[lo, hi, hi, lo, lo],
                y=[y_min, y_min, y_max, y_max, y_min],
                mode="lines",
                line=dict(width=0.5, color=linecol),
                fill="toself",
                fillcolor=fillcol,
                hoveron="fills",
                customdata=[ridx, ridx, ridx, ridx, ridx],
                hovertemplate=hover_text + "<extra></extra>",
                showlegend=False,
                name="",
            ),
            row=1,
            col=1,
        )


# ══════════════════════════════════════════════════════════════════════════════
# Main figure builder
# ══════════════════════════════════════════════════════════════════════════════


def build_base_figure(
    dataset: dict,
    ll_entries_override: Optional[List[dict]] = None,
    debug_hover: bool = False,
    initial_candidate: Optional[tuple] = None,
) -> go.Figure:
    """Build the multi-row spectrum figure with line-list regions.

    This figure is built once at app startup and rebuilt on save/discard.
    Callbacks patch shapes for intermediate updates.
    """
    ll_entries = (
        ll_entries_override
        if ll_entries_override is not None
        else dataset["ll_entries"]
    )
    ll_hover_stats = [dict(r) for r in dataset["ll_hover_stats"]]

    # Update hover stats to reflect any LL entry overrides.
    for i, e in enumerate(ll_entries):
        if i >= len(ll_hover_stats):
            # [M4-figbuild FIX] Append a stub for new entries instead of breaking.
            ll_hover_stats.append(
                dict(
                    region_idx=i + 1,
                    lower=float(e["lower"]),
                    upper=float(e["upper"]),
                    center=0.5 * (float(e["lower"]) + float(e["upper"])),
                    element=str(e.get("element", "Unknown")),
                    ion=str(e.get("ion", "1")),
                    med_chi2=np.nan,
                    n_stars=0,
                    med_npix=0,
                    mean_resid=np.nan,
                    mean_abs_resid=np.nan,
                    p95_abs_resid=np.nan,
                    mean_norm_resid=np.nan,
                )
            )
        else:
            ll_hover_stats[i]["lower"] = float(e["lower"])
            ll_hover_stats[i]["upper"] = float(e["upper"])
            ll_hover_stats[i]["center"] = 0.5 * (float(e["lower"]) + float(e["upper"]))

    w = dataset["common_w"]
    mean_obs_s = dataset["mean_obs_s"]
    mean_fit_s = dataset["mean_fit_s"]
    mean_obs = dataset["mean_obs"]
    mean_fit = dataset["mean_fit"]
    std_obs = dataset["std_obs"]
    std_fit = dataset["std_fit"]
    mean_resid_s = dataset["mean_resid_s"]
    mean_resid = dataset["mean_resid"]
    std_resid = dataset["std_resid"]
    n = dataset["n_stars"]
    suffix = dataset["suffix"]

    fig = make_subplots(
        rows=2,
        cols=1,
        shared_xaxes=True,
        vertical_spacing=0.045,
        row_heights=[0.70, 0.30],
    )

    # ── Row 1 : observed + fit ──────────────────────────────────
    # +/- 1 sigma bands (behind)
    fig.add_trace(
        go.Scatter(
            x=w,
            y=mean_obs + std_obs,
            mode="lines",
            line=dict(width=0),
            showlegend=False,
            hoverinfo="skip",
        ),
        row=1,
        col=1,
    )
    fig.add_trace(
        go.Scatter(
            x=w,
            y=mean_obs - std_obs,
            mode="lines",
            line=dict(width=0),
            fill="tonexty",
            fillcolor="rgba(208,218,231,0.10)",
            showlegend=False,
            hoverinfo="skip",
        ),
        row=1,
        col=1,
    )

    fig.add_trace(
        go.Scatter(
            x=w,
            y=mean_fit + std_fit,
            mode="lines",
            line=dict(width=0),
            showlegend=False,
            hoverinfo="skip",
        ),
        row=1,
        col=1,
    )
    fig.add_trace(
        go.Scatter(
            x=w,
            y=mean_fit - std_fit,
            mode="lines",
            line=dict(width=0),
            fill="tonexty",
            fillcolor="rgba(88,209,235,0.10)",
            showlegend=False,
            hoverinfo="skip",
        ),
        row=1,
        col=1,
    )

    # Main lines (front)
    fig.add_trace(
        go.Scatter(
            x=w,
            y=mean_obs_s,
            mode="lines",
            name=f"Mean observed (n={n})",
            line=dict(color=C["obs"], width=1.2),
            hoverinfo="skip",
        ),
        row=1,
        col=1,
    )
    fig.add_trace(
        go.Scatter(
            x=w,
            y=mean_fit_s,
            mode="lines",
            name="Mean model fit",
            line=dict(color=C["fit"], width=1.2),
            hoverinfo="skip",
        ),
        row=1,
        col=1,
    )

    # ── Row 2 : residual ────────────────────────────────────────
    fig.add_trace(
        go.Scatter(
            x=w,
            y=mean_resid + std_resid,
            mode="lines",
            line=dict(width=0),
            showlegend=False,
            hoverinfo="skip",
        ),
        row=2,
        col=1,
    )
    fig.add_trace(
        go.Scatter(
            x=w,
            y=mean_resid - std_resid,
            mode="lines",
            line=dict(width=0),
            fill="tonexty",
            fillcolor="rgba(255,167,38,0.10)",
            showlegend=False,
            hoverinfo="skip",
        ),
        row=2,
        col=1,
    )
    fig.add_trace(
        go.Scatter(
            x=w,
            y=mean_resid_s,
            mode="lines",
            name="Mean residual",
            line=dict(color=C["resid"], width=1.1),
            hoverinfo="skip",
        ),
        row=2,
        col=1,
    )

    # [H3 FIX] The y=0 reference hline is now part of _ll_shapes()
    # (and _build_ll_shapes in candidate.py) so it survives Patch updates.
    # No separate add_hline() call needed.

    y1_min = float(np.nanmin([mean_obs - std_obs, mean_fit - std_fit]))
    y1_max = float(np.nanmax([mean_obs + std_obs, mean_fit + std_fit]))
    y1_pad = max(1e-6, 0.02 * (y1_max - y1_min))
    _add_region_hover_overlays(
        fig,
        ll_hover_stats,
        y1_min - y1_pad,
        y1_max + y1_pad,
        debug_hover=debug_hover,
    )

    # ── Base layout ────────────────────────────────────────────
    fig.update_layout(
        template="plotly_dark",
        paper_bgcolor=C["surf"],
        plot_bgcolor="#0d1117",
        height=820,
        font=dict(family=MONO, color=C["muted"], size=11),
        margin=dict(l=62, r=24, t=40, b=50),
        legend=dict(
            orientation="h",
            yanchor="bottom",
            y=1.01,
            xanchor="left",
            x=0,
            bgcolor="rgba(0,0,0,0)",
            font=dict(size=12),
        ),
        dragmode="zoom",
        hovermode="closest",
        hoverdistance=20,
        uirevision="asap-main",
        hoverlabel=dict(
            bgcolor=C["surf2"],
            bordercolor=C["border"],
            font=dict(family=MONO, size=11, color=C["text"]),
        ),
        shapes=(
            _ll_shapes(ll_entries)
            + (
                _cand_shapes(
                    float(initial_candidate[0]), float(initial_candidate[1])
                )
                if initial_candidate
                else []
            )
        ),
        annotations=[
            dict(
                text=(
                    f"<b>{suffix}</b>  \u00b7  {n} stars  "
                    f"\u00b7  \u03bb {dataset['common_w'][0]:.1f}"
                    f"\u2013{dataset['common_w'][-1]:.1f} nm"
                ),
                xref="paper",
                yref="paper",
                x=0.5,
                y=1.035,
                showarrow=False,
                font=dict(size=12, color=C["muted"]),
                xanchor="center",
            ),
            dict(
                text="HOVER DEBUG ON" if debug_hover else "",
                xref="paper",
                yref="paper",
                x=1.0,
                y=1.035,
                showarrow=False,
                font=dict(size=10, color=C["amber"]),
                xanchor="right",
            ),
        ],
    )

    fig.update_layout(
        yaxis=dict(
            title_text="Norm. flux",
            title_font=dict(size=11),
            gridcolor="#1c2333",
            gridwidth=1,
            zerolinecolor="#1c2333",
            tickfont=dict(size=10),
        ),
        yaxis2=dict(
            title_text="Residual",
            title_font=dict(size=11),
            gridcolor="#1c2333",
            gridwidth=1,
            zerolinecolor="#1c2333",
            tickfont=dict(size=10),
            range=[-0.2, 0.2],
            autorange=False,
        ),
    )

    fig.update_xaxes(
        title_text="Wavelength (nm)",
        title_font=dict(size=11),
        gridcolor="#1c2333",
        gridwidth=1,
        tickfont=dict(size=10),
        fixedrange=False,
        matches="x",
        row=2,
        col=1,
    )
    fig.update_xaxes(
        gridcolor="#1c2333",
        fixedrange=False,
        row=1,
        col=1,
    )
    return fig
