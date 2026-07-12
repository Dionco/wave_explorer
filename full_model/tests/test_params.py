from pathlib import Path

import pytest

from wave_explorer.full_model.params import load_run_inputs

REF = Path("/net/vdesk/data2/cobelens/MRP/new/obs-data-example/"
           "06_retrievals/gl_382/output_gl_382_v2")


def test_load_run_inputs_reads_paths_and_params():
    ri = load_run_inputs(REF)
    assert ri.path_to_grid.endswith("/")
    assert ri.obs_fits.endswith(".fits")
    assert ri.line_list.endswith(".txt")
    # best-fit atmospheric params present and physical
    assert 2500 < ri.teff < 5000
    assert 3.0 < ri.logg < 6.0
    assert -1.0 < ri.mh < 1.0
    assert len(ri.mag_ff) >= 1           # magnetic filling factors array


_RESULT_LINES = {
    "teff": "flt : teff : 3600 50",
    "logg": "flt : logg : 4.70 0.05",
    "mh": "flt : mh : 0.10 0.05",
    "afe": "flt : afe : 0.00 0.00",
    "rv": "flt : rv : 0.10 0.01",
    "vsini": "flt : vsini : 2.00 0.10",
    "vmac": "flt : vmac : 0.00 0.00",
    "mag_ff": "arr : mag_ff : 0.5 0.3 0.2",
}


def _write_run_folder(tmp_path, omit):
    (tmp_path / "config_copy.ini").write_text(
        "[PATHS]\n"
        "pathToGrid = /nonexistent-grid\n"
        "pathToData = /nonexistent-data\n"
        "lineListFile = lines.txt\n"
    )
    lines = [v for k, v in _RESULT_LINES.items() if k != omit]
    (tmp_path / "results.txt").write_text("\n".join(lines) + "\n")


@pytest.mark.parametrize("key", ["rv", "vsini", "vmac", "mag_ff"])
def test_missing_result_key_raises_value_error(tmp_path, key):
    # F11: no silent defaults — a missing rv/vsini/vmac/mag_ff must fail
    # loudly (a defaulted mag_ff=[1.0] would silently yield a zero-field
    # model), naming the missing key.
    _write_run_folder(tmp_path, omit=key)
    with pytest.raises(ValueError, match=key):
        load_run_inputs(tmp_path)
