"""Teff-stack mode — star selection.

Picks N stars spanning the retrieved Teff range for the stacked
comparison view. Reads Teff from each star's ``results.txt`` (no FITS
loading), dedupes duplicate-named star dirs (``gl_15a`` vs ``gl15a``),
and spreads the picks evenly in Teff.
"""
import math
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple

_TEFF_RE = re.compile(r"^flt\s*:\s*teff\s*:\s*(\S+)")


def parse_results_teff(results_path) -> Optional[float]:
    """Teff from an ASAP ``results.txt`` (``flt : teff : <val> <err>`` line)."""
    try:
        text = Path(results_path).read_text()
    except OSError:
        return None
    for line in text.splitlines():
        m = _TEFF_RE.match(line.strip())
        if m:
            try:
                val = float(m.group(1))
            except ValueError:
                return None
            return val if math.isfinite(val) else None
    return None


def dedup_star_folders(
    found: Dict[str, Path],
) -> Tuple[Dict[str, Path], List[str]]:
    """Collapse duplicate-named star dirs (``gl_15a`` vs ``gl15a``).

    Slugs are duplicates when they match after removing underscores
    (case-insensitive). Among duplicates the folder whose ``results.txt``
    has the newest mtime wins. Returns ``(kept, dropped_slugs)``.
    """
    groups: Dict[str, List[str]] = {}
    for slug in found:
        groups.setdefault(slug.replace("_", "").lower(), []).append(slug)

    def _mtime(slug: str) -> float:
        try:
            return (found[slug] / "results.txt").stat().st_mtime
        except OSError:
            return float("-inf")

    kept: Dict[str, Path] = {}
    dropped: List[str] = []
    for slugs in groups.values():
        slugs = sorted(slugs, key=_mtime, reverse=True)
        kept[slugs[0]] = found[slugs[0]]
        dropped.extend(slugs[1:])
    return {s: kept[s] for s in sorted(kept)}, sorted(dropped)


def pick_even_teff(candidates: List[dict], n: int) -> List[dict]:
    """Pick up to ``n`` candidates spread evenly in Teff.

    ``candidates`` are dicts with at least ``slug`` and ``teff``. The
    coolest and hottest stars are always included; the remaining picks
    greedily take the unused star nearest each evenly spaced target
    temperature. Returns the picks sorted by Teff ascending.
    """
    cands = sorted(candidates, key=lambda c: c["teff"])
    if n <= 0 or not cands:
        return []
    if n >= len(cands):
        return cands
    if n == 1:
        return [cands[0]]

    tmin, tmax = cands[0]["teff"], cands[-1]["teff"]
    targets = [tmin + (tmax - tmin) * i / (n - 1) for i in range(n)]
    used = [False] * len(cands)
    picked_idx: List[int] = []
    # Endpoints first so an inner target can never steal them.
    for ti in [0, n - 1] + list(range(1, n - 1)):
        best, best_d = None, float("inf")
        for j, c in enumerate(cands):
            if used[j]:
                continue
            d = abs(c["teff"] - targets[ti])
            if d < best_d:
                best, best_d = j, d
        used[best] = True
        picked_idx.append(best)
    return [cands[j] for j in sorted(picked_idx)]


def select_stack_stars(found: Dict[str, Path], n: int) -> dict:
    """Resolve the stack-mode star picks from discovered output folders.

    ``found`` is ``discover_output_folders`` output (slug -> output dir).
    Returns ``{"picked", "candidates", "warnings"}``: ``picked`` is the
    even-Teff selection (slug/teff/folder dicts, Teff ascending);
    ``candidates`` is every deduped star with a usable Teff (kept for
    load-failure substitution); ``warnings`` are printable strings.
    """
    warnings: List[str] = []
    kept, dropped = dedup_star_folders(found)
    if dropped:
        warnings.append(
            "duplicate star dirs dropped: " + ", ".join(dropped)
        )
    candidates: List[dict] = []
    for slug, folder in kept.items():
        teff = parse_results_teff(folder / "results.txt")
        if teff is None:
            warnings.append(f"no Teff in {slug}/results.txt — skipped")
            continue
        candidates.append({"slug": slug, "teff": teff, "folder": folder})
    if len(candidates) < n:
        warnings.append(
            f"only {len(candidates)} usable stars (< {n}) — using all"
        )
    picked = pick_even_teff(candidates, n)
    return {"picked": picked, "candidates": candidates, "warnings": warnings}
