"""CLI for the full-range model driver.

    python -m wave_explorer.full_model <output_folder> [--cache-dir DIR]
                                       [--grid-path PATH] [--force]

Writes ``model-full.fits`` into the output folder (or ``--cache-dir`` keyed by
the star folder name). Skips recompute when a valid cache already exists, unless
``--force`` is given. Validity is mtime-based against ``results.txt``.
"""
import argparse
from pathlib import Path

from .driver import compute_full_model


def is_cache_valid(cache_path, results_path) -> bool:
    cache_path, results_path = Path(cache_path), Path(results_path)
    if not cache_path.exists() or not results_path.exists():
        return False
    return cache_path.stat().st_mtime >= results_path.stat().st_mtime


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="python -m wave_explorer.full_model")
    p.add_argument("output_folder")
    p.add_argument("--cache-dir", default=None)
    p.add_argument("--grid-path", default=None)
    p.add_argument("--force", action="store_true")
    a = p.parse_args(argv)

    out_folder = Path(a.output_folder)
    if a.cache_dir:
        out_path = Path(a.cache_dir) / f"{out_folder.parent.name}_model-full.fits"
    else:
        out_path = out_folder / "model-full.fits"

    if not a.force and is_cache_valid(out_path, out_folder / "results.txt"):
        print(f"cache hit: {out_path}")
        return 0

    compute_full_model(out_folder, out_path=out_path,
                       grid_path_override=a.grid_path)
    print(f"wrote {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
