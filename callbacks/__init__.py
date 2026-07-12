"""
Central callback orchestrator
"""

from .candidate import register_candidate_callbacks
from .regions import register_region_callbacks
from .star_focus import register_star_focus_callbacks
from .table import register_table_callbacks


def register_all_callbacks(app, dataset, min_w, max_w, all_rows, debug_hover=False):
    """Register all callbacks for the app.

    `all_rows` and `debug_hover` are kept in the signature for the app.py
    call site even though the registrars below no longer consume them.
    """
    register_candidate_callbacks(app, dataset, min_w, max_w)
    register_region_callbacks(app, dataset, min_w, max_w)
    register_table_callbacks(app, dataset, min_w, max_w)
    register_star_focus_callbacks(app, dataset)
