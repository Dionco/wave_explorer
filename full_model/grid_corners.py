"""Enumerate grid HDF5 nodes and select the bracketing best-fit corners.

Grid files are named like ``2900g3.5z0.00a0.00b0000p0.0rot90.00beta0.00.hdf5``
encoding ``teff g logg z mh a alpha b bmono(Gauss) p... rot... beta...``. This
narval grid has NO ``grid.info``, so ``enumerate_nodes`` lists ``*.hdf5``.
"""
import os
import re
from dataclasses import dataclass

# A node filename starts with the integer teff then 'g' then the logg, e.g.
# "2900g3.5z-0.25a0.00b1000p0.0rot90.00beta0.00.hdf5". The shared wavelength
# file "wave.hdf5" (used by ASAP's loader) and any other non-conforming file
# must be skipped during enumeration.
_NODE_RE = re.compile(r"^\d+g[-\d.]+z[-\d.]+a[-\d.]+b\d+p")


def is_node_filename(fname: str) -> bool:
    return fname.endswith(".hdf5") and bool(_NODE_RE.match(fname))


def parse_grid_filename(fname: str) -> dict:
    def between(s, a, b):
        return s.split(a)[1].split(b)[0]
    return {
        "teff": float(fname.split("g")[0]),
        "logg": float(between(fname, "g", "z")),
        "mh": float(between(fname, "z", "a")),
        "alpha": float(between(fname, "a", "b")),
        "bmono_G": float(between(fname, "b", "p")),
        "file": fname,
    }


def enumerate_nodes(path_to_grid: str) -> list:
    info = os.path.join(path_to_grid, "grid.info")
    if os.path.isfile(info):
        files, reading = [], False
        with open(info) as f:
            for line in f:
                s = line.strip()
                if not s:
                    continue
                if s == "listFiles":
                    reading = True
                    continue
                if reading:
                    files.append(s)
    else:
        files = os.listdir(path_to_grid)
    return [parse_grid_filename(f) for f in files if is_node_filename(f)]


def _bracket(values, x):
    uniq = sorted(set(values))
    if len(uniq) == 1:
        return [uniq[0]]
    below = [v for v in uniq if v <= x]
    above = [v for v in uniq if v >= x]
    lo = max(below) if below else uniq[0]      # clamp to nearest if out of range
    hi = min(above) if above else uniq[-1]
    return sorted({lo, hi})


@dataclass
class CornerSelection:
    teff_nodes: list
    logg_nodes: list
    mh_nodes: list
    alpha_nodes: list
    files: list      # node dicts whose (teff,logg,mh,alpha) is in the selected axes


def select_corners(nodes, teff, logg, mh, alpha) -> CornerSelection:
    tN = _bracket([n["teff"] for n in nodes], teff)
    lN = _bracket([n["logg"] for n in nodes], logg)
    mN = _bracket([n["mh"] for n in nodes], mh)
    aN = _bracket([n["alpha"] for n in nodes], alpha)
    sel = [n for n in nodes
           if n["teff"] in tN and n["logg"] in lN
           and n["mh"] in mN and n["alpha"] in aN]
    return CornerSelection(tN, lN, mN, aN, sel)
