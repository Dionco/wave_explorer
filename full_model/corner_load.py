"""Build a temp grid dir that symlinks ONLY the bracketing corner files.

Per the spike: instead of hand-writing an h5py reader, point ASAP's own
``load_grid`` at a temp directory containing only the bracketing corner files.
ASAP's oldstyle loader then reads just those and builds ``grid_n``/``nwvls`` in
the correct dimension order itself, and clamps its teff/logg/mh/alpha axes to the
two bracketing nodes present in the dir.

``sel.files`` holds the node dicts for every (teff,logg,mh,alpha) atmo-corner;
we symlink every B-component file that shares those atmo coordinates (up to
8 corners x 11 B = 88 files for gl_382), never the full grid.
"""
import os
from pathlib import Path


def make_corner_grid_dir(path_to_grid: str, sel, tmp_root) -> str:
    from .grid_corners import parse_grid_filename, is_node_filename
    atmo = {(n["teff"], n["logg"], n["mh"], n["alpha"]) for n in sel.files}
    # Resolve to an ABSOLUTE source dir: symlink targets are stored verbatim,
    # so a relative --grid-path would otherwise be resolved from the tmp dir
    # and every link would dangle.
    src = Path(path_to_grid).resolve()
    # Node enumeration deliberately stays a plain listdir + is_node_filename
    # scan (NOT grid.info-aware like enumerate_nodes): the corner dir holds a
    # node SUBSET and gets no grid.info of its own, so ASAP's loader listdirs
    # it anyway; copying/honouring a grid.info here (which lists files absent
    # from the corner dir) is not obviously correct. None of the local grids
    # ship a grid.info, so the scans agree in practice.
    dst = Path(tmp_root) / "corner_grid"
    dst.mkdir(parents=True, exist_ok=True)
    for fn in os.listdir(src):
        if not is_node_filename(fn):
            continue
        v = parse_grid_filename(fn)
        if (v["teff"], v["logg"], v["mh"], v["alpha"]) in atmo:
            link = dst / fn
            if not link.exists():
                link.symlink_to(src / fn)
    return str(dst) + "/"
