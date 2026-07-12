"""Smoke test: the Dash app object builds with the star selector wired in.

Builds the real dataset on the ``06_retrievals`` v2 retrievals and constructs
the app, asserting the new dataset keys and the star dropdown are present. This
exercises the duplicate-output star-focus callback registration without starting
a server.
"""
from pathlib import Path

from wave_explorer.app import create_app
from wave_explorer.data_processing import build_dataset

REF_DIR = Path(
    "/net/vdesk/data2/cobelens/MRP/new/obs-data-example/06_retrievals"
)
# Explicit shared list: later campaigns rewrote per-star config.ini files, so
# auto-detection ties between line lists and raises "no clear majority".
LINE_LIST = str(
    REF_DIR.parent / "line_lists" / "targets_line_list_v2.txt"
)


def test_app_builds_with_star_selector():
    ds = build_dataset(REF_DIR, "v2", LINE_LIST, 0.01, 1, None)
    assert "output_folders" in ds and "mean_payload" in ds
    app = create_app(ds)
    # the star dropdown is in the layout
    assert "star-select" in str(app.layout)
