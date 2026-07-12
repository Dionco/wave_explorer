"""Unit tests for stack_select — Teff-stack star selection."""
from pathlib import Path

from wave_explorer.stack_select import parse_results_teff

RESULTS_BODY = """\
#################################################
str :             datetime : 2026-04-21 18h37m00s
str :                 star : ds_leo
#------------------------------------------------
flt :                 teff : 3801.9458    4.3807
flt :                 logg : 4.7789       0.0348
#################################################
"""


def test_parses_teff_value(tmp_path):
    p = tmp_path / "results.txt"
    p.write_text(RESULTS_BODY)
    assert parse_results_teff(p) == 3801.9458


def test_missing_file_returns_none(tmp_path):
    assert parse_results_teff(tmp_path / "absent.txt") is None


def test_no_teff_line_returns_none(tmp_path):
    p = tmp_path / "results.txt"
    p.write_text("flt :                 logg : 4.7789       0.0348\n")
    assert parse_results_teff(p) is None


import os
import time

from wave_explorer.stack_select import dedup_star_folders


def _mk_star(tmp_path, slug, mtime_offset=0):
    d = tmp_path / slug / "output_x_v1"
    d.mkdir(parents=True)
    r = d / "results.txt"
    r.write_text(RESULTS_BODY)
    t = time.time() + mtime_offset
    os.utime(r, (t, t))
    return d


def test_dedup_keeps_newest_results(tmp_path):
    old = _mk_star(tmp_path, "gl_15a", mtime_offset=-100)
    new = _mk_star(tmp_path, "gl15a", mtime_offset=0)
    kept, dropped = dedup_star_folders({"gl_15a": old, "gl15a": new})
    assert kept == {"gl15a": new}
    assert dropped == ["gl_15a"]


def test_dedup_passes_unique_slugs_through(tmp_path):
    a = _mk_star(tmp_path, "ds_leo")
    b = _mk_star(tmp_path, "ev_lac")
    kept, dropped = dedup_star_folders({"ds_leo": a, "ev_lac": b})
    assert kept == {"ds_leo": a, "ev_lac": b}
    assert dropped == []


from wave_explorer.stack_select import pick_even_teff


def _cands(teffs):
    return [{"slug": f"s{i}", "teff": t} for i, t in enumerate(teffs)]


def test_pick_includes_endpoints_and_is_sorted():
    teffs = [3000, 3050, 3100, 3400, 3500, 3550, 3600, 3900, 3950, 4000,
             4001, 4002]
    picked = pick_even_teff(_cands(teffs), 10)
    pt = [p["teff"] for p in picked]
    assert len(picked) == 10
    assert pt[0] == 3000 and pt[-1] == 4002      # endpoints always in
    assert pt == sorted(pt)                       # Teff ascending
    assert len(set(p["slug"] for p in picked)) == 10  # no duplicates


def test_pick_fewer_candidates_returns_all():
    picked = pick_even_teff(_cands([3000, 3500, 4000]), 10)
    assert [p["teff"] for p in picked] == [3000, 3500, 4000]


def test_pick_spreads_over_clustered_sample():
    # 20 cool stars clustered at 3000-3100 plus one hot outlier: the hot
    # star must be picked, and the picks must not all sit in the cluster.
    teffs = [3000 + 5 * i for i in range(20)] + [4500]
    picked = pick_even_teff(_cands(teffs), 5)
    pt = [p["teff"] for p in picked]
    assert len(picked) == 5
    assert len(set(p["slug"] for p in picked)) == 5
    assert 4500 in pt
    assert pt[0] == 3000


from wave_explorer.stack_select import select_stack_stars


def _mk_star_teff(tmp_path, slug, teff):
    d = tmp_path / slug / "output_x_v1"
    d.mkdir(parents=True)
    (d / "results.txt").write_text(
        f"flt :                 teff : {teff:.4f}    4.0000\n"
    )
    return d


def test_select_picks_and_warns(tmp_path):
    found = {}
    for i, t in enumerate([3000, 3200, 3400, 3600, 3800]):
        slug = f"star_{i}"
        found[slug] = _mk_star_teff(tmp_path, slug, t)
    # one star without a usable Teff
    bad = tmp_path / "bad_star" / "output_x_v1"
    bad.mkdir(parents=True)
    (bad / "results.txt").write_text("no teff here\n")
    found["bad_star"] = bad

    sel = select_stack_stars(found, 3)
    assert [p["teff"] for p in sel["picked"]] == [3000.0, 3400.0, 3800.0]
    assert len(sel["candidates"]) == 5
    assert any("bad_star" in w for w in sel["warnings"])


def test_select_fewer_than_n_uses_all(tmp_path):
    found = {
        "a": _mk_star_teff(tmp_path, "a", 3000),
        "b": _mk_star_teff(tmp_path, "b", 4000),
    }
    sel = select_stack_stars(found, 10)
    assert len(sel["picked"]) == 2
    assert any("using all" in w for w in sel["warnings"])


def test_pick_zero_or_negative_n_returns_empty():
    assert pick_even_teff(_cands([3000, 3500]), 0) == []
    assert pick_even_teff(_cands([3000, 3500]), -3) == []
    assert pick_even_teff([], 5) == []


def test_parse_rejects_non_finite_teff(tmp_path):
    p = tmp_path / "results.txt"
    p.write_text("flt :                 teff : nan          4.0000\n")
    assert parse_results_teff(p) is None
