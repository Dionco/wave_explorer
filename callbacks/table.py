"""
Table Filtering Callbacks
"""

from dash import Input, Output, callback, html

from ..theme import C, chi2_color, chi2_label


def register_table_callbacks(app, dataset):
    """Register table filtering callbacks."""

    all_rows = dataset["region_summary"]

    # ════════════════════════════════════════════════════════════
    # Callback – element filter for table body
    # ════════════════════════════════════════════════════════════
    @callback(
        Output("table-body", "children"),
        Input("elem-filter", "value"),
    )
    def filter_table(elem_filter):
        rows = all_rows if elem_filter == "ALL" else [
            r for r in all_rows if r["element"] == elem_filter
        ]
        body_rows = []
        for i, row in enumerate(rows[:50]):
            col = chi2_color(row["med_chi2"])
            lbl = chi2_label(row["med_chi2"])
            # Use index in all_rows for nav btn to keep navigation correct
            real_idx = all_rows.index(row) if row in all_rows else i
            body_rows.append(html.Tr(id={"type": "region-row", "index": real_idx}, children=[
                html.Td(f"{i+1}", className="rank-num"),
                html.Td(f"{row['center']:.3f}"),
                html.Td(f"{row['lower']:.3f} – {row['upper']:.3f}"),
                html.Td(html.Span(f"{row['element']} {row['ion']}", className="elem-tag")),
                html.Td(f"{row['med_chi2']:.3f}", style={"color": col, "fontWeight": "700"}),
                html.Td(html.Span(lbl, className="q-badge",
                                  style={"background": col + "22", "color": col,
                                         "border": f"1px solid {col}55"})),
                html.Td(str(row["n_stars"])),
                html.Td(str(row["med_npix"])),
                html.Td(
                    html.Button("→", id={"type": "nav-btn", "index": real_idx},
                                n_clicks=0, className="btn btn-xs btn-cyan"),
                ),
            ]))
        return body_rows
