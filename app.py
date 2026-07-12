"""
ASAP Line Curation Dashboard — App Factory & Entry Point
"""

import argparse
import difflib
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


def discover_suffixes(retrievals_dir: Path) -> dict:
    """Map each available output suffix to the number of stars that have it.

    Output folders follow ``<star>/output_<star>_<suffix>``, so the suffix is
    the folder name with the ``output_<star>_`` prefix stripped.
    """
    counts: dict = {}
    for star_dir in sorted(retrievals_dir.glob("*")):
        if not star_dir.is_dir():
            continue
        prefix = f"output_{star_dir.name}_"
        for p in star_dir.glob("output_*"):
            if p.is_dir() and p.name.startswith(prefix) and p.name != prefix:
                sfx = p.name[len(prefix) :]
                counts[sfx] = counts.get(sfx, 0) + 1
    return counts


def _format_suffix_table(counts: dict, limit: int = 0) -> str:
    """Render available suffixes sorted by star count (desc), then name."""
    rows = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    if limit:
        rows = rows[:limit]
    width = max((len(s) for s, _ in rows), default=0)
    return "\n".join(
        f"    {sfx:<{width}}  ({n} star{'s' if n != 1 else ''})" for sfx, n in rows
    )


def parse_output_folder(folder: Path) -> "tuple[dict, Path, str]":
    """Derive dataset inputs from a single output folder path.

    Returns (only_folders, retrievals_dir, suffix) for a folder laid out as
    ``<retrievals_dir>/<star>/output_<star>_<suffix>``. The suffix falls back
    to the folder name (minus any ``output_`` prefix) when the name does not
    embed the star slug — it is then only used for display.
    """
    folder = folder.resolve()
    slug = folder.parent.name
    name = folder.name
    prefix = f"output_{slug}_"
    if name.startswith(prefix):
        suffix = name[len(prefix) :]
    elif name.startswith("output_"):
        suffix = name[len("output_") :]
    else:
        suffix = name
    return {slug: folder}, folder.parent.parent, suffix


def _resolve_retrievals_dir(arg: "str | None") -> Path:
    """Resolve the retrievals dir: explicit flag, ./06_retrievals, or the
    sibling obs-data-example/06_retrievals. Exits with guidance if none exist."""
    if arg is not None:
        path = Path(arg)
        if not path.is_dir():
            sys.exit(
                f"error: retrievals dir not found: {path}\n"
                "       (it should contain one folder per star, each with "
                "output_<star>_<suffix> subfolders)"
            )
        return path

    cwd = Path.cwd()
    for candidate in (cwd / "06_retrievals", cwd.parent / "obs-data-example" / "06_retrievals"):
        if candidate.is_dir():
            return candidate
    sys.exit(
        "error: no retrievals dir found.\n"
        f"       Looked for {cwd / '06_retrievals'}\n"
        f"       and       {cwd.parent / 'obs-data-example' / '06_retrievals'}.\n"
        "       Run from the campaign directory (e.g. new/obs-data-example/) "
        "or pass --retrievals-dir."
    )


def main() -> None:
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        prog="python -m wave_explorer",
        description=(
            "ASAP Line Curation Dashboard — explore a retrieval campaign's "
            "observed vs model spectra and curate the line list interactively."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""\
Which SUFFIX? Every star folder holds runs named output_<star>_<suffix>;
SUFFIX picks which run of each star to load. Run with --list-suffixes
(or just with no suffix) to see what is available.

Examples:
  # See what campaigns exist, then launch one
  python -m wave_explorer --list-suffixes
  python -m wave_explorer bic_optimal_region_filtering_v1

  # Explore a single run: pass one output folder instead of a suffix
  python -m wave_explorer 06_retrievals/ds_leo/output_ds_leo_bic_optimal_region_filtering_v1

  # Pin the line list explicitly (skips auto-detection)
  python -m wave_explorer bic_optimal_region_filtering_v1 \\
      --line-list line_lists/targets_llist_v5.txt

  # Serve on the network / another port
  python -m wave_explorer bic_optimal_region_filtering_v1 --host 0.0.0.0 --port 8051

  # Teff-stack mode: 8 stars spanning the Teff range, offset vertically
  python -m wave_explorer bic_optimal_region_filtering_v1 --stack-teff 8 --stack-offset 0.6

Tip: on this cluster use the asap env's python directly
(/net/vdesk/data2/cobelens/.conda/envs/asap/bin/python); `conda activate`
leaves the base python shadowing the env.
""",
    )

    data = parser.add_argument_group("data selection")
    data.add_argument(
        "suffix",
        nargs="?",
        default=None,
        metavar="SUFFIX",
        help="Retrieval-run suffix to load (folders output_<star>_<SUFFIX>), "
        "OR a path to one output_* folder to load just that single run. "
        "Omit it to get a list of available suffixes.",
    )
    data.add_argument(
        "--suffix",
        dest="suffix_flag",
        default=None,
        metavar="SUFFIX",
        help="Same as the positional SUFFIX (kept for backwards compatibility).",
    )
    data.add_argument(
        "--list-suffixes",
        action="store_true",
        help="List every available suffix (with star counts) and exit.",
    )
    data.add_argument(
        "--retrievals-dir",
        default=None,
        metavar="DIR",
        help="Campaign folder containing one directory per star. Default: "
        "./06_retrievals, else ../obs-data-example/06_retrievals.",
    )
    data.add_argument(
        "--line-list",
        default=None,
        metavar="FILE",
        help="Line list to curate. Default: auto-detected from the runs' "
        "config_copy.ini (majority vote; errors on a tie — pass this "
        "flag to break it).",
    )
    data.add_argument(
        "--vald-list",
        default=None,
        metavar="FILE",
        help="VALD3 short-format line list for the absorption-feature overlay. "
        "Default: the bundled DionCobelens.017597 (700–1000 nm).",
    )

    display = parser.add_argument_group("display")
    display.add_argument(
        "--grid-step",
        type=float,
        default=0.01,
        metavar="NM",
        help="Common wavelength grid step in nm (default: 0.01).",
    )
    display.add_argument(
        "--smooth-window",
        type=int,
        default=1,
        metavar="N",
        help="Boxcar-smooth the displayed mean spectra over N grid points "
        "(default: 1 = off).",
    )
    display.add_argument(
        "--stack-teff",
        nargs="?",
        const=10,
        type=int,
        default=None,
        metavar="N",
        help="Teff-stack mode: instead of the campaign mean, show N stars "
        "(default: 10) spanning the retrieved Teff range, stacked with "
        "vertical offsets.",
    )
    display.add_argument(
        "--stack-offset",
        type=float,
        default=0.5,
        metavar="FLUX",
        help="Vertical offset between consecutive stacked stars in "
        "normalized-flux units (default: 0.5; stack mode only).",
    )

    server = parser.add_argument_group("server")
    server.add_argument(
        "--host",
        default="127.0.0.1",
        help="Interface to bind (default: 127.0.0.1; use 0.0.0.0 to serve "
        "on the network).",
    )
    server.add_argument(
        "--port", type=int, default=8050, help="Port to serve on (default: 8050)."
    )

    debug = parser.add_argument_group("debugging")
    debug.add_argument(
        "--debug",
        action="store_true",
        help="Run Dash in debug mode (hot reload + in-page tracebacks).",
    )
    debug.add_argument(
        "--debug-hover",
        action="store_true",
        help="Show the hover/crosshair debug readout in the app.",
    )
    args = parser.parse_args()

    if args.suffix and args.suffix_flag and args.suffix != args.suffix_flag:
        parser.error(
            f"conflicting suffixes: positional '{args.suffix}' vs "
            f"--suffix '{args.suffix_flag}' — pass only one"
        )
    args.suffix = args.suffix or args.suffix_flag

    # ── Single-output-folder mode ─────────────────────────────────────────────
    # A SUFFIX that is an existing directory is treated as a direct path to
    # one output_* folder: load exactly that run (one star).
    only_folders = None
    if args.suffix is not None and Path(args.suffix).is_dir():
        folder = Path(args.suffix).resolve()
        if not (folder / "fit-data.fits").exists():
            sys.exit(
                f"error: {folder}\n"
                "       is a directory but does not look like an ASAP output "
                "folder (no fit-data.fits).\n"
                "       Pass either a campaign suffix or the path of one "
                "output_<star>_<suffix> folder."
            )
        if args.stack_teff:
            parser.error(
                "--stack-teff needs a campaign suffix (many stars), "
                "not a single output folder"
            )
        only_folders, retrievals_dir, args.suffix = parse_output_folder(folder)
        print(f"Single-run mode: {folder}")
    else:
        retrievals_dir = _resolve_retrievals_dir(args.retrievals_dir)

        if args.list_suffixes or args.suffix is None:
            counts = discover_suffixes(retrievals_dir)
            if not counts:
                sys.exit(
                    f"error: no output_<star>_<suffix> folders found under "
                    f"{retrievals_dir}"
                )
            print(f"Available suffixes in {retrievals_dir}:")
            print(_format_suffix_table(counts))
            if args.list_suffixes:
                sys.exit(0)
            if len(counts) == 1:
                args.suffix = next(iter(counts))
                print(f"\nOnly one suffix available — using '{args.suffix}'.")
            else:
                top = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[0][0]
                sys.exit(
                    "\nPick one and re-run, e.g.:\n"
                    f"  python -m wave_explorer {top}"
                )

        # Fail fast with guidance if the suffix matches nothing, instead of
        # letting the dataset build die on an empty star set.
        from .data_processing import discover_output_folders

        if not discover_output_folders(retrievals_dir, args.suffix):
            counts = discover_suffixes(retrievals_dir)
            close = difflib.get_close_matches(args.suffix, counts, n=3, cutoff=0.4)
            msg = (
                f"error: no star has an output folder matching suffix "
                f"'{args.suffix}'."
            )
            if close:
                msg += "\n       Did you mean:\n" + _format_suffix_table(
                    {s: counts[s] for s in close}
                )
            msg += "\n       (--list-suffixes shows everything available)"
            sys.exit(msg)

    args.retrievals_dir = str(retrievals_dir)

    if args.vald_list is None:
        bundled = Path(__file__).resolve().parent / "data" / "DionCobelens.017597"
        if bundled.exists():
            args.vald_list = str(bundled)

    print("━" * 70)
    print("  ASAP Line Curation Dashboard")
    print("━" * 70)
    print(f"  Suffix         : {args.suffix}")
    if only_folders:
        for slug, folder in only_folders.items():
            print(f"  Single run     : {slug}  ({folder})")
    else:
        print(f"  Retrievals dir : {args.retrievals_dir}")
        print("  Loading fit-data for every star … (this can take a moment)")

    try:
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
                only_folders=only_folders,
            )
    except RuntimeError as exc:
        # Dataset builders raise RuntimeError with actionable messages
        # (line-list tie, missing files, empty star set) — no traceback needed.
        sys.exit(f"error: {exc}")

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
    try:
        app.run(host=args.host, port=args.port, debug=args.debug)
    except OSError as exc:
        if "in use" in str(exc).lower():
            sys.exit(
                f"error: port {args.port} is already in use "
                f"(another wave_explorer running?) — try --port {args.port + 1}"
            )
        raise


if __name__ == "__main__":
    main()
