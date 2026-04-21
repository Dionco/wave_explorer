"""
Table Filtering Callbacks

Uses @app.callback (instance-scoped) to prevent duplicate registration
on Dash hot-reload.
"""

from dash import Input, Output

from ..layout import build_table_row


def register_table_callbacks(app, dataset):
    """Register table filtering callbacks."""

    all_rows = dataset["region_summary"]

    # Re-render the table body whenever:
    #   - the element filter changes, OR
    #   - the live ll-entries store changes (e.g. save baselines new state), OR
    #   - the pending-changes store changes (e.g. user toggles exclude/include).
    # This keeps the per-row include/exclude button label + style in sync
    # with the effective excluded state of each region.
    @app.callback(
        Output("table-body", "children"),
        Input("elem-filter", "value"),
        Input("ll-entries-store", "data"),
        Input("pending-changes-store", "data"),
    )
    def filter_table(elem_filter, ll_entries_data, pending_changes):
        rows = (
            all_rows
            if elem_filter == "ALL"
            else [r for r in all_rows if r["element"] == elem_filter]
        )
        return [
            build_table_row(i, row, ll_entries_data, pending_changes)
            for i, row in enumerate(rows[:50])
        ]
