"""Star-focus callback: switch the spectrum to a single star's full-range model.

Picking a star in the ``star-select`` dropdown:
  * ``__mean__`` → restore the cached mean-view payload (status ``idle``).
  * a star slug → ensure ``model-full.fits`` exists in that star's output folder
    (computing it via the driver subprocess if missing/stale), then load it and
    push a single-star full-range payload into ``spectrum-data-store``
    (status ``ready``; ``error`` if the driver fails).

The driver runs as a SUBPROCESS so ASAP + the model grid stay out of the Dash
process. We resolve the interpreter once at registration time: prefer the app's
own ``sys.executable`` when it can import ASAP (the app runs in the ``asap``
env); otherwise fall back to ``conda run -n asap`` so the subprocess always has
ASAP + h5py + astropy regardless of the app's env.
"""
import subprocess
import sys
from pathlib import Path

from dash import Input, Output, no_update

from wave_explorer.data_processing import (
    build_single_star_payload,
    build_single_star_vald_payload,
    load_full_model,
)
from wave_explorer.full_model.__main__ import is_cache_valid

# Generous timeout: a cold compute reads the grid + runs gen_spec twice over the
# full orders (~minute). Cache hits return almost immediately.
_DRIVER_TIMEOUT_S = 600


def _resolve_driver_cmd_prefix():
    """Return the argv prefix that runs the driver with ASAP available.

    Prefer the app's own interpreter when it can import ASAP; otherwise use
    ``conda run -n asap python`` so the subprocess always has the asap env.
    """
    probe = (
        "import sys; "
        "sys.path.insert(0, '/net/vdesk/data2/cobelens/MRP/new/asap'); "
        "import asap"
    )
    try:
        r = subprocess.run(
            [sys.executable, "-c", probe],
            capture_output=True,
            text=True,
            timeout=120,
        )
        if r.returncode == 0:
            return [sys.executable]
    except Exception:
        pass
    return ["conda", "run", "-n", "asap", "python"]


def _run_driver(folder, driver_prefix):
    """Default subprocess runner: compute ``model-full.fits`` for ``folder``.

    Returns True on success (driver exit 0 and the cache now exists), else
    False. Swallows timeout/launch errors as a failure so callers can map
    them to the ``error`` status.
    """
    cmd = driver_prefix + ["-m", "wave_explorer.full_model", str(folder)]
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, timeout=_DRIVER_TIMEOUT_S
        )
    except Exception:
        return False
    return proc.returncode == 0 and (Path(folder) / "model-full.fits").exists()


def focus_star_payload(dataset, slug, run_driver):
    """Resolve a star selection to a (payload_or_no_update, status) pair.

    Pure aside from the injected ``run_driver(folder) -> bool`` (which the
    Dash callback wires to the real subprocess and tests stub). Mirrors the
    callback's behaviour exactly:

      * ``__mean__``/empty → (mean_payload, "idle"); never runs the driver.
      * known slug with a valid cache → loads it (driver NOT called) → "ready".
      * stale/missing cache → runs the driver; on success loads → "ready".
      * unknown slug, driver failure, or load failure → (no_update, "error").
    """
    folders = dataset.get("output_folders", {})  # slug -> Path
    mean_payload = dataset.get("mean_payload")

    if not slug or slug == "__mean__":
        return mean_payload, "idle"

    folder = folders.get(slug)
    if folder is None:
        return no_update, "error"
    folder = Path(folder)
    cache = folder / "model-full.fits"
    results = folder / "results.txt"

    if not is_cache_valid(cache, results):
        if not run_driver(folder):
            return no_update, "error"

    try:
        fd = load_full_model(folder)
        payload = build_single_star_payload(fd, dataset)
    except Exception:
        return no_update, "error"
    return payload, "ready"


def register_star_focus_callbacks(app, dataset):
    driver_prefix = _resolve_driver_cmd_prefix()

    def run_driver(folder):
        return _run_driver(folder, driver_prefix)

    @app.callback(
        Output("spectrum-data-store", "data", allow_duplicate=True),
        Output("full-model-status-store", "data"),
        Output("vald-lines-store", "data"),
        Input("star-select", "value"),
        prevent_initial_call=True,
    )
    def on_star_change(slug):
        payload, status = focus_star_payload(dataset, slug, run_driver)

        # Refresh the VALD overlay so it matches what's displayed: the mean view
        # keeps its window-scoped payload; a focused single star gets a payload
        # spanning its full observed range (lines outside the fitted windows
        # included). On error, leave the existing overlay untouched.
        if not slug or slug == "__mean__":
            vald = dataset.get("vald_payload", no_update)
        elif status == "ready":
            vald = build_single_star_vald_payload(
                payload, dataset.get("vald_entries", [])
            )
        else:
            vald = no_update

        # Tag the status with the slug so the store value changes on EVERY
        # focus. Otherwise two consecutive "ready" results are identical, Dash
        # fires no change event, and the clientside spinner-hide callback never
        # re-runs — leaving the spinner spinning after the model has loaded.
        return payload, f"{status}:{slug}", vald
