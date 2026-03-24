"""
Central callback orchestrator
"""

from .candidate import register_candidate_callbacks
from .regions import register_region_callbacks
from .session import register_session_callbacks
from .table import register_table_callbacks


def register_all_callbacks(app, dataset, min_w, max_w, all_rows, debug_hover=False):
    """Register all callbacks for the app."""
    register_candidate_callbacks(
        app, dataset, min_w, max_w, all_rows, debug_hover=debug_hover
    )
    register_region_callbacks(app, dataset, min_w, max_w)
    register_session_callbacks(app, dataset)
    register_table_callbacks(app, dataset)
