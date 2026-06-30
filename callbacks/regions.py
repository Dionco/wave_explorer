"""
Line List Region Callbacks — edit, exclude, add, save-as-new-file.

All edits accumulate in `pending-changes-store` keyed by entry index.
Saving writes a NEW timestamped curated line list (original is never
overwritten) and then commits the pending entries into `ll-entries-store`.
"""

from pathlib import Path

from dash import ALL, Input, Output, State, no_update
from dash import ctx as dash_ctx


MAX_UNDO_DEPTH = 50


def _entry_from_store(ll_entries_data, idx):
    """Return a shallow-copied dict for the entry at `idx`, or None."""
    if idx is None or idx < 0 or idx >= len(ll_entries_data):
        return None
    return dict(ll_entries_data[idx])


def _stage(pending_changes, ll_entries_data, idx, mutator):
    """Return updated pending-changes dict with mutator applied to entry at idx."""
    entry = _entry_from_store(ll_entries_data, idx)
    if entry is None:
        return None
    staged = dict(pending_changes.get(str(idx), entry))
    mutator(staged)
    updated = dict(pending_changes)
    updated[str(idx)] = staged
    return updated


def _push_history(history, ll_entries_data, pending_changes):
    """Append a snapshot of the current state to the undo history.

    Each entry stores both ll-entries and pending-changes so undo can
    reverse mutations that change either (drag/toggle/draw-add/delete).
    Capped at MAX_UNDO_DEPTH so long sessions don't balloon the store.
    """
    hist = list(history or [])
    hist.append(
        {
            "ll": list(ll_entries_data or []),
            "pending": dict(pending_changes or {}),
        }
    )
    if len(hist) > MAX_UNDO_DEPTH:
        hist = hist[-MAX_UNDO_DEPTH:]
    return hist


def register_region_callbacks(app, dataset, min_w, max_w):
    """Register line-list region edit + save callbacks."""

    # ────────────────────────────────────────────────────────────
    # Edge drag → stage adjusted bounds
    # ────────────────────────────────────────────────────────────
    @app.callback(
        Output("pending-changes-store", "data"),
        Output("unsaved-flag-store", "data"),
        Output("pending-history-store", "data"),
        Input("drag-result-store", "data"),
        State("ll-entries-store", "data"),
        State("pending-changes-store", "data"),
        State("pending-history-store", "data"),
        prevent_initial_call=True,
    )
    def stage_drag(drag_result, ll_entries_data, pending_changes, history):
        if not drag_result or not ll_entries_data:
            return no_update, no_update, no_update

        region_idx = drag_result.get("region_idx")
        bound = drag_result.get("bound")
        new_x = drag_result.get("new_x_nm")
        if region_idx is None or bound is None or new_x is None:
            return no_update, no_update, no_update
        if region_idx < 0 or region_idx >= len(ll_entries_data):
            return no_update, no_update, no_update

        min_gap = 0.001
        new_x = max(min_w, min(max_w, float(new_x)))

        def mutate(e):
            lower = float(e["lower"])
            upper = float(e["upper"])
            if bound == "lower":
                lower = min(new_x, upper - min_gap)
            elif bound == "upper":
                upper = max(new_x, lower + min_gap)
            e["lower"] = float(lower)
            e["upper"] = float(upper)
            e["center"] = 0.5 * (lower + upper)

        updated = _stage(pending_changes, ll_entries_data, region_idx, mutate)
        if updated is None:
            return no_update, no_update, no_update
        new_history = _push_history(history, ll_entries_data, pending_changes)
        return updated, {"has_changes": True}, new_history

    # ────────────────────────────────────────────────────────────
    # Exclude / restore toggle
    # ────────────────────────────────────────────────────────────
    @app.callback(
        Output("pending-changes-store", "data", allow_duplicate=True),
        Output("unsaved-flag-store", "data", allow_duplicate=True),
        Output("pending-history-store", "data", allow_duplicate=True),
        Input({"type": "exclude-btn", "index": ALL}, "n_clicks"),
        State("ll-entries-store", "data"),
        State("pending-changes-store", "data"),
        State("pending-history-store", "data"),
        prevent_initial_call=True,
    )
    def toggle_exclude(n_clicks_list, ll_entries_data, pending_changes, history):
        if not any(n_clicks_list or []):
            return no_update, no_update, no_update
        tid = dash_ctx.triggered_id
        if not isinstance(tid, dict):
            return no_update, no_update, no_update
        idx = tid.get("index")
        if idx is None:
            return no_update, no_update, no_update

        def mutate(e):
            e["excluded"] = not bool(e.get("excluded", False))

        updated = _stage(pending_changes, ll_entries_data, idx, mutate)
        if updated is None:
            return no_update, no_update, no_update
        new_history = _push_history(history, ll_entries_data, pending_changes)
        return updated, {"has_changes": True}, new_history

    # ────────────────────────────────────────────────────────────
    # Accept drawn region → append NEW entry (added=True, pending)
    # ────────────────────────────────────────────────────────────
    @app.callback(
        Output("ll-entries-store", "data", allow_duplicate=True),
        Output("pending-changes-store", "data", allow_duplicate=True),
        Output("unsaved-flag-store", "data", allow_duplicate=True),
        Output("pending-history-store", "data", allow_duplicate=True),
        Input("draw-region-store", "data"),
        State("ll-entries-store", "data"),
        State("pending-changes-store", "data"),
        State("pending-history-store", "data"),
        prevent_initial_call=True,
    )
    def accept_drawn_region(draw_data, ll_entries_data, pending_changes, history):
        if not draw_data:
            return no_update, no_update, no_update, no_update
        lo = draw_data.get("lo")
        hi = draw_data.get("hi")
        if lo is None or hi is None:
            return no_update, no_update, no_update, no_update
        lo = max(min_w, min(max_w, float(lo)))
        hi = max(min_w, min(max_w, float(hi)))
        if hi <= lo:
            return no_update, no_update, no_update, no_update

        new_entry = {
            "center": 0.5 * (lo + hi),
            "lower": lo,
            "upper": hi,
            "element": "Unknown",
            "ion": "1",
            "order": "0",
            "inline_comment": "",
            "excluded": False,
            "added": True,
            "original_lower": None,
            "original_upper": None,
            "original_excluded": False,
        }
        entries = list(ll_entries_data or []) + [new_entry]
        new_idx = len(entries) - 1
        staged = dict(pending_changes or {})
        staged[str(new_idx)] = dict(new_entry)
        new_history = _push_history(history, ll_entries_data, pending_changes)
        return entries, staged, {"has_changes": True}, new_history

    # ────────────────────────────────────────────────────────────
    # Save → write NEW curated file, commit pending into entries
    # ────────────────────────────────────────────────────────────
    TOAST_STYLE_SUCCESS = {
        "display": "block",
        "background": "#0b2110",
        "color": "#3fb950",
        "border": "1px solid #3fb950",
    }
    TOAST_STYLE_ERROR = {
        "display": "block",
        "background": "#2e0d0b",
        "color": "#f85149",
        "border": "1px solid #f85149",
    }
    TOAST_STYLE_INFO = {
        "display": "block",
        "background": "#0a2e38",
        "color": "#58d1eb",
        "border": "1px solid #58d1eb",
    }

    @app.callback(
        Output("ll-entries-store", "data"),
        Output("pending-changes-store", "data", allow_duplicate=True),
        Output("unsaved-flag-store", "data", allow_duplicate=True),
        Output("save-toast", "children"),
        Output("save-toast", "style"),
        Output("save-toast", "className"),
        Output("last-saved-path-store", "data"),
        Output("pending-history-store", "data", allow_duplicate=True),
        Input("save-changes-btn", "n_clicks"),
        State("ll-entries-store", "data"),
        State("pending-changes-store", "data"),
        prevent_initial_call=True,
    )
    def save_curated(n_clicks, ll_entries_data, pending_changes):
        from ..data_processing import save_curated_line_list

        if not ll_entries_data:
            return (no_update,) * 8

        if not pending_changes:
            return (
                no_update,
                no_update,
                no_update,
                "Nothing to save — no pending changes.",
                TOAST_STYLE_INFO,
                "save-toast",
                no_update,
                no_update,
            )

        merged = list(ll_entries_data)
        for idx_str, entry in (pending_changes or {}).items():
            try:
                idx = int(idx_str)
            except (TypeError, ValueError):
                continue
            if 0 <= idx < len(merged):
                merged[idx] = entry

        dest_dir = Path(dataset["line_list"]).parent
        try:
            out_path = save_curated_line_list(
                dest_dir=dest_dir,
                suffix=dataset["suffix"],
                entries=merged,
            )
        except Exception as e:
            return (
                no_update,
                no_update,
                no_update,
                f"Save failed: {e}",
                TOAST_STYLE_ERROR,
                "save-toast",
                no_update,
                no_update,
            )

        # Baseline the saved entries: set original_* to the persisted values
        # so subsequent discards restore to THIS saved state (not to the
        # pre-session file state), and so "ADJUSTED" tags in future saves
        # only appear for edits that post-date this save.
        baselined: list = []
        for e in merged:
            e2 = dict(e)
            e2["original_lower"] = float(e2["lower"])
            e2["original_upper"] = float(e2["upper"])
            e2["original_excluded"] = bool(e2.get("excluded", False))
            baselined.append(e2)

        n_changed = len(pending_changes or {})
        return (
            baselined,
            {},
            {"has_changes": False},
            f"Saved {n_changed} change(s) → {out_path.name}",
            TOAST_STYLE_SUCCESS,
            "save-toast",
            {"path": str(out_path)},
            [],
        )

    # ────────────────────────────────────────────────────────────
    # Auto-hide toast after 3s
    # ────────────────────────────────────────────────────────────
    app.clientside_callback(
        """
        function(toastStyle) {
            if (!toastStyle || toastStyle.display === 'none') {
                return window.dash_clientside
                    ? window.dash_clientside.no_update : null;
            }
            // Cancel any previous auto-hide so rapid successive toasts
            // don't prematurely hide the newest message.
            if (window.__saveToastTimer) {
                clearTimeout(window.__saveToastTimer);
            }
            window.__saveToastTimer = setTimeout(function() {
                var el = document.getElementById('save-toast');
                if (el) el.style.display = 'none';
                window.__saveToastTimer = null;
            }, 4000);
            return window.dash_clientside
                ? window.dash_clientside.no_update : null;
        }
        """,
        Output("save-toast-trigger", "data"),
        Input("save-toast", "style"),
        prevent_initial_call=True,
    )

    # ────────────────────────────────────────────────────────────
    # Discard → drop pending, and drop added-but-never-saved entries
    # ────────────────────────────────────────────────────────────
    @app.callback(
        Output("pending-changes-store", "data", allow_duplicate=True),
        Output("unsaved-flag-store", "data", allow_duplicate=True),
        Output("discard-signal-store", "data"),
        Output("ll-entries-store", "data", allow_duplicate=True),
        Output("pending-history-store", "data", allow_duplicate=True),
        Input("discard-changes-btn", "n_clicks"),
        State("ll-entries-store", "data"),
        State("pending-changes-store", "data"),
        prevent_initial_call=True,
    )
    def discard_pending(n_clicks, ll_entries_data, pending_changes):
        pending_indices = set()
        for k in (pending_changes or {}).keys():
            try:
                pending_indices.add(int(k))
            except (TypeError, ValueError):
                continue
        # An entry is a NEVER-SAVED addition when:
        #   - it was added in this session (`added=True`), AND
        #   - it has no baseline yet (`original_lower is None`), AND
        #   - it still has pending edits (i.e. was never committed via save).
        # Those entries are dropped on discard. Previously-saved entries
        # (even if they are tagged `added=True` from an earlier save) are
        # KEPT and have their pending edits restored to the saved baseline
        # by dropping pending_changes below.
        trimmed = [
            e
            for i, e in enumerate(ll_entries_data or [])
            if not (
                e.get("added", False)
                and e.get("original_lower") is None
                and i in pending_indices
            )
        ]
        return (
            {},
            {"has_changes": False},
            {"tick": n_clicks, "entries": trimmed},
            trimmed,
            [],
        )

    # ────────────────────────────────────────────────────────────
    # Pending badge visibility
    # ────────────────────────────────────────────────────────────
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

    # ────────────────────────────────────────────────────────────
    # Last-saved chip visibility + filename
    # ────────────────────────────────────────────────────────────
    @app.callback(
        Output("last-saved-chip", "style"),
        Output("last-saved-name", "children"),
        Output("last-saved-name", "title"),
        Input("last-saved-path-store", "data"),
    )
    def update_last_saved_chip(saved):
        if not saved or not saved.get("path"):
            return {"display": "none"}, "", ""
        path = saved["path"]
        return (
            {"display": "flex"},
            Path(path).name,
            path,
        )

    # ────────────────────────────────────────────────────────────
    # Selected-region header block render
    # ────────────────────────────────────────────────────────────
    @app.callback(
        Output("selected-region-container", "style"),
        Output("selected-region-label", "children"),
        Output("selected-exclude-btn", "style"),
        Output("selected-restore-btn", "style"),
        Output("selected-delete-btn", "style"),
        Input("selected-region-store", "data"),
        Input("ll-entries-store", "data"),
        Input("pending-changes-store", "data"),
    )
    def render_selected_region_panel(sel, ll_entries_data, pending_changes):
        hidden = {"display": "none"}
        if not sel or not ll_entries_data:
            return hidden, "", hidden, hidden, hidden
        idx = sel.get("region_idx")
        if idx is None or idx < 0 or idx >= len(ll_entries_data):
            return hidden, "", hidden, hidden, hidden

        base = ll_entries_data[idx]
        staged = (pending_changes or {}).get(str(idx))
        live = staged if isinstance(staged, dict) else base

        lo = float(live["lower"])
        hi = float(live["upper"])
        is_excluded = bool(live.get("excluded", False))
        is_unsaved_added = bool(
            base.get("added", False) and base.get("original_lower") is None
        )

        tag = ""
        if is_excluded:
            tag = "  · EXCLUDED"
        elif base.get("added"):
            tag = "  · added"
        if staged is not None:
            tag = tag + (" · pending" if tag else "  · pending")
        # line-list species (element/ion) intentionally omitted — unreliable
        label = f"#{idx + 1}  {lo:.3f}–{hi:.3f} nm{tag}"

        shown = {"display": "inline-flex"}
        exclude_style = hidden if is_excluded else shown
        restore_style = shown if is_excluded else hidden
        delete_style = shown if is_unsaved_added else hidden

        return (
            {"display": "flex"},
            label,
            exclude_style,
            restore_style,
            delete_style,
        )

    # ────────────────────────────────────────────────────────────
    # Selected-region action: exclude / restore (stage pending)
    # ────────────────────────────────────────────────────────────
    @app.callback(
        Output("pending-changes-store", "data", allow_duplicate=True),
        Output("unsaved-flag-store", "data", allow_duplicate=True),
        Output("pending-history-store", "data", allow_duplicate=True),
        Input("selected-exclude-btn", "n_clicks"),
        Input("selected-restore-btn", "n_clicks"),
        State("selected-region-store", "data"),
        State("ll-entries-store", "data"),
        State("pending-changes-store", "data"),
        State("pending-history-store", "data"),
        prevent_initial_call=True,
    )
    def toggle_selected_exclude(
        excl_clicks,
        rest_clicks,
        sel,
        ll_entries_data,
        pending_changes,
        history,
    ):
        if not sel or not ll_entries_data:
            return no_update, no_update, no_update
        idx = sel.get("region_idx")
        if idx is None or idx < 0 or idx >= len(ll_entries_data):
            return no_update, no_update, no_update
        tid = dash_ctx.triggered_id
        if tid == "selected-exclude-btn":
            target = True
        elif tid == "selected-restore-btn":
            target = False
        else:
            return no_update, no_update, no_update

        def mutate(e):
            e["excluded"] = target

        updated = _stage(pending_changes, ll_entries_data, idx, mutate)
        if updated is None:
            return no_update, no_update, no_update
        new_history = _push_history(history, ll_entries_data, pending_changes)
        return updated, {"has_changes": True}, new_history

    # ────────────────────────────────────────────────────────────
    # Selected-region action: delete an unsaved added region
    # ────────────────────────────────────────────────────────────
    @app.callback(
        Output("ll-entries-store", "data", allow_duplicate=True),
        Output("pending-changes-store", "data", allow_duplicate=True),
        Output("unsaved-flag-store", "data", allow_duplicate=True),
        Output("selected-region-store", "data", allow_duplicate=True),
        Output("pending-history-store", "data", allow_duplicate=True),
        Input("selected-delete-btn", "n_clicks"),
        State("selected-region-store", "data"),
        State("ll-entries-store", "data"),
        State("pending-changes-store", "data"),
        State("pending-history-store", "data"),
        prevent_initial_call=True,
    )
    def delete_selected_added_region(
        n_clicks, sel, ll_entries_data, pending_changes, history
    ):
        if not n_clicks or not sel or not ll_entries_data:
            return (no_update,) * 5
        idx = sel.get("region_idx")
        if idx is None or idx < 0 or idx >= len(ll_entries_data):
            return (no_update,) * 5
        entry = ll_entries_data[idx]
        # Only allow deletion of added-but-never-saved regions. Persisted
        # regions should be excluded (reversibly), not deleted outright.
        if not (entry.get("added", False) and entry.get("original_lower") is None):
            return (no_update,) * 5

        trimmed = [e for i, e in enumerate(ll_entries_data) if i != idx]
        rekeyed: dict = {}
        for k, v in (pending_changes or {}).items():
            try:
                ki = int(k)
            except (TypeError, ValueError):
                continue
            if ki == idx:
                continue
            new_k = ki - 1 if ki > idx else ki
            rekeyed[str(new_k)] = v
        has_changes = bool(rekeyed)
        new_history = _push_history(history, ll_entries_data, pending_changes)
        return (
            trimmed,
            rekeyed,
            {"has_changes": has_changes},
            None,
            new_history,
        )

    # ────────────────────────────────────────────────────────────
    # Selected-region action: clear selection
    # ────────────────────────────────────────────────────────────
    @app.callback(
        Output("selected-region-store", "data", allow_duplicate=True),
        Input("selected-clear-btn", "n_clicks"),
        prevent_initial_call=True,
    )
    def clear_selection(n_clicks):
        if not n_clicks:
            return no_update
        return None

    # ────────────────────────────────────────────────────────────
    # Undo — pop last history snapshot
    # ────────────────────────────────────────────────────────────
    @app.callback(
        Output("ll-entries-store", "data", allow_duplicate=True),
        Output("pending-changes-store", "data", allow_duplicate=True),
        Output("unsaved-flag-store", "data", allow_duplicate=True),
        Output("pending-history-store", "data", allow_duplicate=True),
        Input("undo-btn", "n_clicks"),
        State("pending-history-store", "data"),
        prevent_initial_call=True,
    )
    def undo_last_change(n_clicks, history):
        if not n_clicks or not history:
            return no_update, no_update, no_update, no_update
        new_hist = list(history)
        snapshot = new_hist.pop()
        prev_ll = snapshot.get("ll") or []
        prev_pending = snapshot.get("pending") or {}
        has_changes = bool(prev_pending)
        return prev_ll, prev_pending, {"has_changes": has_changes}, new_hist

    @app.callback(
        Output("undo-btn", "disabled"),
        Input("pending-history-store", "data"),
    )
    def sync_undo_disabled(history):
        return not bool(history)

    # ────────────────────────────────────────────────────────────
    # Draw-mode toggle (clientside)
    # ────────────────────────────────────────────────────────────
    app.clientside_callback(
        """
        function(nClicks, currentActive) {
            var active = !currentActive;
            if (window.activateDrawMode) {
                window.activateDrawMode(active);
            }
            var btn = document.getElementById('draw-mode-toggle');
            if (btn) {
                btn.classList.toggle('btn-active', active);
                btn.textContent = active
                    ? '\u25a0 Drawing... (click-drag on plot)'
                    : '\u270e Draw Region';
            }
            return active;
        }
        """,
        Output("draw-mode-active-store", "data"),
        Input("draw-mode-toggle", "n_clicks"),
        State("draw-mode-active-store", "data"),
        prevent_initial_call=True,
    )

    # ────────────────────────────────────────────────────────────
    # After accepting a drawn region, flip draw mode off
    # ────────────────────────────────────────────────────────────
    app.clientside_callback(
        """
        function(drawData) {
            if (!drawData) {
                return window.dash_clientside
                    ? window.dash_clientside.no_update : null;
            }
            if (window.activateDrawMode) window.activateDrawMode(false);
            var btn = document.getElementById('draw-mode-toggle');
            if (btn) {
                btn.classList.remove('btn-active');
                btn.textContent = '\u270e Draw Region';
            }
            return false;
        }
        """,
        Output("draw-mode-active-store", "data", allow_duplicate=True),
        Input("draw-region-store", "data"),
        prevent_initial_call=True,
    )
