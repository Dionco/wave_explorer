"""
ASAP Line Curation Dashboard — App Factory & Entry Point
"""

import argparse
import sys
from pathlib import Path

from dash import Dash, Input, Output

from .callbacks import register_all_callbacks
from .data_processing import build_dataset
from .layout import build_layout


def create_app(dataset: dict, debug_hover: bool = False) -> Dash:
    """Factory function to create the Dash app with all callbacks."""

    if not len(dataset.get("common_w", [])):
        raise RuntimeError(
            "Dataset error: common wavelength grid is empty — no overlapping "
            "spectral coverage was found across the loaded stars."
        )

    min_w = float(dataset["common_w"][0])
    max_w = float(dataset["common_w"][-1])
    all_rows = dataset["region_summary"]

    app = Dash(__name__, suppress_callback_exceptions=True)
    app.title = f"ASAP — {dataset['suffix']}"

    app.layout = build_layout(dataset, debug_hover=debug_hover)

    # ── Clientside: feed the SVG spectrum component ──────────────────────────
    # One callback pushes static data + live region state into spectrum.js.
    # If spectrum.js has not initialised yet, the args are cached on window
    # and replayed by its init().
    app.clientside_callback(
        """
        function(specData, llEntries, pending, selected, drawActive, goto,
                vald, valdVisible, valdDepthMin) {
            var args = [specData, llEntries, pending, selected, drawActive,
                        goto, vald, valdVisible, valdDepthMin];
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
        Input("vald-lines-store", "data"),
        Input("vald-visible-store", "data"),
        Input("vald-depth-min-store", "data"),
    )

    app.clientside_callback(
        """
        function(n) {
            if (!n) return false;
            return n % 2 === 1;
        }
        """,
        Output("vald-visible-store", "data"),
        Input("vald-toggle-btn", "n_clicks"),
    )

    app.clientside_callback(
        """
        function(v) { return v; }
        """,
        Output("vald-depth-min-store", "data"),
        Input("vald-depth-min-slider", "value"),
    )

    # ── Full-range model compute spinner ─────────────────────────────────────
    # The server-side star-focus callback runs the driver subprocess
    # synchronously, so it cannot push an intermediate "computing" status. To
    # still show activity, this clientside callback fires the moment a real star
    # is selected (star-select changed → spinner active) and hides the spinner
    # once the server callback resolves (full-model-status-store updated).
    app.clientside_callback(
        """
        function(starValue, status) {
            var ctx = window.dash_clientside
                ? window.dash_clientside.callback_context : null;
            var trigger = (ctx && ctx.triggered && ctx.triggered.length)
                ? ctx.triggered[0].prop_id : "";
            if (trigger.indexOf("star-select") === 0) {
                // A real star was picked → show the spinner while the driver runs.
                return (starValue && starValue !== "__mean__")
                    ? "spinner-active" : "spinner-hidden";
            }
            // The server star-focus callback resolves only when the compute is
            // DONE (it never emits "computing"), so any status update means
            // hide. The status value is slug-tagged so it changes on every
            // focus and reliably re-fires this callback.
            return "spinner-hidden";
        }
        """,
        Output("full-model-spinner", "className"),
        Input("star-select", "value"),
        Input("full-model-status-store", "data"),
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
  python -m wave_explorer --suffix ds_leo --stack-teff
  python -m wave_explorer --suffix ds_leo --stack-teff 8 --stack-offset 0.6
        """,
    )
    parser.add_argument("--suffix", required=True)
    parser.add_argument("--retrievals-dir", default=None)
    parser.add_argument("--line-list", default=None)
    parser.add_argument(
        "--vald-list",
        default=None,
        help="VALD3 short-format line list for the absorption-feature overlay. "
        "Defaults to the bundled DionCobelens.017597 (700–1000 nm).",
    )
    parser.add_argument("--grid-step", type=float, default=0.01)
    parser.add_argument("--smooth-window", type=int, default=1)
    parser.add_argument(
        "--stack-teff",
        nargs="?",
        const=10,
        type=int,
        default=None,
        metavar="N",
        help="Teff-stack mode: pick N stars (default 10) spanning the "
        "retrieved Teff range and show them stacked with vertical "
        "offsets instead of averaged.",
    )
    parser.add_argument(
        "--stack-offset",
        type=float,
        default=0.5,
        help="Vertical offset between consecutive stars in "
        "normalized-flux units (stack mode only).",
    )
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

    if not Path(args.retrievals_dir).is_dir():
        sys.exit(f"retrievals dir not found: {args.retrievals_dir}")

    if args.vald_list is None:
        bundled = Path(__file__).resolve().parent / "data" / "DionCobelens.017597"
        if bundled.exists():
            args.vald_list = str(bundled)

    print("━" * 70)
    print("  ASAP Line Curation Dashboard")
    print("━" * 70)
    print(f"  Suffix         : {args.suffix}")
    print(f"  Retrievals dir : {args.retrievals_dir}")

    if args.stack_teff:
        from .data_processing import build_stacked_dataset

        dataset = build_stacked_dataset(
            retrievals_dir=Path(args.retrievals_dir).resolve(),
            suffix=args.suffix,
            line_list_path=args.line_list,
            grid_step_nm=args.grid_step,
            smooth_window=args.smooth_window,
            vald_path=args.vald_list,
            n_stack=args.stack_teff,
            offset_step=args.stack_offset,
        )
    else:
        dataset = build_dataset(
            retrievals_dir=Path(args.retrievals_dir).resolve(),
            suffix=args.suffix,
            line_list_path=args.line_list,
            grid_step_nm=args.grid_step,
            smooth_window=args.smooth_window,
            vald_path=args.vald_list,
        )

    print(f"  Stars          : {dataset['n_stars']}")
    if dataset.get("stacked"):
        print(f"  Mode           : Teff stack ({len(dataset['stack_teffs'])} stars)")
        for s in dataset["stacked_payload"]["stars"]:
            print(f"    {s['slug']:<16s} Teff = {s['teff']:7.1f} K")
    print(
        f"  λ range        : {dataset['common_w'][0]:.2f} – {dataset['common_w'][-1]:.2f} nm"
    )
    print(f"  Line list      : {dataset['line_list']}")
    print(
        f"  LL regions     : {len(dataset['ll_entries'])} (total), "
        f"{len(dataset['region_summary'])} (with χ²)"
    )
    print(
        f"  VALD lines     : {len(dataset.get('vald_entries', []))}"
        f"  ({dataset.get('vald_path') or 'none'})"
    )
    print("━" * 70)
    print(f"  → http://{args.host}:{args.port}")
    print("━" * 70)

    app = create_app(dataset, debug_hover=args.debug_hover)
    app.run(host=args.host, port=args.port, debug=args.debug)


if __name__ == "__main__":
    main()
