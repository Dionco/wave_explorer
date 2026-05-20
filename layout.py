"""
ASAP Layout & UI Component Builders
"""

from pathlib import Path
from typing import List

import numpy as np
from dash import dcc, html

from .theme import C, MONO, _fmt, chi2_color, chi2_label, chi2_pct

# ══════════════════════════════════════════════════════════════════════════════
# Brand mark — abstract spectral-peak SVG (warm editorial identity).
# Encoded as a data URI so it can be served through a plain html.Img without
# needing an extra static asset or raw-HTML rendering.
# ══════════════════════════════════════════════════════════════════════════════

BRAND_MARK = (
    "data:image/svg+xml;utf8,"
    "<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none'>"
    "<path d='M2 18 L6 18 L8 12 L10 18 L12 6 L14 18 L16 9 L18 18 L22 18' "
    "stroke='%23b3553b' stroke-width='2' stroke-linecap='round' "
    "stroke-linejoin='round'/>"
    "<circle cx='12' cy='6' r='1.5' fill='%231a1814'/></svg>"
)


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
                    html.Img(src=BRAND_MARK, className="wordmark-mark", alt=""),
                    html.Span("Wave Explorer"),
                    html.Span("Line curation · ASAP", className="wm-sub"),
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
                className="btn btn-sm",
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
                        className="btn btn-sm",
                        title="Revert the most recent change",
                        disabled=True,
                    ),
                    html.Button(
                        "\u2b73 Save Curated File",
                        id="save-changes-btn",
                        n_clicks=0,
                        className="btn btn-sm btn-primary",
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
# Stats Panel
# ══════════════════════════════════════════════════════════════════════════════


_ROMAN = {"1": "I", "2": "II", "3": "III", "4": "IV", "5": "V"}


def romanize(ion) -> str:
    """Render an ionisation stage as a Roman numeral (1 -> I, 2 -> II)."""
    return _ROMAN.get(str(ion).strip(), str(ion))


def _legend_swatch(color: str, label: str) -> html.Div:
    return html.Div(
        className="legend-item",
        children=[
            html.Span(className="legend-swatch", style={"background": color}),
            label,
        ],
    )


def build_histogram(region_summary: List[dict]) -> html.Div:
    """A compact χ²/N distribution histogram for the fitted regions.

    Static — computed once from the region summary. Bars are coloured by
    the quality ramp so the spread of fit quality is readable at a glance.
    """
    bin_w = 2.0
    n_bins = 22
    bins = [0] * n_bins
    vals = [
        float(r["med_chi2"])
        for r in region_summary
        if r.get("med_chi2") is not None and np.isfinite(r["med_chi2"])
    ]
    for v in vals:
        b = min(n_bins - 1, max(0, int(v / bin_w)))
        bins[b] += 1
    peak = max(bins + [1])

    bars = [
        html.Div(
            className="hist-bar",
            title=(
                f"χ²/N {i * bin_w:.0f}–{(i + 1) * bin_w:.0f}"
                f"{'+' if i == n_bins - 1 else ''}  ·  {count} region"
                f"{'' if count == 1 else 's'}"
            ),
            children=html.Div(
                className="hist-bar-fill",
                style={
                    "height": f"{(count / peak) * 100.0:.1f}%",
                    "background": chi2_color((i + 0.5) * bin_w),
                },
            ),
        )
        for i, count in enumerate(bins)
    ]

    return html.Div(
        className="hist-card",
        children=[
            html.Div(
                className="hist-head",
                children=[
                    html.Span("χ²/N distribution", className="eyebrow"),
                    html.Span(f"{len(vals)} fitted regions", className="subtitle"),
                ],
            ),
            html.Div(className="hist-bars", children=bars),
            html.Div(
                className="hist-legend",
                children=[
                    _legend_swatch(C["green"], "good"),
                    _legend_swatch(C["amber"], "fair"),
                    _legend_swatch(C["orange"], "poor"),
                    _legend_swatch(C["red"], "bad"),
                ],
            ),
        ],
    )


def build_heatstrip_regions(
    ll_entries,
    pending_changes,
    chi2_map: dict,
    min_w: float,
    max_w: float,
) -> List[html.Div]:
    """Build the per-region blocks of the heat-strip mini-map.

    Shared between the initial layout build and the refresh callback so
    the strip always reflects the effective (pending-aware) line list.
    """
    span = max(1e-6, max_w - min_w)
    pending_changes = pending_changes or {}
    blocks: List[html.Div] = []
    for idx, entry in enumerate(ll_entries or []):
        staged = pending_changes.get(str(idx))
        e = staged if staged is not None else entry
        lo = float(e["lower"])
        hi = float(e["upper"])
        excluded = bool(e.get("excluded", False))
        left = (lo - min_w) / span * 100.0
        width = max(0.18, (hi - lo) / span * 100.0)
        c2 = chi2_map.get(idx)
        color = chi2_color(c2) if c2 is not None else C["dim"]
        tip = f"#{idx + 1}  ·  λ {lo:.2f}–{hi:.2f} nm"
        if c2 is not None and np.isfinite(c2):
            tip += f"  ·  χ²/N {c2:.2f}"
        blocks.append(
            html.Div(
                className="heatstrip-region"
                + (" excluded" if excluded else ""),
                style={
                    "left": f"{left:.4f}%",
                    "width": f"{width:.4f}%",
                    "background": color,
                },
                title=tip,
            )
        )
    return blocks


def build_heatstrip(dataset: dict, min_w: float, max_w: float) -> html.Div:
    """Heat-strip mini-map: full-λ quality overview + navigation viewport."""
    chi2_map = {
        int(r["region_idx"]): float(r["med_chi2"])
        for r in dataset["region_summary"]
    }
    regions = build_heatstrip_regions(
        dataset["ll_entries"], {}, chi2_map, min_w, max_w
    )
    return html.Div(
        className="heatstrip-section",
        children=[
            html.Div(
                className="heatstrip-head",
                children=[
                    html.Span(
                        "Quality map · full λ range", className="eyebrow"
                    ),
                    html.Span(
                        "click or drag to navigate", className="subtitle"
                    ),
                ],
            ),
            html.Div(
                id="heatstrip",
                className="heatstrip-wrap",
                title="Click or drag to move the spectrum view",
                children=[
                    html.Div(
                        id="heatstrip-regions",
                        className="heatstrip-regions",
                        children=regions,
                    ),
                    html.Div(
                        id="heatstrip-viewport",
                        className="heatstrip-viewport",
                    ),
                ],
                **{
                    "data-lmin": f"{min_w:.6f}",
                    "data-lmax": f"{max_w:.6f}",
                },
            ),
        ],
    )


def build_stats_panel(region_summary: List[dict]) -> html.Div:
    return html.Div(
        className="card",
        children=[
            html.Div("Live Statistics", className="card-title"),
            html.Div(id="candidate-stats"),
            build_histogram(region_summary),
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
                f"{row['med_chi2']:.3f}",
                style={"color": col, "fontWeight": "700"},
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
    ll_entries=None,
) -> html.Div:
    header_row = html.Tr(
        [
            html.Th("#"),
            html.Th("Center (nm)"),
            html.Th("Range (nm)"),
            html.Th("χ²/N med"),
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
                "Worst Fitted Regions  (top 50 by median χ²/N)",
                className="card-title",
                style={"marginBottom": "12px"},
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
# Main Layout Builder
# ══════════════════════════════════════════════════════════════════════════════


def build_layout(dataset: dict, base_fig, debug_hover: bool = False) -> html.Div:
    all_rows = dataset["region_summary"]
    _common_w = dataset["common_w"]
    _min_w = float(_common_w[0])
    _max_w = float(_common_w[-1])

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
                        className="plot-wrap",
                        children=[
                            html.Div(
                                className="spectrum-toolbar",
                                children=[
                                    html.Div(
                                        className="spectrum-toolbar-left",
                                        children=[
                                            html.Div(
                                                "Spectrum", className="eyebrow"
                                            ),
                                            html.Div(
                                                "Observation, fit & residuals",
                                                className="display-md",
                                            ),
                                        ],
                                    ),
                                    html.Div(
                                        "scroll to zoom · drag to pan · "
                                        "double-click resets",
                                        className="zoom-readout",
                                    ),
                                ],
                            ),
                            html.Div(
                                className="spectrum-canvas-wrap",
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
                                            "responsive": True,
                                            "modeBarButtonsToRemove": [
                                                "lasso2d",
                                                "select2d",
                                            ],
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
                            build_heatstrip(dataset, _min_w, _max_w),
                        ],
                    ),
                    # ── Live Statistics (left) + Worst Fitted Regions (right) ──────
                    html.Div(
                        className="two-col gap-md",
                        children=[
                            build_stats_panel(all_rows),
                            build_table_panel(all_rows, ll_entries_jsonable),
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
                        f"Wave Explorer  ·  ASAP  ·  {dataset['suffix']}  ·  "
                        f"{dataset['n_stars']} stars  ·  "
                        f"{len(dataset['ll_entries'])} regions",
                        style={"color": C["dim"]},
                    ),
                    html.Span("·"),
                    html.Span(id="status-range", style={"color": C["cyan"]}),
                    html.Div(className="h-spacer"),
                    html.Div(
                        className="kbd-hints",
                        children=[
                            html.Span(
                                [html.Span("D", className="kbd"), "draw"]
                            ),
                            html.Span(
                                [html.Span("X", className="kbd"), "exclude"]
                            ),
                            html.Span(
                                [html.Span("Z", className="kbd"), "undo"]
                            ),
                            html.Span(
                                [html.Span("⌘S", className="kbd"), "save"]
                            ),
                            html.Span(
                                [html.Span("Esc", className="kbd"), "deselect"]
                            ),
                        ],
                    ),
                ],
            ),
        ]
    )
