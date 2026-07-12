"""CLI helper tests: suffix discovery, formatting, single-folder mode."""

from pathlib import Path

from wave_explorer.app import (
    _format_suffix_table,
    discover_suffixes,
    parse_output_folder,
)


def _make_campaign(tmp_path: Path) -> Path:
    """Two stars sharing suffix 'v1'; one star with an extra 'special_v2' run."""
    for star, suffixes in {
        "star_a": ["v1", "special_v2"],
        "star_b": ["v1"],
    }.items():
        for sfx in suffixes:
            (tmp_path / star / f"output_{star}_{sfx}").mkdir(parents=True)
    # Distractors: a loose file, a non-output dir, and an output dir whose
    # name does not embed this star's slug (foreign copy — not enumerable).
    (tmp_path / "notes.txt").write_text("not a star dir")
    (tmp_path / "star_a" / "plots").mkdir()
    (tmp_path / "star_b" / "output_star_a_v9").mkdir()
    return tmp_path


def test_discover_suffixes_counts_stars_per_suffix(tmp_path):
    counts = discover_suffixes(_make_campaign(tmp_path))
    assert counts == {"v1": 2, "special_v2": 1}


def test_discover_suffixes_empty_dir(tmp_path):
    assert discover_suffixes(tmp_path) == {}


def test_format_suffix_table_sorts_by_count_then_name():
    table = _format_suffix_table({"bbb": 2, "aaa": 2, "ccc": 5})
    lines = [ln.split()[0] for ln in table.splitlines()]
    assert lines == ["ccc", "aaa", "bbb"]
    assert "(5 stars)" in table and "(2 stars)" in table


def test_format_suffix_table_limit_and_singular():
    table = _format_suffix_table({"only": 1, "other": 3}, limit=1)
    assert table.splitlines() == [f"    {'other':<5}  (3 stars)"]
    assert "(1 star)" in _format_suffix_table({"only": 1})


def test_parse_output_folder_standard_layout(tmp_path):
    folder = tmp_path / "06_retrievals" / "ds_leo" / "output_ds_leo_bic_v1"
    folder.mkdir(parents=True)
    only_folders, retrievals_dir, suffix = parse_output_folder(folder)
    assert only_folders == {"ds_leo": folder.resolve()}
    assert retrievals_dir == (tmp_path / "06_retrievals").resolve()
    assert suffix == "bic_v1"


def test_parse_output_folder_foreign_name_falls_back(tmp_path):
    # Folder name embeds a different slug than its parent dir (a copied run):
    # the suffix falls back to everything after "output_".
    folder = tmp_path / "06_retrievals" / "star_b" / "output_star_a_v9"
    folder.mkdir(parents=True)
    only_folders, _, suffix = parse_output_folder(folder)
    assert only_folders == {"star_b": folder.resolve()}
    assert suffix == "star_a_v9"


def test_parse_output_folder_no_output_prefix(tmp_path):
    folder = tmp_path / "06_retrievals" / "ds_leo" / "my_special_run"
    folder.mkdir(parents=True)
    _, _, suffix = parse_output_folder(folder)
    assert suffix == "my_special_run"
