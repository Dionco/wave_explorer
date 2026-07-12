from pathlib import Path
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
