from wave_explorer.full_model.grid_corners import parse_grid_filename, select_corners


def test_parse_grid_filename():
    v = parse_grid_filename("2900g3.5z-0.25a0.00b1000p0.0rot90.00beta0.00.hdf5")
    assert v["teff"] == 2900.0
    assert v["logg"] == 3.5
    assert v["mh"] == -0.25
    assert v["alpha"] == 0.0
    assert v["bmono_G"] == 1000.0


def test_select_corners_brackets_and_dedups():
    nodes = [
        {"teff": 3500.0, "logg": 4.5, "mh": 0.0, "alpha": 0.0, "bmono_G": 0.0, "file": "a"},
        {"teff": 3600.0, "logg": 4.5, "mh": 0.0, "alpha": 0.0, "bmono_G": 0.0, "file": "b"},
        {"teff": 3500.0, "logg": 4.75, "mh": 0.0, "alpha": 0.0, "bmono_G": 0.0, "file": "c"},
        {"teff": 3600.0, "logg": 4.75, "mh": 0.0, "alpha": 0.0, "bmono_G": 0.0, "file": "d"},
    ]
    sel = select_corners(nodes, teff=3528.0, logg=4.66, mh=0.0, alpha=0.0)
    # axes degenerate to single nodes where only one value exists (mh, alpha)
    assert sel.teff_nodes == [3500.0, 3600.0]
    assert sel.logg_nodes == [4.5, 4.75]
    assert sel.mh_nodes == [0.0]
    assert sel.alpha_nodes == [0.0]
    # one file per (teff,logg,mh,alpha) combination that exists
    assert len(sel.files) == 4
