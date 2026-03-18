"""
ASAP Line Curation Dashboard — App Factory & Entry Point
"""

import argparse
from pathlib import Path

from flask_caching import Cache
from dash import Dash, Input, Output, State

from .callbacks import register_all_callbacks
from .data_processing import build_dataset
from .figure_builder import build_base_figure
from .layout import build_layout


# ══════════════════════════════════════════════════════════════════════════════
# Caching configuration
# ══════════════════════════════════════════════════════════════════════════════

cache = Cache(config={"CACHE_TYPE": "SimpleCache"})


def create_app(dataset: dict, debug_hover: bool = False) -> Dash:
    """Factory function to create the Dash app with all callbacks."""

    min_w    = float(dataset["common_w"][0])
    max_w    = float(dataset["common_w"][-1])
    all_rows = dataset["region_summary"]

    base_fig = build_base_figure(dataset, debug_hover=debug_hover)

    app = Dash(__name__, suppress_callback_exceptions=True)
    app.title = f"ASAP — {dataset['suffix']}"

    cache.init_app(app.server)

    app.layout = build_layout(dataset, base_fig, debug_hover=debug_hover)

    # ── Clientside callback: sync ll-entries to drag_handles.js ──────────────
    #
    # BUG FIX: The previous version did `if (window.updateLLEntries) { ... }`
    # and silently dropped the data if drag_handles.js had not loaded yet.
    # Since ll-entries-store only changes again on Save, llEntries stayed
    # empty forever after the initial page load.
    #
    # Fix: always write to window.__llEntriesData (a plain global that exists
    # regardless of script load order).  drag_handles.js reads this cache
    # inside its own init() after it defines window.updateLLEntries.
    app.clientside_callback(
        """
        function(llEntries) {
            var entries = llEntries || [];

            // Always cache — drag_handles.js reads this on init() if it
            // loads after this callback fires.
            window.__llEntriesData = entries;

            // If drag_handles.js is already loaded, call it immediately.
            if (window.updateLLEntries) {
                window.updateLLEntries(entries);
            }
            return window.dash_clientside
                ? window.dash_clientside.no_update
                : null;
        }
        """,
        Output("handles-sync-store", "data"),
        Input("ll-entries-store", "data"),
    )

    # ── Clientside callback: discard reset ───────────────────────────────────
    # When the user clicks Discard, the Python callback emits the saved
    # ll-entries data via discard-signal-store.  This JS callback:
    #   1. Resets window.llEntries mirror to the saved positions
    #   2. Calls window.resetShapesToEntries() which calls Plotly.relayout()
    #      to move all shape edges back to their saved coordinates.
    # This is necessary because Plotly.relayout() during drag is browser-only —
    # the server never sees those position changes, so its Patch() only updates
    # colours, not coordinates.
    app.clientside_callback(
        """
        function(discardSignal) {
            if (!discardSignal || !discardSignal.entries) {
                return window.dash_clientside
                    ? window.dash_clientside.no_update : null;
            }
            var entries = discardSignal.entries;
            window.__llEntriesData = entries;
            if (window.updateLLEntries)      window.updateLLEntries(entries);
            if (window.resetShapesToEntries) window.resetShapesToEntries(entries);
            return window.dash_clientside
                ? window.dash_clientside.no_update : null;
        }
        """,
        Output("handles-sync-store", "data", allow_duplicate=True),
        Input("discard-signal-store", "data"),
        prevent_initial_call=True,
    )


    app.clientside_callback(
        """
        function(hoverData, llStatsStore) {
            if (window.dash_clientside && window.dash_clientside.show_region_tooltip) {
                return window.dash_clientside.show_region_tooltip(hoverData, llStatsStore);
            }
            return window.dash_clientside ? window.dash_clientside.no_update : null;
        }
        """,
        Output("tooltip-sync-store", "data"),
        Input("spectrum-graph", "hoverData"),
        State("ll-stats-store", "data"),
    )

    app.clientside_callback(
        """
        function(hoverSync) {
            if (window.updateHoveredRegion) {
                window.updateHoveredRegion(hoverSync || {region_idx: null});
            }
            return window.dash_clientside ? window.dash_clientside.no_update : null;
        }
        """,
        Output("handles-hover-sync-store", "data"),
        Input("tooltip-sync-store", "data"),
    )

    register_all_callbacks(app, dataset, min_w, max_w, all_rows, debug_hover=debug_hover)

    return app


# ══════════════════════════════════════════════════════════════════════════════
# Entry Point
# ══════════════════════════════════════════════════════════════════════════════

def main() -> None:
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="ASAP Line Curation Dashboard",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python -m wave_explorer --suffix ds_leo
  python -m wave_explorer --suffix ds_leo --host 0.0.0.0 --port 8050 --debug
  python -m wave_explorer --suffix ds_leo --line-list /path/to/custom_ll.txt
        """
    )
    parser.add_argument("--suffix",         required=True)
    parser.add_argument("--retrievals-dir", default=None)
    parser.add_argument("--line-list",      default=None)
    parser.add_argument("--grid-step",      type=float, default=0.01)
    parser.add_argument("--smooth-window",  type=int,   default=1)
    parser.add_argument("--host",           default="127.0.0.1")
    parser.add_argument("--port",           type=int,   default=8050)
    parser.add_argument("--debug",          action="store_true")
    parser.add_argument("--debug-hover",    action="store_true")
    args = parser.parse_args()

    if args.retrievals_dir is None:
        cwd = Path.cwd()
        if (cwd / "06_retrievals").exists():
            args.retrievals_dir = str(cwd / "06_retrievals")
        else:
            candidate = cwd.parent / "obs-data-example" / "06_retrievals"
            args.retrievals_dir = str(candidate if candidate.exists()
                                       else cwd / "06_retrievals")

    print("━" * 70)
    print("  ASAP Line Curation Dashboard")
    print("━" * 70)
    print(f"  Suffix         : {args.suffix}")
    print(f"  Retrievals dir : {args.retrievals_dir}")

    dataset = build_dataset(
        retrievals_dir = Path(args.retrievals_dir).resolve(),
        suffix         = args.suffix,
        line_list_path = args.line_list,
        grid_step_nm   = args.grid_step,
        smooth_window  = args.smooth_window,
    )

    print(f"  Stars          : {dataset['n_stars']}")
    print(f"  λ range        : {dataset['common_w'][0]:.2f} – {dataset['common_w'][-1]:.2f} nm")
    print(f"  Line list      : {dataset['line_list']}")
    print(f"  LL regions     : {len(dataset['ll_entries'])} (total), "
          f"{len(dataset['region_summary'])} (with χ²)")
    print("━" * 70)
    print(f"  → http://{args.host}:{args.port}")
    print("━" * 70)

    app = create_app(dataset, debug_hover=args.debug_hover)
    app.run(host=args.host, port=args.port, debug=args.debug)


if __name__ == "__main__":
    main()