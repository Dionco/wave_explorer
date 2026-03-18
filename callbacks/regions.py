"""
Line List Region Callbacks (Boundary Dragging with Deferred Persistence)
FIXED v2: Proper shape updates using Patch() instead of relayout
"""

import re
from typing import Optional

from dash import Input, Output, State, callback, no_update, ctx, Patch

from ..data_processing import save_line_list
from pathlib import Path


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
        
        drag_result format: {region_idx, bound: "lower"|"upper", new_x_nm}
        pending_changes format: {region_idx: {lower, upper, center, element, ion}}
        """
        if not drag_result or not ll_entries_data:
            return no_update, no_update

        region_idx = drag_result.get("region_idx")
        bound = drag_result.get("bound")
        new_x = drag_result.get("new_x_nm")

        if region_idx is None or bound is None or new_x is None:
            return no_update, no_update

        if region_idx < 0 or region_idx >= len(ll_entries_data):
            return no_update, no_update

        # Get the current saved entry as baseline
        entry = dict(ll_entries_data[region_idx])
        
        # If there are pending changes for this region, start from pending state instead
        if str(region_idx) in pending_changes:
            entry = dict(pending_changes[str(region_idx)])
        
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

        # Update pending changes store with the new state
        updated_pending = dict(pending_changes)
        updated_pending[str(region_idx)] = entry

        # Signal that there are unsaved changes
        unsaved_flag = {"has_changes": True}

        return updated_pending, unsaved_flag

    # ════════════════════════════════════════════════════════════
    # Callback – save all pending changes to disk and ll-entries
    # ════════════════════════════════════════════════════════════
    @callback(
        Output("ll-entries-store", "data"),
        Output("pending-changes-store", "data", allow_duplicate=True),
        Output("unsaved-flag-store", "data", allow_duplicate=True),
        Output("save-status-toast", "children"),
        Output("save-status-toast", "style"),
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
        5. Show success/error toast
        """
        if not pending_changes or not ll_entries_data:
            return no_update, no_update, no_update, "", {"display": "none"}

        # Merge pending into entries
        updated_entries = list(ll_entries_data)
        for region_idx_str, pending_entry in pending_changes.items():
            try:
                idx = int(region_idx_str)
                if 0 <= idx < len(updated_entries):
                    updated_entries[idx] = pending_entry
            except (ValueError, KeyError):
                continue

        # Persist to disk
        try:
            save_line_list(Path(dataset["line_list"]), updated_entries)
            toast_msg = f"✓ Saved {len(pending_changes)} region(s) to disk"
            toast_style = {
                "display": "block",
                "background": "#0b2110",
                "border": "1px solid #3fb950",
                "color": "#3fb950",
            }
        except OSError as e:
            print(f"Error: Failed to save line list: {e}")
            toast_msg = f"✗ Save failed: {str(e)}"
            toast_style = {
                "display": "block",
                "background": "#2e0d0b",
                "border": "1px solid #f85149",
                "color": "#f85149",
            }
            return no_update, no_update, no_update, toast_msg, toast_style

        # Clear pending and reset flag
        return updated_entries, {}, {"has_changes": False}, toast_msg, toast_style

    # ════════════════════════════════════════════════════════════
    # Callback – discard all pending changes
    # ════════════════════════════════════════════════════════════
    @callback(
        Output("pending-changes-store", "data", allow_duplicate=True),
        Output("unsaved-flag-store", "data", allow_duplicate=True),
        Input("discard-changes-btn", "n_clicks"),
        prevent_initial_call=True,
    )
    def discard_pending_changes(n_clicks):
        """
        On 'Discard Changes' click:
        1. Clear pending changes
        2. Set unsaved_flag.has_changes = False
        (ll-entries-store remains unchanged—already in saved state)
        """
        return {}, {"has_changes": False}

    # ════════════════════════════════════════════════════════════
    # Callback – manage pending status UI visibility and count
    # ════════════════════════════════════════════════════════════
    @callback(
        Output("pending-status-container", "style"),
        Output("pending-count", "children"),
        Input("unsaved-flag-store", "data"),
        Input("pending-changes-store", "data"),
    )
    def manage_pending_status_ui(unsaved_flag, pending_changes):
        """
        Update the visibility of pending status container and count badge
        based on whether there are unsaved changes.
        """
        has_changes = unsaved_flag.get("has_changes", False) if unsaved_flag else False
        num_changes = len(pending_changes) if pending_changes else 0
        
        # Show container only if there are unsaved changes
        display_style = "flex" if has_changes else "none"
        
        return (
            {"display": display_style},
            str(num_changes),
        )

    # ════════════════════════════════════════════════════════════
    # Callback – update figure shapes to show pending + saved regions
    # FIXED v2: Now uses Patch() instead of relayout
    # ════════════════════════════════════════════════════════════
    @callback(
        Output("spectrum-graph", "figure"),
        Input("ll-entries-store", "data"),
        Input("pending-changes-store", "data"),
    )
    def update_figure_shapes_with_pending(ll_entries, pending_changes):
        """
        Rebuild figure shapes layer to show:
        - Saved regions (green, original style)
        - Pending edits (amber, higher opacity)
        
        Uses Patch() to update shapes without rebuilding entire figure.
        This preserves zoom/pan state and performance.
        
        FIXED v2: Uses Patch() on figure instead of invalid relayout output.
        """
        from ..theme import C
        
        # Create a Patch object to modify only the shapes
        patched_figure = Patch()
        shapes = []
        
        # Color & opacity constants
        saved_fill = "rgba(62, 173, 90, 0.18)"
        saved_line = "rgba(40, 150, 70, 0.80)"
        pending_fill = "rgba(255, 167, 38, 0.25)"
        pending_line = "rgba(245, 130, 10, 0.95)"
        
        # Build pending changes lookup by index
        pending_by_idx = {}
        if pending_changes:
            for idx_str, entry in pending_changes.items():
                try:
                    pending_by_idx[int(idx_str)] = entry
                except (ValueError, TypeError):
                    continue
        
        # Add shapes for each region
        if ll_entries:
            for idx, entry in enumerate(ll_entries):
                # CRITICAL FIX: Use pending bounds if available, otherwise use saved bounds
                if idx in pending_by_idx:
                    # This region has pending changes - use the pending values
                    active_entry = pending_by_idx[idx]
                    is_pending = True
                else:
                    # No pending changes - use saved values
                    active_entry = entry
                    is_pending = False
                
                lower = float(active_entry["lower"])
                upper = float(active_entry["upper"])
                
                fill_color = pending_fill if is_pending else saved_fill
                line_color = pending_line if is_pending else saved_line
                
                # Row 1 — spectrum background rect
                shapes.append(dict(
                    type="rect", xref="x", yref="y domain",
                    x0=lower, x1=upper, y0=0, y1=1,
                    fillcolor=fill_color,
                    line=dict(color=line_color, width=0.8),
                    layer="below",
                    editable=False,
                ))
                
                # Row 2 — residual background rect
                shapes.append(dict(
                    type="rect", xref="x", yref="y2 domain",
                    x0=lower, x1=upper, y0=0, y1=1,
                    fillcolor=fill_color,
                    line=dict(color=line_color, width=0.8),
                    layer="below",
                    editable=False,
                ))
        
        # Use Patch to update only the shapes
        patched_figure["layout"]["shapes"] = shapes
        
        return patched_figure