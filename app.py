"""
ASAP Line Curation Dashboard — App Factory & Entry Point
"""

import argparse
from pathlib import Path

from flask_caching import Cache
from dash import Dash, Input, Output, State, html

from .callbacks import register_all_callbacks
from .data_processing import build_dataset
from .figure_builder import build_base_figure
from .layout import build_layout
from .theme import C, MONO, SANS


# ══════════════════════════════════════════════════════════════════════════════
# Caching configuration
# ══════════════════════════════════════════════════════════════════════════════

cache = Cache(config={"CACHE_TYPE": "SimpleCache"})


def create_app(dataset: dict, debug_hover: bool = False) -> Dash:
    """Factory function to create the Dash app with all callbacks."""
    
    # Compute min/max wavelengths and row data
    min_w  = float(dataset["common_w"][0])
    max_w  = float(dataset["common_w"][-1])
    all_rows = dataset["region_summary"]

    # Build base figure once; reused across all callbacks
    base_fig = build_base_figure(dataset, debug_hover=debug_hover)

    # Instantiate Dash app
    app = Dash(__name__, suppress_callback_exceptions=True)
    app.title = f"ASAP — {dataset['suffix']}"

    # Bind cache to app
    cache.init_app(app.server)

    # Build and set layout
    app.layout = build_layout(dataset, base_fig, debug_hover=debug_hover)

    # Wire JS-only interactions via Dash clientside callbacks.
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
        function(llEntries) {
            var entries = llEntries || [];
            // Expose globally so drag_handles.js can fall back to this
            // if its own llEntries array hasn't been populated yet.
            window.__asapLLEntries = entries;
            if (window.updateLLEntries) {
                window.updateLLEntries(entries);
            }
            return window.dash_clientside ? window.dash_clientside.no_update : null;
        }
        """,
        Output("handles-sync-store", "data"),
        Input("ll-entries-store", "data"),
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

    # Register all callbacks
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
    parser.add_argument("--suffix",        required=True,
                       help="Retrieval suffix (e.g. 'ds_leo')")
    parser.add_argument("--retrievals-dir", default=None,
                       help="Retrievals directory (default: inferred from working directory)")
    parser.add_argument("--line-list",     default=None,
                       help="Explicit line list path")
    parser.add_argument("--grid-step",     type=float, default=0.01,
                       help="Grid step in nm (default: 0.01)")
    parser.add_argument("--smooth-window", type=int,   default=1,
                       help="Smoothing window size (default: 1, no smoothing)")
    parser.add_argument("--host",          default="127.0.0.1",
                       help="Bind host (default: 127.0.0.1)")
    parser.add_argument("--port",          type=int,   default=8050,
                       help="Bind port (default: 8050)")
    parser.add_argument("--debug",         action="store_true",
                       help="Dash debug mode")
    parser.add_argument("--debug-hover",   action="store_true",
                       help="Show hover hitboxes + event diagnostics")
    args = parser.parse_args()

    # Infer retrievals dir if not provided
    if args.retrievals_dir is None:
        # Assume we're running from obs-data-example/ or a sibling folder
        cwd = Path.cwd()
        if (cwd / "06_retrievals").exists():
            args.retrievals_dir = str(cwd / "06_retrievals")
        else:
            # Try parent / obs-data-example / 06_retrievals
            candidate = cwd.parent / "obs-data-example" / "06_retrievals"
            if candidate.exists():
                args.retrievals_dir = str(candidate)
            else:
                args.retrievals_dir = str(cwd / "06_retrievals")

    print("━" * 70)
    print("  ASAP Line Curation Dashboard")
    print("━" * 70)
    print(f"  Suffix         : {args.suffix}")
    print(f"  Retrievals dir : {args.retrievals_dir}")

    # Load dataset (cached on subsequent calls)
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

    # Create and run app
    app = create_app(dataset, debug_hover=args.debug_hover)
    app.run(host=args.host, port=args.port, debug=args.debug)


if __name__ == "__main__":
    main()
