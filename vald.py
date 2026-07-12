"""VALD3 short-format line-list parser.

VALD download files (Vienna Atomic Line Database, http://vald.astro.uu.se/)
in short format have a 3-line header followed by one data row per line.
Each data row is comma-separated and looks like:

    'Spec Ion',  WL_vac(nm), Excit(eV), Vmic, log gf, Rad., Stark,
                 Waals, Lande factor, Central depth, 'Reference...'

Where `'Spec Ion'` is the element symbol + ionisation stage (1 = neutral,
2 = singly ionised, ...) in single quotes — e.g. `'Fe 1'`, `'TiO 1'`,
`'Ca 2'`. Wavelengths are vacuum.

This module reads the file and returns a list of plain Python dicts —
no astropy dependency, no numpy.
"""

from pathlib import Path
from typing import List, Optional, Sequence, Tuple


def parse_vald_lines(path) -> List[dict]:
    """Parse a VALD3 short-format file and return per-transition dicts.

    Skips the standard 3-line header. Silently ignores any subsequent row
    that does not have at least 9 numeric fields after the quoted species
    label (these include trailing reference blocks and stray blank lines).
    The returned list is sorted by wavelength.
    """
    entries: List[dict] = []
    with open(Path(path)) as fh:
        for idx, raw in enumerate(fh):
            if idx < 3:
                continue
            row = _parse_row(raw)
            if row is not None:
                entries.append(row)
    entries.sort(key=lambda e: e["wavelength_nm"])
    return entries


def _parse_row(raw: str):
    s = raw.strip()
    if not s or not s.startswith("'"):
        return None
    species_end = s.find("'", 1)
    if species_end <= 1:
        return None
    species = s[1:species_end].strip()
    rest = s[species_end + 1:].lstrip(", ").strip()
    if not rest:
        return None
    # Drop the trailing reference (also quoted), if present.
    ref_start = rest.find("'")
    if ref_start >= 0:
        rest = rest[:ref_start]
    # Split WITHOUT dropping empty fields: an empty field mid-row must not
    # shift later columns onto the wrong positional index. Only the trailing
    # empties left by the comma before the (stripped) reference are removed.
    parts = [p.strip() for p in rest.split(",")]
    while parts and parts[-1] == "":
        parts.pop()
    # VALD short format: 9 numeric fields after the species label
    # (WL_vac, Excit, Vmic, log gf, Rad., Stark, Waals, Lande, Central depth)
    if len(parts) < 9:
        return None
    try:
        numeric = [float(p) for p in parts[:9]]
    except ValueError:
        return None  # empty or non-numeric field → reject the row
    wavelength_nm = numeric[0]
    excit_ev = numeric[1]
    log_gf = numeric[3]
    central_depth = numeric[8]
    element, _, ion_str = species.partition(" ")
    try:
        ion = int(ion_str.strip() or "1")
    except ValueError:
        ion = 1
    return {
        "element": element,
        "ion": ion,
        "wavelength_nm": wavelength_nm,
        "excit_ev": excit_ev,
        "log_gf": log_gf,
        "central_depth": central_depth,
    }


def build_vald_payload(
    entries: List[dict],
    lambda_min: float,
    lambda_max: float,
    observed_ranges: Optional[Sequence[Tuple[float, float]]] = None,
) -> dict:
    """Build the JSON-serializable payload for the vald-lines-store.

    Filters entries to the [lambda_min, lambda_max] window and emits parallel
    arrays (wavelengths, elements, ions, depths, logGf, excitEv) keyed by
    index. Parallel arrays keep the payload compact and let the JS renderer
    do per-index lookups during a tight render loop without object churn.

    When `observed_ranges` is provided as a list of (lo, hi) tuples, entries
    outside every observed span are dropped — this hides VALD lines in the
    inter-order gaps that the spectrum interpolator linearly bridges.

    Also returns the [depthMin, depthMax] range so the UI can configure the
    depth slider.
    """
    def _in_observed(w: float) -> bool:
        if not observed_ranges:
            return True
        for lo, hi in observed_ranges:
            if lo <= w <= hi:
                return True
        return False

    in_range = [
        e for e in entries
        if lambda_min <= e["wavelength_nm"] <= lambda_max
        and _in_observed(e["wavelength_nm"])
    ]
    in_range.sort(key=lambda e: e["wavelength_nm"])
    depths = [float(e["central_depth"]) for e in in_range]
    return {
        "count": len(in_range),
        "wavelengths": [float(e["wavelength_nm"]) for e in in_range],
        "elements":    [str(e["element"]) for e in in_range],
        "ions":        [int(e["ion"]) for e in in_range],
        "depths":      depths,
        "logGf":       [float(e["log_gf"]) for e in in_range],
        "excitEv":     [float(e["excit_ev"]) for e in in_range],
        "depthMin": min(depths) if depths else 0.0,
        "depthMax": max(depths) if depths else 0.0,
    }
