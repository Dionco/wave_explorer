"""Unit tests for the star-focus callback's core logic.

Exercises ``focus_star_payload`` (the pure helper the Dash callback wraps)
WITHOUT a real subprocess: the driver runner is injected, so every path is
tested in-process. The cache-hit path uses the real gl_382 v2 output folder,
which already ships a valid (cache newer than results.txt) ``model-full.fits``.

Cases:
  (a) ``__mean__`` → mean_payload + "idle"; driver NOT called.
  (b) cache-hit gl_382 → a payload + "ready"; driver NOT called (asserted).
  (c) driver failure → no_update + "error".
"""
from pathlib import Path

import pytest
from dash import no_update

from wave_explorer.callbacks.star_focus import focus_star_payload

GL382_V2 = Path(
    "/net/vdesk/data2/cobelens/MRP/new/obs-data-example"
    "/06_retrievals/gl_382/output_gl_382_v2"
)


def _base_dataset():
    """Minimal dataset for build_single_star_payload + the helper.

    build_single_star_payload only reads ll_entries / ll_hover_stats /
    region_summary off the base dataset (region/colour metadata); the helper
    reads output_folders and mean_payload.
    """
    return {
        "ll_entries": [],
        "ll_hover_stats": [],
        "region_summary": [],
        "mean_payload": {"wavelengths": [515.0, 515.1], "flux": [1.0, 1.0]},
        "output_folders": {"gl_382": GL382_V2},
    }


class _Counter:
    """Stub driver runner that records whether it was invoked."""

    def __init__(self, result):
        self.result = result
        self.calls = []

    def __call__(self, folder):
        self.calls.append(folder)
        return self.result


def test_mean_returns_mean_payload_no_driver():
    ds = _base_dataset()
    runner = _Counter(result=True)
    payload, status = focus_star_payload(ds, "__mean__", runner)
    assert payload is ds["mean_payload"]
    assert status == "idle"
    assert runner.calls == []  # driver never touched for the mean view


def test_empty_slug_is_treated_as_mean():
    ds = _base_dataset()
    runner = _Counter(result=True)
    payload, status = focus_star_payload(ds, "", runner)
    assert payload is ds["mean_payload"]
    assert status == "idle"
    assert runner.calls == []


@pytest.mark.skipif(
    not (GL382_V2 / "model-full.fits").exists(),
    reason="gl_382 v2 cached model-full.fits not present",
)
def test_cache_hit_loads_payload_without_running_driver():
    ds = _base_dataset()
    # If the runner WERE called, returning False would force an error status;
    # a valid cache must short-circuit before that, so calls stays empty.
    runner = _Counter(result=False)
    payload, status = focus_star_payload(ds, "gl_382", runner)
    assert status == "ready"
    assert runner.calls == [], "valid cache must NOT invoke the driver"
    # payload has the single-star full-range shape spectrum.js consumes.
    assert payload is not no_update
    for key in ("wavelengths", "flux", "fitFlux", "resid", "lambdaMin",
                "lambdaMax", "fullRange"):
        assert key in payload
    assert payload["fullRange"] is True
    assert len(payload["wavelengths"]) == len(payload["flux"]) > 0


def test_unknown_slug_errors_without_driver():
    ds = _base_dataset()
    runner = _Counter(result=True)
    payload, status = focus_star_payload(ds, "does_not_exist", runner)
    assert payload is no_update
    assert status == "error"
    assert runner.calls == []


def test_driver_failure_errors(tmp_path):
    # Point a slug at an empty folder so the cache is missing → the driver
    # runs; the stub reports failure → error, no FITS load attempted.
    star_dir = tmp_path / "output_star_v2"
    star_dir.mkdir()
    (star_dir / "results.txt").write_text("dummy\n")
    ds = _base_dataset()
    ds["output_folders"] = {"star": star_dir}
    runner = _Counter(result=False)
    payload, status = focus_star_payload(ds, "star", runner)
    assert payload is no_update
    assert status == "error"
    assert runner.calls == [star_dir]  # driver WAS attempted (stale cache)
