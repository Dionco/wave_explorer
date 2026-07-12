"""Parse a retrieval run's config + results into typed inputs for the driver.

Reads ``config_copy.ini`` (preferring it over the parent ``config.ini``) for the
grid/obs/line-list paths and ASAP's ``read_res_v2`` for the best-fit parameters
in ``results.txt``.

The config's ``pathToGrid`` can be STALE (the gl_382 example points at a removed
``asap_v0.1_example`` path). ``load_run_inputs`` therefore resolves the grid path
as: explicit override > config value if it is a real directory > the known full
narval grid fallback.
"""
import sys
import configparser
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, "/net/vdesk/data2/cobelens/MRP/new/asap")
from asap.SpectralAnalysis import read_res_v2   # noqa: E402

DEFAULT_GRID = "/net/vdesk/data2/cobelens/MRP/new/grid_models/hdf5-narval-full/"


@dataclass
class RunInputs:
    output_folder: Path
    config_path: Path
    path_to_grid: str
    obs_fits: str
    line_list: str
    star: str
    teff: float
    logg: float
    mh: float
    afe: float
    rv: float
    vsini: float
    vmac: float
    mag_ff: list      # magnetic filling factors (= gen_spec `coeffs`)
    veiling: list


def _config_path(output_folder: Path) -> Path:
    local = output_folder / "config_copy.ini"
    if local.exists():
        return local
    parent_cfg = output_folder.parent / "config.ini"
    if parent_cfg.exists():
        return parent_cfg
    raise FileNotFoundError(
        f"No config_copy.ini or parent config.ini for {output_folder}")


def load_run_inputs(output_folder, grid_path_override=None) -> RunInputs:
    output_folder = Path(output_folder)
    cfg_path = _config_path(output_folder)
    cfg = configparser.ConfigParser()
    cfg.read(cfg_path)
    paths = cfg["PATHS"]

    cfg_grid = paths["pathToGrid"]
    if grid_path_override:
        path_to_grid = grid_path_override
    elif Path(cfg_grid).is_dir():
        path_to_grid = cfg_grid
    else:
        path_to_grid = DEFAULT_GRID
    if not path_to_grid.endswith("/"):
        path_to_grid += "/"

    path_to_data = paths["pathToData"]
    line_list = paths["lineListFile"]

    res = read_res_v2(str(output_folder / "results.txt"))
    star = str(res.get("star", output_folder.parent.name))
    obs_fits = path_to_data.rstrip("/") + "/" + star + ".fits"

    return RunInputs(
        output_folder=output_folder, config_path=cfg_path,
        path_to_grid=path_to_grid, obs_fits=obs_fits, line_list=line_list,
        star=star,
        teff=float(res["teff"]), logg=float(res["logg"]),
        mh=float(res["mh"]), afe=float(res["afe"]),
        rv=float(res.get("rv", 0.0)),
        vsini=float(res.get("vsini", 0.0)),
        vmac=float(res.get("vmac", 0.0)),
        mag_ff=list(res.get("mag_ff", [1.0])),
        veiling=list(res.get("veiling", [])),
    )
