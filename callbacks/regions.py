"""
Line List Region Callbacks (Boundary Dragging with Deferred Persistence)

Uses @app.callback (instance-scoped) throughout, NOT the global @callback.
The global decorator re-registers on Dash hot-reload, producing duplicate
output errors. @app.callback is scoped to the app instance and is safe.
"""

from pathlib import Path

from dash import Input, Output, State, no_update


def register_region_callbacks(app, dataset, min_w, max_w):
    """Register line-list region boundary dragging callbacks."""

    # ════════════════════════════════════════════════════════════
    # Callback – edge drag -> accumulate in pending-changes-store
    # ════════════════════════════════════════════════════════════
    @app.callback(
        Output("pending-changes-store", "data"),
        Output("unsaved-flag-store", "data"),
        Input("drag-result-store", "data"),
        State("ll-entries-store", "data"),
        State("pending-changes-store", "data"),
        prevent_initial_call=True,
    )
    def update_ll_bounds_from_drag(drag_result, ll_entries_data, pending_changes):
        if not drag_result or not ll_entries_data:
            return no_update, no_update

        region_idx = drag_result.get("region_idx")
        bound = drag_result.get("bound")
        new_x = drag_result.get("new_x_nm")

        if region_idx is None or bound is None or new_x is None:
            return no_update, no_update
        if region_idx < 0 or region_idx >= len(ll_entries_data):
            return no_update, no_update

        entry = dict(pending_changes.get(str(region_idx), ll_entries_data[region_idx]))
        lower = float(entry["lower"])
        upper = float(entry["upper"])
        min_gap = 0.001
        new_x = max(min_w, min(max_w, float(new_x)))

        if bound == "lower":
            lower = min(new_x, upper - min_gap)
        elif bound == "upper":
            upper = max(new_x, lower + min_gap)
        else:
            return no_update, no_update

        entry["lower"] = float(lower)
        entry["upper"] = float(upper)
        entry["center"] = 0.5 * (lower + upper)

        updated = dict(pending_changes)
        updated[str(region_idx)] = entry
        return updated, {"has_changes": True}

    # ════════════════════════════════════════════════════════════
    # Callback – save pending changes to disk
    #
    # [M9 FIX] Now outputs to save-toast for user-visible feedback.
    # ════════════════════════════════════════════════════════════
    @app.callback(
        Output("ll-entries-store", "data"),
        Output("pending-changes-store", "data", allow_duplicate=True),
        Output("unsaved-flag-store", "data", allow_duplicate=True),
        Output("save-toast", "children"),
        Output("save-toast", "style"),
        Output("save-toast", "className"),
        Input("save-changes-btn", "n_clicks"),
        State("ll-entries-store", "data"),
        State("pending-changes-store", "data"),
        prevent_initial_call=True,
    )
    def apply_pending_changes(n_clicks, ll_entries_data, pending_changes):
        from ..data_processing import save_line_list

        if not pending_changes or not ll_entries_data:
            return (
                no_update,
                no_update,
                no_update,
                no_update,
                no_update,
                no_update,
            )

        updated = list(ll_entries_data)
        for idx_str, entry in pending_changes.items():
            try:
                idx = int(idx_str)
                if 0 <= idx < len(updated):
                    updated[idx] = entry
            except (ValueError, KeyError):
                continue

        n_changed = len(pending_changes)

        try:
            save_line_list(Path(dataset["line_list"]), updated)
        except OSError as e:
            return (
                no_update,
                no_update,
                no_update,
                f"Save failed: {e}",
                {
                    "display": "block",
                    "background": "#2e0d0b",
                    "color": "#f85149",
                    "border": "1px solid #f85149",
                },
                "save-toast",
            )

        return (
            updated,
            {},
            {"has_changes": False},
            f"Saved {n_changed} region(s) to disk",
            {
                "display": "block",
                "background": "#0b2110",
                "color": "#3fb950",
                "border": "1px solid #3fb950",
            },
            "save-toast",
        )

    # ════════════════════════════════════════════════════════════
    # Callback – auto-hide toast after 3 seconds
    # ════════════════════════════════════════════════════════════
    app.clientside_callback(
        """
        function(toastStyle) {
            if (!toastStyle || toastStyle.display === 'none') {
                return window.dash_clientside
                    ? window.dash_clientside.no_update : null;
            }
            setTimeout(function() {
                var el = document.getElementById('save-toast');
                if (el) el.style.display = 'none';
            }, 3000);
            return window.dash_clientside
                ? window.dash_clientside.no_update : null;
        }
        """,
        Output("save-toast-trigger", "data"),
        Input("save-toast", "style"),
        prevent_initial_call=True,
    )

    # ════════════════════════════════════════════════════════════
    # Callback – discard pending changes
    # ════════════════════════════════════════════════════════════
    @app.callback(
        Output("pending-changes-store", "data", allow_duplicate=True),
        Output("unsaved-flag-store", "data", allow_duplicate=True),
        Output("discard-signal-store", "data"),
        Input("discard-changes-btn", "n_clicks"),
        State("ll-entries-store", "data"),
        prevent_initial_call=True,
    )
    def discard_pending_changes(n_clicks, ll_entries_data):
        return (
            {},
            {"has_changes": False},
            {"tick": n_clicks, "entries": ll_entries_data},
        )

    # ════════════════════════════════════════════════════════════
    # Callback – pending status badge visibility
    # ════════════════════════════════════════════════════════════
    @app.callback(
        Output("pending-status-container", "style"),
        Output("pending-count", "children"),
        Input("unsaved-flag-store", "data"),
        Input("pending-changes-store", "data"),
    )
    def manage_pending_status_ui(unsaved_flag, pending_changes):
        has_changes = (unsaved_flag or {}).get("has_changes", False)
        num_changes = len(pending_changes) if pending_changes else 0
        style = {"display": "flex"} if has_changes else {"display": "none"}
        return style, str(num_changes)
