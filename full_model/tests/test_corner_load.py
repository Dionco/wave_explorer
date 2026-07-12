from pathlib import Path
from wave_explorer.full_model.params import load_run_inputs
from wave_explorer.full_model.grid_corners import enumerate_nodes, select_corners
from wave_explorer.full_model.corner_load import make_corner_grid_dir

REF = Path("/net/vdesk/data2/cobelens/MRP/new/obs-data-example/"
           "06_retrievals/gl_382/output_gl_382_v2")
GRID = "/net/vdesk/data2/cobelens/MRP/new/grid_models/hdf5-narval-full/"


def test_make_corner_grid_dir_symlinks_only_corners(tmp_path):
    ri = load_run_inputs(REF, grid_path_override=GRID)
    nodes = enumerate_nodes(ri.path_to_grid)
    sel = select_corners(nodes, ri.teff, ri.logg, ri.mh, ri.afe)
    d = make_corner_grid_dir(ri.path_to_grid, sel, tmp_path)
    links = list(Path(d).glob("*.hdf5"))
    # 8 atmo-corners (2x2x2x1) x 11 B-components = up to 88 files; never the full 1651
    assert 0 < len(links) <= 88
    assert all(p.is_symlink() for p in links)
    # each symlink resolves to a real grid file
    assert all(p.resolve().exists() for p in links)
