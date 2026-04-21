"""
ASAP Layout & UI Component Builders
"""

from pathlib import Path
from typing import List

import numpy as np
from dash import dcc, html

from .theme import C, MONO, _fmt, chi2_color, chi2_label, chi2_pct


# ══════════════════════════════════════════════════════════════════════════════
# Initial candidate range
# ══════════════════════════════════════════════════════════════════════════════


def initial_candidate_range(
    dataset: dict, min_w: float, max_w: float
) -> tuple:
    """Pick a sensible initial candidate range.

    Strategy: prefer the first non-excluded line-list region with finite
    chi2 stats, so the user lands on something meaningful instead of the
    left edge (which often has no fitted pixels).

    Falls back to the first line-list region, then to a 1 nm window at
    the left of the spectrum.
    """
    for rs in dataset.get("ll_hover_stats", []):
        c2 = rs.get("med_chi2")
        if c2 is None:
            continue
        try:
            c2f = float(c2)
        except (TypeError, ValueError):
            continue
        if c2f == c2f:  # NaN check
            lo = max(min_w, min(max_w, float(rs["lower"])))
            hi = max(min_w, min(max_w, float(rs["upper"])))
            if hi > lo:
                return lo, hi

    for e in dataset.get("ll_entries", []):
        lo = max(min_w, min(max_w, float(e["lower"])))
        hi = max(min_w, min(max_w, float(e["upper"])))
        if hi > lo and not e.get("excluded", False):
            return lo, hi

    return min_w, min(min_w + 1.0, max_w)


# ══════════════════════════════════════════════════════════════════════════════
# Header
# ══════════════════════════════════════════════════════════════════════════════


def build_header(dataset: dict) -> html.Div:
    w = dataset["common_w"]
    return html.Div(
        className="asap-header",
        children=[
            html.Div(
                className="asap-wordmark",
                children=[
                    "ASAP",
                    html.Span("  /  ", className="wm-sep"),
                    html.Span("Line Curation", className="wm-sub"),
                ],
            ),
            html.Div(
                className="h-chip c-cyan",
                children=["suffix ", html.Span(dataset["suffix"], className="hc-val")],
            ),
            html.Div(
                className="h-chip c-green",
                children=[
                    "stars ",
                    html.Span(str(dataset["n_stars"]), className="hc-val"),
                ],
            ),
            html.Div(
                className="h-chip",
                children=[
                    "λ ",
                    html.Span(f"{w[0]:.1f} – {w[-1]:.1f} nm", className="hc-val"),
                ],
            ),
            html.Div(
                className="h-chip",
                children=[
                    "ll regions ",
                    html.Span(str(len(dataset["ll_entries"])), className="hc-val"),
                ],
            ),
            html.Div(className="h-spacer"),
            html.Button(
                "\u270e Draw Region",
                id="draw-mode-toggle",
                n_clicks=0,
                className="btn btn-sm btn-amber",
                style={"marginRight": "8px"},
            ),
            # ── Selected-region chip + per-region action buttons ──────────────
            html.Div(
                id="selected-region-container",
                className="selected-region-container",
                style={"display": "none"},
                children=[
                    html.Span(
                        className="h-chip c-cyan",
                        children=[
                            "◉ ",
                            html.Span(
                                id="selected-region-label", className="hc-val"
                            ),
                        ],
                    ),
                    html.Button(
                        "\u2a2f Exclude",
                        id="selected-exclude-btn",
                        n_clicks=0,
                        className="btn btn-sm btn-danger",
                        style={"display": "none"},
                        title="Exclude the selected region from the saved line list",
                    ),
                    html.Button(
                        "\u21ba Restore",
                        id="selected-restore-btn",
                        n_clicks=0,
                        className="btn btn-sm btn-green",
                        style={"display": "none"},
                        title="Include the selected region in the saved line list",
                    ),
                    html.Button(
                        "✕ Delete",
                        id="selected-delete-btn",
                        n_clicks=0,
                        className="btn btn-sm btn-danger",
                        style={"display": "none"},
                        title="Permanently remove this unsaved added region",
                    ),
                    html.Button(
                        "Deselect",
                        id="selected-clear-btn",
                        n_clicks=0,
                        className="btn btn-sm",
                        title="Clear region selection",
                    ),
                ],
            ),
            html.Div(
                id="pending-status-container",
                className="pending-status-container",
                style={"display": "none"},
                children=[
                    html.Span(
                        id="pending-badge",
                        className="h-chip c-amber",
                        children=[
                            "⚠ ",
                            html.Span(id="pending-count", children="0"),
                            " pending",
                        ],
                    ),
                    html.Button(
                        "\u21b6 Undo",
                        id="undo-btn",
                        n_clicks=0,
                        className="btn btn-sm btn-amber",
                        title="Revert the most recent change",
                        disabled=True,
                    ),
                    html.Button(
                        "\u2b73 Save Curated File",
                        id="save-changes-btn",
                        n_clicks=0,
                        className="btn btn-sm btn-green",
                    ),
                    html.Button(
                        "✕ Discard all changes",
                        id="discard-changes-btn",
                        n_clicks=0,
                        className="btn btn-sm btn-danger",
                        title="Drop every unsaved change and remove unsaved drawn regions",
                    ),
                ],
            ),
            html.Div(
                className="h-chip",
                style={
                    "maxWidth": "340px",
                    "overflow": "hidden",
                    "textOverflow": "ellipsis",
                },
                children=[
                    "source ",
                    html.Span(
                        Path(dataset["line_list"]).name, className="hc-val"
                    ),
                ],
            ),
            html.Div(
                id="last-saved-chip",
                className="h-chip c-green",
                style={"display": "none"},
                children=[
                    "\u2714 saved ",
                    html.Span(id="last-saved-name", className="hc-val"),
                ],
            ),
        ],
    )


# ══════════════════════════════════════════════════════════════════════════════
# Candidate Region Panel
# ══════════════════════════════════════════════════════════════════════════════


def build_candidate_panel(
    min_w: float, max_w: float, init_lo: float, init_hi: float
) -> html.Div:
    return html.Div(
        className="card",
        children=[
            html.Div("Candidate Region", className="card-title"),
            html.Div(
                className="btn-row",
                children=[
                    html.Button(
                        "⊕  Use Zoom",
                        id="use-zoom-btn",
                        n_clicks=0,
                        className="btn btn-cyan",
                    ),
                    html.Button(
                        "→  Apply Manual",
                        id="apply-manual-btn",
                        n_clicks=0,
                        className="btn btn-amber",
                    ),
                    html.Button(
                        "＋  Add to Session",
                        id="add-session-btn",
                        n_clicks=0,
                        className="btn btn-green",
                    ),
                ],
            ),
            html.Div(
                [
                    html.Div(
                        "Wavelength Range (nm)",
                        className="form-label",
                        style={"marginBottom": "12px"},
                    ),
                    dcc.RangeSlider(
                        id="candidate-range",
                        min=min_w,
                        max=max_w,
                        value=[init_lo, init_hi],
                        # step=0.001 over a ~600 nm range = 600,000 discrete positions,
                        # which causes React's Range component to blow the call stack.
                        # Use step=0.1 here; manual inputs below still give 0.001 precision.
                        step=0.1,
                        allowCross=False,
                        updatemode="mouseup",
                        tooltip={"placement": "bottom", "always_visible": False},
                    ),
                ],
                style={"marginBottom": "16px"},
            ),
            html.Div(
                style={
                    "display": "grid",
                    "gridTemplateColumns": "1fr 1fr",
                    "gap": "10px",
                    "marginBottom": "4px",
                },
                children=[
                    html.Div(
                        [
                            html.Label("Lower  (nm)", className="form-label"),
                            dcc.Input(
                                id="manual-lo",
                                type="number",
                                value=init_lo,
                                debounce=True,
                                className="form-input",
                            ),
                        ]
                    ),
                    html.Div(
                        [
                            html.Label("Upper  (nm)", className="form-label"),
                            dcc.Input(
                                id="manual-hi",
                                type="number",
                                value=init_hi,
                                debounce=True,
                                className="form-input",
                            ),
                        ]
                    ),
                ],
            ),
            html.Div(id="src-hint", className="src-hint none", children="—"),
            html.Div(
                className="legend-row",
                children=[
                    html.Span([
                        html.Span(className="legend-swatch", style={
                            "background": "rgba(62,173,90,0.35)",
                            "border": "1px solid rgba(40,150,70,0.9)",
                        }),
                        "saved",
                    ]),
                    html.Span([
                        html.Span(className="legend-swatch", style={
                            "background": "rgba(255,167,38,0.4)",
                            "border": "1px solid rgba(245,130,10,0.95)",
                        }),
                        "pending",
                    ]),
                    html.Span([
                        html.Span(className="legend-swatch", style={
                            "background": "rgba(88,209,235,0.4)",
                            "border": "1px solid rgba(88,209,235,0.95)",
                        }),
                        "added",
                    ]),
                    html.Span([
                        html.Span(className="legend-swatch", style={
                            "background": "rgba(248,81,73,0.12)",
                            "border": "1px dashed rgba(248,81,73,0.5)",
                        }),
                        "excluded",
                    ]),
                ],
            ),
        ],
    )


# ══════════════════════════════════════════════════════════════════════════════
# Stats Panel
# ══════════════════════════════════════════════════════════════════════════════


def build_stats_panel() -> html.Div:
    return html.Div(
        className="card",
        children=[
            html.Div("Live Statistics", className="card-title"),
            html.Div(id="candidate-stats"),
        ],
    )


def render_stats(chi2: dict, resid: dict, lo: float, hi: float) -> html.Div:
    c2 = chi2["median_chi2"]
    color = chi2_color(c2)
    label = chi2_label(c2)
    pct = chi2_pct(c2)

    return html.Div(
        [
            html.Div(
                f"λ  {lo:.3f} – {hi:.3f} nm  ·  Δλ = {hi-lo:.3f} nm",
                style={
                    "fontFamily": MONO,
                    "fontSize": "11px",
                    "color": C["muted"],
                    "marginBottom": "12px",
                    "background": C["bg"],
                    "padding": "6px 10px",
                    "borderRadius": "5px",
                    "border": f"1px solid {C['border2']}",
                },
            ),
            html.Div(
                className="stat-grid",
                children=[
                    html.Div(
                        className="stat-block",
                        children=[
                            html.Div("χ²/N  median", className="stat-key"),
                            html.Div(
                                style={
                                    "display": "flex",
                                    "alignItems": "baseline",
                                    "gap": "6px",
                                },
                                children=[
                                    html.Div(
                                        _fmt(c2, ".3f"),
                                        className="stat-val",
                                        style={"color": color},
                                    ),
                                    html.Span(
                                        html.Span(
                                            label,
                                            className="quality-badge",
                                            style={
                                                "color": color,
                                                "background": color + "22",
                                                "border": f"1px solid {color}44",
                                            },
                                        )
                                    ),
                                ],
                            ),
                            html.Div(
                                className="chi2-track",
                                children=[
                                    html.Div(
                                        className="chi2-fill",
                                        style={"width": f"{pct}%", "background": color},
                                    ),
                                ],
                            ),
                        ],
                    ),
                    html.Div(
                        className="stat-block",
                        children=[
                            html.Div("χ²/N  16–84%", className="stat-key"),
                            html.Div(
                                f"{_fmt(chi2['p16_chi2'], '.2f')} – {_fmt(chi2['p84_chi2'], '.2f')}",
                                className="stat-val",
                                style={"fontSize": "14px", "color": C["text"]},
                            ),
                        ],
                    ),
                    html.Div(
                        className="stat-block",
                        children=[
                            html.Div("Stars", className="stat-key"),
                            html.Div(
                                [
                                    html.Span(
                                        str(chi2["n_stars"]),
                                        className="stat-val",
                                        style={"color": C["cyan"]},
                                    ),
                                    html.Span(" ★", className="stat-unit"),
                                ]
                            ),
                        ],
                    ),
                    html.Div(
                        className="stat-block",
                        children=[
                            html.Div("Median pix/star", className="stat-key"),
                            html.Div(
                                [
                                    html.Span(
                                        str(chi2["med_npix"]),
                                        className="stat-val",
                                        style={"color": C["text"]},
                                    ),
                                    html.Span(" px", className="stat-unit"),
                                ]
                            ),
                        ],
                    ),
                ],
            ),
            html.Div(className="divider"),
            html.Div(
                "Residual diagnostics",
                style={
                    "fontFamily": MONO,
                    "fontSize": "10px",
                    "letterSpacing": "0.1em",
                    "textTransform": "uppercase",
                    "color": C["dim"],
                    "marginBottom": "8px",
                },
            ),
            html.Div(
                className="resid-grid",
                children=[
                    html.Div(
                        className="resid-row",
                        children=[
                            html.Span("mean", className="rr-key"),
                            html.Span(
                                _fmt(resid.get("mean_resid", np.nan), "+.4f"),
                                className="rr-val",
                            ),
                        ],
                    ),
                    html.Div(
                        className="resid-row",
                        children=[
                            html.Span("|mean|", className="rr-key"),
                            html.Span(
                                _fmt(resid.get("mean_abs_resid", np.nan), ".4f"),
                                className="rr-val",
                            ),
                        ],
                    ),
                    html.Div(
                        className="resid-row",
                        children=[
                            html.Span("|p95|", className="rr-key"),
                            html.Span(
                                _fmt(resid.get("p95_abs_resid", np.nan), ".4f"),
                                className="rr-val",
                            ),
                        ],
                    ),
                    html.Div(
                        className="resid-row",
                        children=[
                            html.Span("|res|/σ  mean", className="rr-key"),
                            html.Span(
                                _fmt(resid.get("mean_norm_resid", np.nan), ".3f"),
                                className="rr-val",
                            ),
                        ],
                    ),
                    html.Div(
                        className="resid-row",
                        children=[
                            html.Span("grid pts", className="rr-key"),
                            html.Span(str(resid.get("n_grid", 0)), className="rr-val"),
                        ],
                    ),
                ],
            ),
        ]
    )


# ══════════════════════════════════════════════════════════════════════════════
# Table Panel
# ══════════════════════════════════════════════════════════════════════════════


def _effective_excluded(
    real_idx: int,
    ll_entries,
    pending_changes,
) -> bool:
    """Return the effective excluded state, accounting for any unsaved
    pending edit that has toggled exclusion for this region."""
    pc = (pending_changes or {}).get(str(real_idx))
    if isinstance(pc, dict) and "excluded" in pc:
        return bool(pc.get("excluded", False))
    if ll_entries and 0 <= real_idx < len(ll_entries):
        return bool(ll_entries[real_idx].get("excluded", False))
    return False


def build_table_row(
    i: int,
    row: dict,
    ll_entries=None,
    pending_changes=None,
) -> html.Tr:
    """Render a single region table row. Shared between the initial
    layout build and the filter_table callback so the exclude/include
    button always reflects the effective (pending-aware) state."""
    col = chi2_color(row["med_chi2"])
    lbl = chi2_label(row["med_chi2"])
    real_idx = int(row.get("region_idx", i))
    is_excluded = _effective_excluded(real_idx, ll_entries, pending_changes)

    if is_excluded:
        btn_char = "\u21ba"  # anticlockwise open-circle arrow = restore
        btn_cls = "btn btn-xs btn-green"
        btn_title = "Restore this region (include in saved line list)"
    else:
        btn_char = "\u2a2f"  # vector cross product = exclude
        btn_cls = "btn btn-xs btn-danger"
        btn_title = "Exclude this region from saved line list"

    tr_cls = "asap-row-excluded" if is_excluded else None

    return html.Tr(
        id={"type": "region-row", "index": real_idx},
        className=tr_cls,
        children=[
            html.Td(f"{i+1}", className="rank-num"),
            html.Td(f"{row['center']:.3f}"),
            html.Td(f"{row['lower']:.3f} – {row['upper']:.3f}"),
            html.Td(
                html.Span(
                    f"{row['element']} {row['ion']}", className="elem-tag"
                )
            ),
            html.Td(
                f"{row['med_chi2']:.3f}",
                style={"color": col, "fontWeight": "700"},
            ),
            html.Td(
                html.Span(
                    lbl,
                    className="q-badge",
                    style={
                        "background": col + "22",
                        "color": col,
                        "border": f"1px solid {col}55",
                    },
                )
            ),
            html.Td(str(row["n_stars"])),
            html.Td(str(row["med_npix"])),
            html.Td(
                html.Button(
                    "→",
                    id={"type": "nav-btn", "index": real_idx},
                    n_clicks=0,
                    className="btn btn-xs btn-cyan",
                    title="Navigate to region",
                )
            ),
            html.Td(
                html.Button(
                    btn_char,
                    id={"type": "exclude-btn", "index": real_idx},
                    n_clicks=0,
                    className=btn_cls,
                    title=btn_title,
                )
            ),
        ],
    )


def build_table_panel(
    region_summary: List[dict],
    unique_elements: List[str],
    ll_entries=None,
) -> html.Div:
    elem_options = [{"label": "All elements", "value": "ALL"}] + [
        {"label": e, "value": e} for e in unique_elements
    ]
    header_row = html.Tr(
        [
            html.Th("#"),
            html.Th("Center (nm)"),
            html.Th("Range (nm)"),
            html.Th("Species"),
            html.Th("χ²/N med"),
            html.Th("Quality"),
            html.Th("N★"),
            html.Th("N pix"),
            html.Th(""),
            html.Th(""),
        ]
    )
    body_rows = [
        build_table_row(i, row, ll_entries, None)
        for i, row in enumerate(region_summary[:50])
    ]
    return html.Div(
        className="card gap-lg",
        children=[
            html.Div(
                style={
                    "display": "flex",
                    "alignItems": "center",
                    "justifyContent": "space-between",
                    "marginBottom": "12px",
                },
                children=[
                    html.Div(
                        "Worst Fitted Regions  (top 50 by median χ²/N)",
                        className="card-title",
                        style={
                            "marginBottom": 0,
                            "borderBottom": "none",
                            "paddingBottom": 0,
                        },
                    ),
                    html.Div(
                        style={"width": "200px"},
                        children=[
                            dcc.Dropdown(
                                id="elem-filter",
                                options=elem_options,
                                value="ALL",
                                clearable=False,
                                style={"fontSize": "12px"},
                            ),
                        ],
                    ),
                ],
            ),
            html.Div(
                className="table-wrap",
                children=[
                    html.Table(
                        className="asap-table",
                        children=[
                            html.Thead(header_row),
                            html.Tbody(id="table-body", children=body_rows),
                        ],
                    )
                ],
            ),
        ],
    )


# ══════════════════════════════════════════════════════════════════════════════
# Session Panel
# ══════════════════════════════════════════════════════════════════════════════


def build_session_panel() -> html.Div:
    return html.Div(
        className="card",
        children=[
            html.Div(
                style={
                    "display": "flex",
                    "alignItems": "center",
                    "justifyContent": "space-between",
                    "marginBottom": "12px",
                },
                children=[
                    html.Div(
                        "Session Candidates",
                        className="card-title",
                        style={
                            "marginBottom": 0,
                            "borderBottom": "none",
                            "paddingBottom": 0,
                        },
                    ),
                    html.Div(
                        style={"display": "flex", "gap": "8px"},
                        children=[
                            html.Button(
                                "⬇ Export",
                                id="export-btn",
                                n_clicks=0,
                                className="btn btn-sm btn-amber",
                            ),
                            html.Button(
                                "✕ Clear",
                                id="clear-session-btn",
                                n_clicks=0,
                                className="btn btn-sm btn-danger",
                            ),
                        ],
                    ),
                ],
            ),
            html.Div(
                id="session-log",
                className="session-log",
                children=[html.Div("No candidates added yet.", className="log-empty")],
            ),
            dcc.Download(id="download-session"),
        ],
    )


# ══════════════════════════════════════════════════════════════════════════════
# Main Layout Builder
# ══════════════════════════════════════════════════════════════════════════════


def build_layout(dataset: dict, base_fig, debug_hover: bool = False) -> html.Div:
    min_w = float(dataset["common_w"][0])
    max_w = float(dataset["common_w"][-1])
    init_lo, init_hi = initial_candidate_range(dataset, min_w, max_w)

    unique_elements = sorted({e["element"] for e in dataset["region_summary"]})
    all_rows = dataset["region_summary"]

    ll_stats_jsonable = [
        {
            "region_idx": int(rs["region_idx"]),
            "lower": float(rs["lower"]),
            "upper": float(rs["upper"]),
            "center": float(rs["center"]),
            "element": str(rs["element"]),
            "ion": str(rs["ion"]),
            "med_chi2": float(rs["med_chi2"]) if np.isfinite(rs["med_chi2"]) else None,
            "n_stars": int(rs["n_stars"]),
            "med_npix": int(rs["med_npix"]),
            "mean_resid": (
                float(rs["mean_resid"]) if np.isfinite(rs["mean_resid"]) else None
            ),
            "mean_abs_resid": (
                float(rs["mean_abs_resid"])
                if np.isfinite(rs["mean_abs_resid"])
                else None
            ),
            "p95_abs_resid": (
                float(rs["p95_abs_resid"]) if np.isfinite(rs["p95_abs_resid"]) else None
            ),
            "mean_norm_resid": (
                float(rs["mean_norm_resid"])
                if np.isfinite(rs["mean_norm_resid"])
                else None
            ),
        }
        for rs in dataset["ll_hover_stats"]
    ]

    def _jsonable_entry(e: dict) -> dict:
        return {
            "center": float(e["center"]),
            "lower": float(e["lower"]),
            "upper": float(e["upper"]),
            "element": str(e.get("element", "Unknown")),
            "ion": str(e.get("ion", "1")),
            "order": str(e.get("order", "0")),
            "inline_comment": str(e.get("inline_comment", "") or ""),
            "excluded": bool(e.get("excluded", False)),
            "added": bool(e.get("added", False)),
            "original_lower": (
                float(e["original_lower"])
                if e.get("original_lower") is not None
                else None
            ),
            "original_upper": (
                float(e["original_upper"])
                if e.get("original_upper") is not None
                else None
            ),
            "original_excluded": bool(e.get("original_excluded", False)),
        }

    ll_entries_jsonable = [_jsonable_entry(e) for e in dataset["ll_entries"]]

    return html.Div(
        [
            build_header(dataset),
            html.Div(
                className="asap-main",
                children=[
                    # ── Spectrum plot ────────────────────────────────────────────────
                    html.Div(
                        className="plot-wrap gap-md",
                        style={"position": "relative"},
                        children=[
                            dcc.Graph(
                                id="spectrum-graph",
                                figure=base_fig,
                                clear_on_unhover=True,
                                config={
                                    "scrollZoom": True,
                                    "displaylogo": False,
                                    "doubleClick": "reset+autosize",
                                    "modeBarButtonsToRemove": ["lasso2d", "select2d"],
                                    "editable": False,
                                },
                                style={"height": "820px"},
                            ),
                            html.Div(
                                id="drag-handles-overlay",
                                style={
                                    "position": "absolute",
                                    "top": "0",
                                    "left": "0",
                                    "right": "0",
                                    "bottom": "0",
                                    "pointerEvents": "none",
                                    "zIndex": "10",
                                },
                            ),
                        ],
                    ),
                    # ── Candidate + Stats ────────────────────────────────────────────
                    html.Div(
                        className="two-col gap-md",
                        children=[
                            build_candidate_panel(min_w, max_w, init_lo, init_hi),
                            build_stats_panel(),
                        ],
                    ),
                    # ── Table + Session ──────────────────────────────────────────────
                    html.Div(
                        className="two-col gap-md",
                        children=[
                            build_table_panel(
                                all_rows, unique_elements, ll_entries_jsonable
                            ),
                            build_session_panel(),
                        ],
                    ),
                    html.Div(
                        className="card gap-md",
                        style={"display": "block" if debug_hover else "none"},
                        children=[
                            html.Div("Hover Debug", className="card-title"),
                            html.Pre(
                                id="debug-hover-log",
                                style={
                                    "maxHeight": "220px",
                                    "overflowY": "auto",
                                    "fontFamily": MONO,
                                    "fontSize": "11px",
                                    "color": C["text"],
                                    "background": C["bg"],
                                    "border": f"1px solid {C['border2']}",
                                    "borderRadius": "6px",
                                    "padding": "10px",
                                    "whiteSpace": "pre-wrap",
                                },
                            ),
                        ],
                    ),
                ],
            ),
            # ── Hidden state stores ────────────────────────────────────────────
            dcc.Store(id="session-store", data=[]),
            dcc.Store(id="source-type", data="none"),
            dcc.Store(id="ll-entries-store", data=ll_entries_jsonable),
            dcc.Store(id="ll-stats-store", data=ll_stats_jsonable),
            dcc.Store(id="drag-result-store", data=None),
            dcc.Store(id="draw-region-store", data=None),
            dcc.Store(id="tooltip-sync-store", data=None),
            dcc.Store(id="handles-sync-store", data=None),
            dcc.Store(id="handles-hover-sync-store", data=None),
            dcc.Store(id="pending-changes-store", data={}),
            dcc.Store(id="unsaved-flag-store", data={"has_changes": False}),
            dcc.Store(id="discard-signal-store", data=None),
            dcc.Store(id="draw-mode-active-store", data=False),
            dcc.Store(id="last-saved-path-store", data=None),
            dcc.Store(id="selected-region-store", data=None),
            dcc.Store(id="pending-history-store", data=[]),
            # ── Cursor tooltip ─────────────────────────────────────────────────
            html.Div(
                id="cursor-tooltip",
                style={
                    "display": "none",
                    "position": "fixed",
                    "backgroundColor": C["surf2"],
                    "border": f"1px solid {C['border']}",
                    "borderRadius": "6px",
                    "padding": "8px 12px",
                    "fontSize": "11px",
                    "fontFamily": MONO,
                    "color": C["text"],
                    "zIndex": "1000",
                    "maxWidth": "280px",
                    "boxShadow": "0 4px 12px rgba(0,0,0,0.4)",
                    "pointerEvents": "none",
                },
            ),
            # ── Draw-region confirmation popover ───────────────────────────────
            html.Div(
                id="draw-confirm-popover",
                style={
                    "display": "none",
                    "position": "fixed",
                    "backgroundColor": C["surf"],
                    "border": f"2px solid {C['amber']}",
                    "borderRadius": "8px",
                    "padding": "12px 16px",
                    "zIndex": "999",
                    "boxShadow": "0 6px 20px rgba(0,0,0,0.5)",
                },
                children=[
                    html.Div(
                        "Add this region?",
                        style={"marginBottom": "10px", "fontWeight": "bold"},
                    ),
                    html.Div(
                        id="draw-confirm-range-text",
                        style={"fontSize": "12px", "marginBottom": "12px"},
                    ),
                    html.Div(
                        style={"display": "flex", "gap": "8px"},
                        children=[
                            html.Button(
                                "✓ Accept",
                                id="draw-confirm-accept",
                                n_clicks=0,
                                className="btn btn-sm btn-green",
                            ),
                            html.Button(
                                "✕ Cancel",
                                id="draw-confirm-cancel",
                                n_clicks=0,
                                className="btn btn-sm btn-danger",
                            ),
                        ],
                    ),
                ],
            ),
            # ── Save toast notification ────────────────────────────────────────
            html.Div(
                id="save-toast", className="save-toast", style={"display": "none"}
            ),
            dcc.Store(id="save-toast-trigger", data=None),
            # ── Status bar ─────────────────────────────────────────────────────
            html.Div(
                className="status-bar",
                children=[
                    html.Div(className="status-dot"),
                    html.Span(
                        f"ASAP  ·  {dataset['suffix']}  ·  {dataset['n_stars']} stars",
                        style={"color": C["dim"]},
                    ),
                    html.Span("·"),
                    html.Span(id="status-range", style={"color": C["cyan"]}),
                ],
            ),
        ]
    )
