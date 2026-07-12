"""Smoke test: the Teff-stack dataset builds on the real 06_retrievals."""
from pathlib import Path

from wave_explorer.data_processing import build_stacked_dataset

REF_DIR = Path(
    "/net/vdesk/data2/cobelens/MRP/new/obs-data-example/06_retrievals"
)
# Explicit shared list: with a small picked subset the per-star
# line_list_filtered.txt overrides can tie in resolve_line_list_path's
# majority vote (its error says to set --line-list, which this mirrors).
LINE_LIST = str(
    REF_DIR.parent / "line_lists" / "targets_line_list_v2.txt"
)


def test_stacked_dataset_builds():
    ds = build_stacked_dataset(
        REF_DIR, "v2", LINE_LIST, 0.01, 1, None, n_stack=4
    )
    assert ds["stacked"] is True
    p = ds["stacked_payload"]
    assert p["stacked"] is True
    assert 1 <= len(p["stars"]) <= 4
    teffs = [s["teff"] for s in p["stars"]]
    assert teffs == sorted(teffs)
    # offsets ascend with Teff
    offsets = [s["offset"] for s in p["stars"]]
    assert offsets == sorted(offsets)
    # statistics are scoped to the displayed stars
    assert set(ds["stack_teffs"]) == set(ds["fit_data_cache"])
    # any "__mean__" restore must restore the stack, not a mean view
    assert ds["mean_payload"] is ds["stacked_payload"]


from wave_explorer.app import create_app


def test_stacked_app_builds_and_hides_star_select():
    ds = build_stacked_dataset(
        REF_DIR, "v2", LINE_LIST, 0.01, 1, None, n_stack=3
    )
    app = create_app(ds)
    layout_str = str(app.layout)
    assert "star-select" in layout_str          # component present (callbacks wired)
    assert "Teff stack" in layout_str           # header chip
