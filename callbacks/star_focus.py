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
env); then the explicit asap env interpreter (``_ASAP_ENV_PYTHON``) when it
exists and passes the import probe (``conda`` is not on PATH on this cluster
without a module load); otherwise fall back to ``conda run -n asap`` as a last
resort. The ASAP checkout used by the import probe can be overridden via the
``WAVE_EXPLORER_ASAP_PATH`` environment variable.

KNOWN LIMITATION (synchronous compute): a cold compute holds a Dash worker
for up to ``_DRIVER_TIMEOUT_S`` (600 s) because the callback runs the driver
subprocess synchronously — other requests are only served by the remaining
workers meanwhile. The clean fix is Dash *background callbacks*
(``background=True`` with a ``DiskcacheManager``), which need the ``diskcache``
package (or celery) as a backend; ``diskcache`` is NOT installed in the asap
env, so this stays a synchronous callback for now. Upgrade path: install
``diskcache`` in the env, create ``dash.DiskcacheManager(diskcache.Cache(...))``
in ``app.py``, pass it as ``background_callback_manager``, and mark this
callback ``background=True``. A per-folder in-process lock (below) at least
guarantees two sessions focusing the same uncached star never run duplicate
drivers racing to write the same ``model-full.fits``.
"""
import os
import subprocess
import sys
import threading
import traceback
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

# ASAP checkout used by the import probe; overridable for other deployments.
_ASAP_PATH = os.environ.get(
    "WAVE_EXPLORER_ASAP_PATH", "/net/vdesk/data2/cobelens/MRP/new/asap"
)

# Explicit asap-env interpreter: the middle fallback when the app's own
# interpreter lacks ASAP. ``conda run`` alone is NOT reliable here (conda is
# not on PATH on the cluster without a module load).
_ASAP_ENV_PYTHON = "/net/vdesk/data2/cobelens/.conda/envs/asap/bin/python"

# The wave_explorer package's PARENT directory: running the driver with this as
# cwd makes ``-m wave_explorer.full_model`` resolve no matter where the server
# was started. star_focus.py lives at wave_explorer/callbacks/, so parents[2]
# is the directory CONTAINING the package.
_PACKAGE_PARENT = Path(__file__).resolve().parents[2]

# Per-folder locks so two sessions focusing the same uncached star never launch
# duplicate ~1-min drivers racing to write the same model-full.fits. The dict
# itself is guarded; each folder lock is held across the cache check + driver
# run + load (double-checked locking: waiters re-check validity on acquire and
# reuse the first runner's result).
_FOLDER_LOCKS = {}
_FOLDER_LOCKS_GUARD = threading.Lock()


def _folder_lock(folder):
    key = str(Path(folder).resolve())
    with _FOLDER_LOCKS_GUARD:
        lock = _FOLDER_LOCKS.get(key)
        if lock is None:
            lock = _FOLDER_LOCKS[key] = threading.Lock()
        return lock


def _probe_asap(python_exe):
    """True if ``python_exe`` can import ASAP (with the checkout on sys.path)."""
    probe = (
        "import sys; "
        f"sys.path.insert(0, {_ASAP_PATH!r}); "
        "import asap"
    )
    try:
        r = subprocess.run(
            [python_exe, "-c", probe],
            capture_output=True,
            text=True,
            timeout=120,
        )
        return r.returncode == 0
    except Exception:
        return False


def _resolve_driver_cmd_prefix():
    """Return the argv prefix that runs the driver with ASAP available.

    Prefer the app's own interpreter when it can import ASAP; then the explicit
    asap-env interpreter; last, ``conda run -n asap python`` (only works where
    conda is on PATH).
    """
    if _probe_asap(sys.executable):
        return [sys.executable]
    if Path(_ASAP_ENV_PYTHON).exists() and _probe_asap(_ASAP_ENV_PYTHON):
        return [_ASAP_ENV_PYTHON]
    return ["conda", "run", "-n", "asap", "python"]


def _tail(text, n_lines=30):
    lines = (text or "").splitlines()
    return "\n".join(lines[-n_lines:])


def _run_driver(folder, driver_prefix):
    """Default subprocess runner: compute ``model-full.fits`` for ``folder``.

    Returns True on success (driver exit 0 and the cache now exists), else
    False. Timeout/launch errors and driver diagnostics (returncode + the last
    ~30 lines of stdout/stderr) are logged to the server console with a
    ``[star-focus]`` prefix so failures are debuggable.
    """
    cmd = driver_prefix + ["-m", "wave_explorer.full_model", str(folder)]
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, timeout=_DRIVER_TIMEOUT_S,
            cwd=str(_PACKAGE_PARENT),
        )
    except Exception:
        print(f"[star-focus] driver launch failed for {folder}: cmd={cmd}",
              file=sys.stderr)
        traceback.print_exc()
        return False
    ok = proc.returncode == 0 and (Path(folder) / "model-full.fits").exists()
    if not ok:
        print(
            f"[star-focus] driver failed for {folder} "
            f"(returncode={proc.returncode}, cmd={cmd})",
            file=sys.stderr,
        )
        if proc.stderr:
            print(f"[star-focus] driver stderr (tail):\n{_tail(proc.stderr)}",
                  file=sys.stderr)
        if proc.stdout:
            print(f"[star-focus] driver stdout (tail):\n{_tail(proc.stdout)}",
                  file=sys.stderr)
    return ok


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

    # Per-folder lock (double-checked): the unlocked check is a fast path for
    # valid caches; on miss, re-check under the lock so a waiter blocked behind
    # a running driver reuses its freshly written cache instead of recomputing.
    if not is_cache_valid(cache, results):
        with _folder_lock(folder):
            if not is_cache_valid(cache, results):
                if not run_driver(folder):
                    return no_update, "error"

    try:
        fd = load_full_model(folder)
        payload = build_single_star_payload(fd, dataset)
    except Exception:
        print(f"[star-focus] loading model-full payload failed for {folder}:",
              file=sys.stderr)
        traceback.print_exc()
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
        try:
            payload, status = focus_star_payload(dataset, slug, run_driver)
        except Exception:
            print(f"[star-focus] callback failed for slug {slug!r}:",
                  file=sys.stderr)
            traceback.print_exc()
            payload, status = no_update, "error"

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
