"""
ASAP Line Curation Theme & Styling
"""

import numpy as np

# ══════════════════════════════════════════════════════════════════════════════
# Color palette (warm editorial — Claude Design handoff)
#
# Keys are kept stable so figure_builder.py / layout.py / callbacks keep
# working; only the values changed from the old observatory-dark theme.
# ══════════════════════════════════════════════════════════════════════════════

C = {
    # Surfaces — warm parchment family
    "bg": "#f8f5ec",        # paper-soft  (inset / sunk surfaces)
    "surf": "#fdfcf7",      # paper       (card surface)
    "surf2": "#efe9d8",     # surface-soft
    "border": "#d8cfb4",    # hairline
    "border2": "#e6dfcb",   # hairline-soft
    # Ink
    "text": "#1a1814",
    "muted": "#75705f",
    "dim": "#9c9684",
    # Accent (terracotta-rust) — replaces the old cyan key
    "cyan": "#b3553b",
    "cyan_bg": "#efd9c8",
    # Quality ramp
    "amber": "#b88829",     # fair
    "amber_bg": "#f0e2bd",
    "green": "#4f7a4d",     # good
    "green_bg": "#d8e2c8",
    "red": "#9c3d2e",       # bad
    "red_bg": "#ecccc1",
    "orange": "#c87338",    # poor
    # Plot lines
    "obs": "#4a4639",       # observation — warm ink-grey
    "fit": "#b3553b",       # model fit — terracotta accent
    "resid": "#4a4639",     # residual — warm ink-grey
    # Region spans
    "ll_fill": "rgba(79, 122, 77, 0.14)",
    "ll_line": "rgba(79, 122, 77, 0.55)",
    "cand_fill": "rgba(179, 85, 59, 0.16)",
    "cand_line": "rgba(179, 85, 59, 0.90)",
    # Canvas (page background, for legacy references)
    "canvas": "#f4efe2",
}

MONO = "'JetBrains Mono', 'IBM Plex Mono', 'Courier New', monospace"
SANS = "'Inter', -apple-system, 'Segoe UI', system-ui, sans-serif"
DISPLAY = "'Fraunces', 'Source Serif Pro', Georgia, serif"


# ══════════════════════════════════════════════════════════════════════════════
# Color & label coding
# ══════════════════════════════════════════════════════════════════════════════


# χ²/N quality thresholds:
#   GOOD  : v < 5
#   FAIR  : 5 ≤ v < 15
#   POOR  : 15 ≤ v < 30
#   BAD   : v ≥ 30
_CHI2_GOOD = 5.0
_CHI2_FAIR = 15.0
_CHI2_POOR = 15.0
_CHI2_BAD = 30.0


def chi2_color(v: float) -> str:
    """Return color for chi2 value."""
    if not np.isfinite(v):
        return C["muted"]
    if v < _CHI2_GOOD:
        return C["green"]
    if v < _CHI2_FAIR:
        return C["amber"]
    if v < _CHI2_BAD:
        return C["orange"]
    return C["red"]


def chi2_label(v: float) -> str:
    """Return quality label for chi2 value."""
    if not np.isfinite(v):
        return "—"
    if v < _CHI2_GOOD:
        return "GOOD"
    if v < _CHI2_FAIR:
        return "FAIR"
    if v < _CHI2_BAD:
        return "POOR"
    return "BAD"


def chi2_pct(v: float, cap: float = _CHI2_BAD) -> int:
    """Return progress-bar fill percentage (0–100)."""
    if not np.isfinite(v):
        return 0
    return min(100, int(v / cap * 100))


# ══════════════════════════════════════════════════════════════════════════════
# Format helpers
# ══════════════════════════════════════════════════════════════════════════════


def _fmt(v: float, fmt: str = ".4f", fallback: str = "—") -> str:
    """Format a float value; return fallback if not finite."""
    return fallback if not np.isfinite(v) else f"{v:{fmt}}"
