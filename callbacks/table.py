"""
Table & Heat-strip Refresh Callbacks

Uses @app.callback (instance-scoped) to prevent duplicate registration
on Dash hot-reload.
"""

from dash import Input, Output

from ..layout import build_heatstrip_regions, build_table_row


def register_table_callbacks(app, dataset, min_w, max_w):
    """Register derived-view refresh callbacks (table body + heat-strip)."""

    all_rows = dataset["region_summary"]
    chi2_map = {
        int(r["region_idx"]): float(r["med_chi2"]) for r in all_rows
    }

    # Re-render the table body whenever the ll-entries store or
    # pending-changes store change, so per-row include/exclude buttons
    # stay in sync with the effective excluded state.
    @app.callback(
        Output("table-body", "children"),
        Input("ll-entries-store", "data"),
        Input("pending-changes-store", "data"),
    )
    def refresh_table(ll_entries_data, pending_changes):
        return [
            build_table_row(i, row, ll_entries_data, pending_changes)
            for i, row in enumerate(all_rows[:50])
        ]

    # Re-render the heat-strip region blocks on the same triggers so the
    # mini-map reflects pending drags / exclusions / additions. The
    # navigation viewport is a separate element handled entirely
    # client-side by heatstrip.js, so it is untouched here.
    @app.callback(
        Output("heatstrip-regions", "children"),
        Input("ll-entries-store", "data"),
        Input("pending-changes-store", "data"),
    )
    def refresh_heatstrip(ll_entries_data, pending_changes):
        return build_heatstrip_regions(
            ll_entries_data, pending_changes, chi2_map, min_w, max_w
        )
