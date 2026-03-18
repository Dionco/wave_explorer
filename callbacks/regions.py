"""
Line List Region Callbacks (Boundary Dragging with Deferred Persistence)

Deliberately owns NO figure output. All shape rendering is handled by
update_figure_shapes() in candidate.py, which is the single owner of
spectrum-graph.figure.
"""

from pathlib import Path

from dash import Input, Output, State, callback, no_update


def register_region_callbacks(app, dataset, min_w, max_w):
    """Register line-list region boundary dragging callbacks."""

    # ════════════════════════════════════════════════════════════
    # Callback – edge drag results accumulate in pending-changes
    # ════════════════════════════════════════════════════════════
    @callback(
        Output("pending-changes-store", "data"),
        Output("unsaved-flag-store", "data"),
        Input("drag-result-store", "data"),
        State("ll-entries-store", "data"),
        State("pending-changes-store", "data"),
        prevent_initial_call=True,
    )
    def update_ll_bounds_from_drag(drag_result, ll_entries_data, pending_changes):
        """
        On boundary drag release, accumulate changes in pending-changes-store
        but do NOT save to disk yet.

        drag_result: {region_idx, bound: "lower"|"upper", new_x_nm}
        pending_changes: {str(region_idx): {lower, upper, center, element, ion}}
        """
        if not drag_result or not ll_entries_data:
            return no_update, no_update

        region_idx = drag_result.get("region_idx")
        bound      = drag_result.get("bound")
        new_x      = drag_result.get("new_x_nm")

        if region_idx is None or bound is None or new_x is None:
            return no_update, no_update

        if region_idx < 0 or region_idx >= len(ll_entries_data):
            return no_update, no_update

        # Start from pending state if one already exists for this region.
        entry = dict(pending_changes.get(str(region_idx), ll_entries_data[region_idx]))

        lower   = float(entry["lower"])
        upper   = float(entry["upper"])
        min_gap = 0.001
        new_x   = max(min_w, min(max_w, float(new_x)))

        if bound == "lower":
            lower = min(new_x, upper - min_gap)
        elif bound == "upper":
            upper = max(new_x, lower + min_gap)
        else:
            return no_update, no_update

        entry["lower"]  = float(lower)
        entry["upper"]  = float(upper)
        entry["center"] = 0.5 * (lower + upper)

        updated_pending = dict(pending_changes)
        updated_pending[str(region_idx)] = entry

        return updated_pending, {"has_changes": True}

    # ════════════════════════════════════════════════════════════
    # Callback – save all pending changes to disk and ll-entries
    # ════════════════════════════════════════════════════════════
    @callback(
        Output("ll-entries-store", "data"),
        Output("pending-changes-store", "data"),
        Output("unsaved-flag-store", "data"),
        Input("save-changes-btn", "n_clicks"),
        State("ll-entries-store", "data"),
        State("pending-changes-store", "data"),
        prevent_initial_call=True,
    )
    def apply_pending_changes(n_clicks, ll_entries_data, pending_changes):
        """
        On 'Save Changes' click:
        1. Merge pending changes into ll-entries-store
        2. Persist to disk
        3. Clear pending changes
        4. Set unsaved_flag.has_changes = False
        """
        from ..data_processing import save_line_list

        if not pending_changes or not ll_entries_data:
            return no_update, no_update, no_update

        updated_entries = list(ll_entries_data)
        for idx_str, pending_entry in pending_changes.items():
            try:
                idx = int(idx_str)
                if 0 <= idx < len(updated_entries):
                    updated_entries[idx] = pending_entry
            except (ValueError, KeyError):
                continue

        try:
            save_line_list(Path(dataset["line_list"]), updated_entries)
        except OSError as e:
            print(f"Warning: Failed to save line list: {e}")
            return no_update, no_update, no_update

        return updated_entries, {}, {"has_changes": False}

    # ════════════════════════════════════════════════════════════
    # Callback – discard all pending changes
    # ════════════════════════════════════════════════════════════
    @callback(
        Output("pending-changes-store", "data"),
        Output("unsaved-flag-store", "data"),
        Input("discard-changes-btn", "n_clicks"),
        prevent_initial_call=True,
    )
    def discard_pending_changes(n_clicks):
        """Clear pending changes without touching ll-entries-store."""
        return {}, {"has_changes": False}

    # ════════════════════════════════════════════════════════════
    # Callback – pending status UI (badge + button visibility)
    # ════════════════════════════════════════════════════════════
    @callback(
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