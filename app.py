"""
ASAP Line Curation Dashboard — App Factory & Entry Point
"""

import argparse
from pathlib import Path

from flask_caching import Cache
from dash import Dash, Input, Output

from .callbacks import register_all_callbacks
from .data_processing import build_dataset
from .layout import build_layout


# ══════════════════════════════════════════════════════════════════════════════
# Caching configuration
# ══════════════════════════════════════════════════════════════════════════════

cache = Cache(config={"CACHE_TYPE": "SimpleCache"})


def create_app(dataset: dict, debug_hover: bool = False) -> Dash:
    """Factory function to create the Dash app with all callbacks."""

    min_w = float(dataset["common_w"][0])
    max_w = float(dataset["common_w"][-1])
    all_rows = dataset["region_summary"]

    app = Dash(__name__, suppress_callback_exceptions=True)
    app.title = f"ASAP — {dataset['suffix']}"

    cache.init_app(app.server)

    app.layout = build_layout(dataset, debug_hover=debug_hover)

    # ── Clientside: feed the SVG spectrum component ──────────────────────────
    # One callback pushes static data + live region state into spectrum.js.
    # If spectrum.js has not initialised yet, the args are cached on window
    # and replayed by its init().
    app.clientside_callback(
        """
        function(specData, llEntries, pending, selected, drawActive, goto) {
            var args = [specData, llEntries, pending, selected, drawActive,
                        goto];
            window.__weSpectrumPending = args;
            if (window.WaveExplorer && window.WaveExplorer.sync) {
                window.WaveExplorer.sync.apply(null, args);
            }
            return window.dash_clientside
                ? window.dash_clientside.no_update : null;
        }
        """,
        Output("handles-sync-store", "data"),
        Input("spectrum-data-store", "data"),
        Input("ll-entries-store", "data"),
        Input("pending-changes-store", "data"),
        Input("selected-region-store", "data"),
        Input("draw-mode-active-store", "data"),
        Input("goto-region-store", "data"),
    )

    register_all_callbacks(
        app, dataset, min_w, max_w, all_rows, debug_hover=debug_hover
    )

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
        """,
    )
    parser.add_argument("--suffix", required=True)
    parser.add_argument("--retrievals-dir", default=None)
    parser.add_argument("--line-list", default=None)
    parser.add_argument("--grid-step", type=float, default=0.01)
    parser.add_argument("--smooth-window", type=int, default=1)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8050)
    parser.add_argument("--debug", action="store_true")
    parser.add_argument("--debug-hover", action="store_true")
    args = parser.parse_args()

    if args.retrievals_dir is None:
        cwd = Path.cwd()
        if (cwd / "06_retrievals").exists():
            args.retrievals_dir = str(cwd / "06_retrievals")
        else:
            candidate = cwd.parent / "obs-data-example" / "06_retrievals"
            args.retrievals_dir = str(
                candidate if candidate.exists() else cwd / "06_retrievals"
            )

    print("━" * 70)
    print("  ASAP Line Curation Dashboard")
    print("━" * 70)
    print(f"  Suffix         : {args.suffix}")
    print(f"  Retrievals dir : {args.retrievals_dir}")

    dataset = build_dataset(
        retrievals_dir=Path(args.retrievals_dir).resolve(),
        suffix=args.suffix,
        line_list_path=args.line_list,
        grid_step_nm=args.grid_step,
        smooth_window=args.smooth_window,
    )

    print(f"  Stars          : {dataset['n_stars']}")
    print(
        f"  λ range        : {dataset['common_w'][0]:.2f} – {dataset['common_w'][-1]:.2f} nm"
    )
    print(f"  Line list      : {dataset['line_list']}")
    print(
        f"  LL regions     : {len(dataset['ll_entries'])} (total), "
        f"{len(dataset['region_summary'])} (with χ²)"
    )
    print("━" * 70)
    print(f"  → http://{args.host}:{args.port}")
    print("━" * 70)

    app = create_app(dataset, debug_hover=args.debug_hover)
    app.run(host=args.host, port=args.port, debug=args.debug)


if __name__ == "__main__":
    main()
