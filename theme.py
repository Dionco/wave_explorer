"""
ASAP Line Curation Theme & Styling
"""

import numpy as np

# ══════════════════════════════════════════════════════════════════════════════
# Color palette (observatory dark)
# ══════════════════════════════════════════════════════════════════════════════

C = {
    "bg": "#0d1117",
    "surf": "#161b22",
    "surf2": "#1c2333",
    "border": "#30363d",
    "border2": "#21262d",
    "text": "#e6edf3",
    "muted": "#7d8590",
    "dim": "#484f58",
    "cyan": "#58d1eb",
    "cyan_bg": "#0a2e38",
    "amber": "#ffa726",
    "amber_bg": "#2e1d00",
    "green": "#3fb950",
    "green_bg": "#0b2110",
    "red": "#f85149",
    "red_bg": "#2e0d0b",
    "orange": "#fb8f44",
    "obs": "#d0dae7",
    "fit": "#58d1eb",
    "resid": "#ffa726",
    "ll_fill": "rgba(62, 173, 90, 0.18)",
    "ll_line": "rgba(40, 150, 70, 0.80)",
    "cand_fill": "rgba(255, 167, 38, 0.20)",
    "cand_line": "rgba(245, 130, 10, 0.95)",
}

MONO = "'Space Mono', 'JetBrains Mono', 'Courier New', monospace"
SANS = "'DM Sans', 'Segoe UI', system-ui, sans-serif"


# ══════════════════════════════════════════════════════════════════════════════
# Color & label coding
# ══════════════════════════════════════════════════════════════════════════════


def chi2_color(v: float) -> str:
    """Return color for chi2 value."""
    if not np.isfinite(v):
        return C["muted"]
    if v < 1.5:
        return C["green"]
    if v < 3.0:
        return C["amber"]
    if v < 6.0:
        return C["orange"]
    return C["red"]


def chi2_label(v: float) -> str:
    """Return quality label for chi2 value."""
    if not np.isfinite(v):
        return "—"
    if v < 1.5:
        return "GOOD"
    if v < 3.0:
        return "FAIR"
    if v < 6.0:
        return "POOR"
    return "BAD"


def chi2_pct(v: float, cap: float = 10.0) -> int:
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
