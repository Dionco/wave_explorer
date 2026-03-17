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

def _ll_shapes(ll_entries: List[dict]) -> List[dict]:
    """
    Return rectangular region spans for fitted line-list regions.
    
    Note: Draggable handles are now rendered as SVG overlays in JavaScript,
    not as Plotly shapes. This function only returns the background rectangles.
    """
    shapes = []
    for e in ll_entries:
        # Row 1 — fitted spectrum backgroundrect
        shapes.append(dict(
            type="rect", xref="x", yref="y domain",
            x0=e["lower"], x1=e["upper"],
            y0=0, y1=1,
            fillcolor=C["ll_fill"],
            line=dict(color=C["ll_line"], width=0.8),
            layer="below",
            editable=False,
        ))
        # Row 2 — residual background rect
        shapes.append(dict(
            type="rect", xref="x", yref="y2 domain",
            x0=e["lower"], x1=e["upper"],
            y0=0, y1=1,
            fillcolor=C["ll_fill"],
            line=dict(color=C["ll_line"], width=0.8),
            layer="below",
            editable=False,
        ))

    return shapes


def _cand_shapes(lo: float, hi: float) -> List[dict]:
    """Return candidate region spans (amber highlight)."""
    return [
        dict(
            type="rect", xref="x", yref="y domain",
            x0=lo, x1=hi, y0=0, y1=1,
            fillcolor=C["cand_fill"],
            line=dict(color=C["cand_line"], width=1.8),
            layer="below",
        ),
        dict(
            type="rect", xref="x", yref="y2 domain",
            x0=lo, x1=hi, y0=0, y1=1,
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
    """
    Add transparent polygon overlay traces for hover interaction.
    
    Each trace corresponds to a fitted region. Hover over it triggers the tooltip.
    The customdata embeds region_idx for client-side identification.
    """
    for rs in ll_hover_stats:
        lo = rs["lower"]
        hi = rs["upper"]
        
        # Build hover text (shown when you hover directly on region)
        hover_text = (
            f"<b>Region #{rs['region_idx']}</b><br>"
            f"λ {lo:.3f} – {hi:.3f} nm<br>"
            f"χ²/N (med): {_fmt(rs['med_chi2'], '.3f')}<br>"
            f"Mean residual: {_fmt(rs['mean_resid'], '+.4f')}<br>"
            f"Stars: {rs['n_stars']}  ·  Median pix: {rs['med_npix']}"
        )
        
        # Keep region index 1-based to match ll-stats-store entries used by tooltip.js.
        ridx = int(rs["region_idx"])
        fillcol = "rgba(255,80,80,0.16)" if debug_hover else "rgba(62,173,90,0.06)"
        linecol = "rgba(255,120,120,0.55)" if debug_hover else "rgba(62,173,90,0.22)"
        
        fig.add_trace(go.Scatter(
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
        ), row=1, col=1)


# ══════════════════════════════════════════════════════════════════════════════
# Main figure builder
# ══════════════════════════════════════════════════════════════════════════════

def build_base_figure(
    dataset: dict,
    ll_entries_override: Optional[List[dict]] = None,
    debug_hover: bool = False,
) -> go.Figure:
    """
    Build the multi-row spectrum figure with line-list regions.
    
    This figure is built once at app startup and reused. Callbacks only patch shapes.
    """
    ll_entries = ll_entries_override if ll_entries_override is not None else dataset["ll_entries"]
    ll_hover_stats = [dict(r) for r in dataset["ll_hover_stats"]]
    
    # Update hover stats to reflect any LL entry overrides (e.g. from drag updates)
    for i, e in enumerate(ll_entries):
        if i >= len(ll_hover_stats):
            break
        ll_hover_stats[i]["lower"] = float(e["lower"])
        ll_hover_stats[i]["upper"] = float(e["upper"])
        ll_hover_stats[i]["center"] = 0.5 * (float(e["lower"]) + float(e["upper"]))

    w         = dataset["common_w"]
    mean_obs_s = dataset["mean_obs_s"]
    mean_fit_s = dataset["mean_fit_s"]
    mean_obs   = dataset["mean_obs"]
    mean_fit   = dataset["mean_fit"]
    std_obs   = dataset["std_obs"]
    std_fit   = dataset["std_fit"]
    mean_resid_s = dataset["mean_resid_s"]
    mean_resid   = dataset["mean_resid"]
    std_resid   = dataset["std_resid"]
    n           = dataset["n_stars"]
    suffix      = dataset["suffix"]

    fig = make_subplots(
        rows=2, cols=1,
        shared_xaxes=True,
        vertical_spacing=0.045,
        row_heights=[0.70, 0.30],
    )

    # ── Row 1 : observed + fit ──────────────────────────────────
    # ± 1σ bands (behind)
    fig.add_trace(go.Scatter(
        x=w, y=mean_obs + std_obs,
        mode="lines", line=dict(width=0), showlegend=False, hoverinfo="skip",
    ), row=1, col=1)
    fig.add_trace(go.Scatter(
        x=w, y=mean_obs - std_obs,
        mode="lines", line=dict(width=0), fill="tonexty",
        fillcolor="rgba(208,218,231,0.10)", showlegend=False, hoverinfo="skip",
    ), row=1, col=1)

    fig.add_trace(go.Scatter(
        x=w, y=mean_fit + std_fit,
        mode="lines", line=dict(width=0), showlegend=False, hoverinfo="skip",
    ), row=1, col=1)
    fig.add_trace(go.Scatter(
        x=w, y=mean_fit - std_fit,
        mode="lines", line=dict(width=0), fill="tonexty",
        fillcolor="rgba(88,209,235,0.10)", showlegend=False, hoverinfo="skip",
    ), row=1, col=1)

    # main lines (front)
    fig.add_trace(go.Scatter(
        x=w, y=mean_obs_s, mode="lines", name=f"Mean observed (n={n})",
        line=dict(color=C["obs"], width=1.2),
        hoverinfo="skip",
    ), row=1, col=1)
    fig.add_trace(go.Scatter(
        x=w, y=mean_fit_s, mode="lines", name="Mean model fit",
        line=dict(color=C["fit"], width=1.2),
        hoverinfo="skip",
    ), row=1, col=1)

    # ── Row 2 : residual ────────────────────────────────────────
    fig.add_trace(go.Scatter(
        x=w, y=mean_resid + std_resid,
        mode="lines", line=dict(width=0), showlegend=False, hoverinfo="skip",
    ), row=2, col=1)
    fig.add_trace(go.Scatter(
        x=w, y=mean_resid - std_resid,
        mode="lines", line=dict(width=0), fill="tonexty",
        fillcolor="rgba(255,167,38,0.10)", showlegend=False, hoverinfo="skip",
    ), row=2, col=1)
    fig.add_trace(go.Scatter(
        x=w, y=mean_resid_s, mode="lines", name="Mean residual",
        line=dict(color=C["resid"], width=1.1),
        hoverinfo="skip",
    ), row=2, col=1)

    fig.add_hline(y=0, line_dash="dot", line_width=1,
                  line_color="rgba(120,130,150,0.40)", row=2, col=1)

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
            orientation="h", yanchor="bottom", y=1.01, xanchor="left", x=0,
            bgcolor="rgba(0,0,0,0)", font=dict(size=12),
        ),
        dragmode="zoom",
        hovermode="closest",
        hoverdistance=20,
        uirevision="asap-main",
        hoverlabel=dict(
            bgcolor=C["surf2"], bordercolor=C["border"],
            font=dict(family=MONO, size=11, color=C["text"]),
        ),
        shapes=_ll_shapes(ll_entries),
        annotations=[
            dict(
                text=(
                    f"<b>{suffix}</b>  ·  {n} stars  "
                    f"·  λ {dataset['common_w'][0]:.1f}–{dataset['common_w'][-1]:.1f} nm"
                ),
                xref="paper", yref="paper", x=0.5, y=1.035,
                showarrow=False, font=dict(size=12, color=C["muted"]),
                xanchor="center",
            ),
            dict(
                text="HOVER DEBUG ON" if debug_hover else "",
                xref="paper", yref="paper", x=1.0, y=1.035,
                showarrow=False,
                font=dict(size=10, color=C["amber"]),
                xanchor="right",
            ),
        ],
    )

    for row, ax, title in [
        (1, "yaxis",  "Norm. flux"),
        (2, "yaxis2", "Residual"),
    ]:
        fig.update_layout(**{
            ax: dict(
                title_text=title, title_font=dict(size=11),
                gridcolor="#1c2333", gridwidth=1,
                zerolinecolor="#1c2333",
                tickfont=dict(size=10),
            )
        })

    fig.update_xaxes(
        title_text="Wavelength (nm)", title_font=dict(size=11),
        gridcolor="#1c2333", gridwidth=1,
        tickfont=dict(size=10),
        fixedrange=False, matches="x",
        row=2, col=1,
    )
    fig.update_xaxes(
        gridcolor="#1c2333", fixedrange=False,
        row=1, col=1,
    )
    fig.update_xaxes(rangeslider=dict(visible=True, bgcolor="#0d1117", thickness=0.04),
                     row=2, col=1)

    return fig
