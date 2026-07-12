# Teff-Stack Mode Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
>
> **User preference override:** Do NOT commit. The user commits themselves. Skip any habitual commit step.

**Goal:** Add a CLI-activated mode (`--stack-teff [N]`) that picks N stars (default 10) spanning the retrieved Teff range and renders them stacked with vertical offsets — full region curation stays active, statistics scoped to the displayed stars, per-star region usage visible.

**Architecture:** A new `stack_select.py` module picks the stars (results.txt Teff parse → dedup → even-Teff spread). `data_processing.py` gains `build_stacked_dataset()` which reuses `build_dataset()` restricted to the picked slugs (so every existing callback works unchanged with N-star statistics) plus a `stacked: true` payload variant carrying per-star obs/fit traces and a per-region × per-star χ² matrix. `spectrum.js` learns to render the stacked variant (offset traces, Teff colormap, pinned labels, redesigned tooltip, no residual panel). Spec: `docs/superpowers/specs/2026-06-11-teff-stack-mode-design.md`.

**Tech Stack:** Python (Dash, numpy, astropy via `load_fit_data`), vanilla-JS SVG renderer, pytest.

**Repo root for all paths below:** `/net/vdesk/data2/cobelens/MRP/new/obs-data-example/wave_explorer/`

**Test command prefix (asap conda env has dash/numpy/astropy):**
`cd /net/vdesk/data2/cobelens/MRP/new/obs-data-example/wave_explorer && conda run -n asap python -m pytest`

## File map

| File | Action | Responsibility |
|---|---|---|
| `stack_select.py` | Create | Teff parsing, dedup, even-Teff pick, selection orchestration |
| `data_processing.py` | Modify | `only_slugs` filter; fitted-range masking; stacked payload; stacked dataset builder |
| `app.py` | Modify | `--stack-teff` / `--stack-offset` flags, banner, dataset dispatch |
| `layout.py` | Modify | stacked payload into the store, hide star-select, header chip, subtitle |
| `assets/spectrum.js` | Modify | stacked rendering, Teff colormap, labels, tooltip, NaN-safe paths |
| `assets/styles.css` | Modify | tooltip per-star row styles, star label style |
| `tests/test_stack_select.py` | Create | unit tests for selection |
| `tests/test_stacked_payload.py` | Create | unit tests for masking + payload |
| `tests/test_stacked_dataset.py` | Create | smoke test on real `06_retrievals` |

---

### Task 1: `parse_results_teff` — read Teff from results.txt

**Files:**
- Create: `stack_select.py`
- Create: `tests/test_stack_select.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_stack_select.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `conda run -n asap python -m pytest tests/test_stack_select.py -v`
Expected: FAIL / collection error — `No module named 'wave_explorer.stack_select'`

- [ ] **Step 3: Write the implementation**

Create `stack_select.py`:

```python
"""Teff-stack mode — star selection.

Picks N stars spanning the retrieved Teff range for the stacked
comparison view. Reads Teff from each star's ``results.txt`` (no FITS
loading), dedupes duplicate-named star dirs (``gl_15a`` vs ``gl15a``),
and spreads the picks evenly in Teff.
"""
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple

_TEFF_RE = re.compile(r"^flt\s*:\s*teff\s*:\s*(\S+)")


def parse_results_teff(results_path) -> Optional[float]:
    """Teff from an ASAP ``results.txt`` (``flt : teff : <val> <err>`` line)."""
    try:
        text = Path(results_path).read_text()
    except OSError:
        return None
    for line in text.splitlines():
        m = _TEFF_RE.match(line.strip())
        if m:
            try:
                return float(m.group(1))
            except ValueError:
                return None
    return None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `conda run -n asap python -m pytest tests/test_stack_select.py -v`
Expected: 3 PASS

---

### Task 2: `dedup_star_folders` — collapse duplicate star dirs

**Files:**
- Modify: `stack_select.py`
- Modify: `tests/test_stack_select.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_stack_select.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `conda run -n asap python -m pytest tests/test_stack_select.py -v`
Expected: 2 new FAIL — `cannot import name 'dedup_star_folders'`

- [ ] **Step 3: Write the implementation**

Append to `stack_select.py`:

```python
def dedup_star_folders(
    found: Dict[str, Path],
) -> Tuple[Dict[str, Path], List[str]]:
    """Collapse duplicate-named star dirs (``gl_15a`` vs ``gl15a``).

    Slugs are duplicates when they match after removing underscores
    (case-insensitive). Among duplicates the folder whose ``results.txt``
    has the newest mtime wins. Returns ``(kept, dropped_slugs)``.
    """
    groups: Dict[str, List[str]] = {}
    for slug in found:
        groups.setdefault(slug.replace("_", "").lower(), []).append(slug)

    def _mtime(slug: str) -> float:
        try:
            return (found[slug] / "results.txt").stat().st_mtime
        except OSError:
            return float("-inf")

    kept: Dict[str, Path] = {}
    dropped: List[str] = []
    for slugs in groups.values():
        slugs = sorted(slugs, key=_mtime, reverse=True)
        kept[slugs[0]] = found[slugs[0]]
        dropped.extend(slugs[1:])
    return {s: kept[s] for s in sorted(kept)}, sorted(dropped)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `conda run -n asap python -m pytest tests/test_stack_select.py -v`
Expected: 5 PASS

---

### Task 3: `pick_even_teff` — even-spread selection

**Files:**
- Modify: `stack_select.py`
- Modify: `tests/test_stack_select.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_stack_select.py`:

```python
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
    assert 4500 in pt
    assert pt[0] == 3000
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `conda run -n asap python -m pytest tests/test_stack_select.py -v`
Expected: 3 new FAIL — `cannot import name 'pick_even_teff'`

- [ ] **Step 3: Write the implementation**

Append to `stack_select.py`:

```python
def pick_even_teff(candidates: List[dict], n: int) -> List[dict]:
    """Pick up to ``n`` candidates spread evenly in Teff.

    ``candidates`` are dicts with at least ``slug`` and ``teff``. The
    coolest and hottest stars are always included; the remaining picks
    greedily take the unused star nearest each evenly spaced target
    temperature. Returns the picks sorted by Teff ascending.
    """
    cands = sorted(candidates, key=lambda c: c["teff"])
    if n >= len(cands):
        return cands
    if n == 1:
        return [cands[0]]

    tmin, tmax = cands[0]["teff"], cands[-1]["teff"]
    targets = [tmin + (tmax - tmin) * i / (n - 1) for i in range(n)]
    used = [False] * len(cands)
    picked_idx: List[int] = []
    # Endpoints first so an inner target can never steal them.
    for ti in [0, n - 1] + list(range(1, n - 1)):
        best, best_d = None, float("inf")
        for j, c in enumerate(cands):
            if used[j]:
                continue
            d = abs(c["teff"] - targets[ti])
            if d < best_d:
                best, best_d = j, d
        used[best] = True
        picked_idx.append(best)
    return [cands[j] for j in sorted(picked_idx)]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `conda run -n asap python -m pytest tests/test_stack_select.py -v`
Expected: 8 PASS

---

### Task 4: `select_stack_stars` — selection orchestration

**Files:**
- Modify: `stack_select.py`
- Modify: `tests/test_stack_select.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_stack_select.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `conda run -n asap python -m pytest tests/test_stack_select.py -v`
Expected: 2 new FAIL — `cannot import name 'select_stack_stars'`

- [ ] **Step 3: Write the implementation**

Append to `stack_select.py`:

```python
def select_stack_stars(found: Dict[str, Path], n: int) -> dict:
    """Resolve the stack-mode star picks from discovered output folders.

    ``found`` is ``discover_output_folders`` output (slug -> output dir).
    Returns ``{"picked", "candidates", "warnings"}``: ``picked`` is the
    even-Teff selection (slug/teff/folder dicts, Teff ascending);
    ``candidates`` is every deduped star with a usable Teff (kept for
    load-failure substitution); ``warnings`` are printable strings.
    """
    warnings: List[str] = []
    kept, dropped = dedup_star_folders(found)
    if dropped:
        warnings.append(
            "duplicate star dirs dropped: " + ", ".join(dropped)
        )
    candidates: List[dict] = []
    for slug, folder in kept.items():
        teff = parse_results_teff(folder / "results.txt")
        if teff is None:
            warnings.append(f"no Teff in {slug}/results.txt — skipped")
            continue
        candidates.append({"slug": slug, "teff": teff, "folder": folder})
    if len(candidates) < n:
        warnings.append(
            f"only {len(candidates)} usable stars (< {n}) — using all"
        )
    picked = pick_even_teff(candidates, n)
    return {"picked": picked, "candidates": candidates, "warnings": warnings}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `conda run -n asap python -m pytest tests/test_stack_select.py -v`
Expected: 10 PASS

---

### Task 5: `only_slugs` filter in `build_dataset`

**Files:**
- Modify: `data_processing.py:573-590` (the `build_dataset` signature and discovery block)

No new unit test (exercised by the Task 8 smoke test); this is a two-line, behavior-preserving change when the parameter is omitted.

- [ ] **Step 1: Add the parameter**

In `data_processing.py`, change the `build_dataset` signature:

```python
def build_dataset(
    retrievals_dir: Path,
    suffix: str,
    line_list_path: Optional[str],
    grid_step_nm: float,
    smooth_window: int,
    vald_path: Optional[str] = None,
    only_slugs: Optional[List[str]] = None,
) -> dict:
    """Load and process all spectral data for a given suffix."""
    found = discover_output_folders(retrievals_dir, suffix)
    if only_slugs is not None:
        wanted = set(only_slugs)
        found = {s: p for s, p in found.items() if s in wanted}
    if not found:
        raise RuntimeError(
            f"No output folders for suffix '{suffix}' in {retrievals_dir}"
        )
```

(Only the signature line, the docstring position, and the two `only_slugs` lines change; everything after stays as-is.)

- [ ] **Step 2: Run the existing payload tests to confirm nothing broke**

Run: `conda run -n asap python -m pytest tests/test_spectrum_payload.py -v`
Expected: all PASS

---

### Task 6: fitted-range masking helpers

**Files:**
- Modify: `data_processing.py` (append after `build_single_star_vald_payload`)
- Create: `tests/test_stacked_payload.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_stacked_payload.py`:

```python
"""Unit tests for the Teff-stack payload: fit masking + payload builder."""
import json
import math

import numpy as np

from wave_explorer.data_processing import (
    fitted_ranges_for_star,
    mask_to_ranges,
)


def synth_fit_data(n_pix=200, w0_nm=700.0, dw_nm=0.05,
                   fitted=((20, 60), (120, 160))):
    """One-order synthetic fit-data dict in the load_fit_data shape.

    ``wvl`` is in Å (load_fit_data convention; flatten divides by 10).
    ``fitted`` lists (start, stop) pixel slices marked in idxtofit.
    """
    w_nm = w0_nm + dw_nm * np.arange(n_pix)
    wvl = (w_nm * 10.0)[None, :]                       # (1, n_pix) Å
    flux = np.ones((1, n_pix))
    fit = np.full((1, n_pix), 0.98)
    pix = np.concatenate([np.arange(a, b) for a, b in fitted])
    idxtofit = (np.zeros(pix.size, dtype=int), pix)
    return {
        "wvl": wvl,
        "flux": flux,
        "fit": fit,
        "flux_fit": flux.copy(),
        "error": np.full((1, n_pix), 0.01),
        "idxtofit": idxtofit,
    }


def test_fitted_ranges_cover_fitted_pixels_only():
    fd = synth_fit_data()
    ranges = fitted_ranges_for_star(fd)
    assert len(ranges) == 2
    # first fitted block: pixels 20..59 → 701.0 .. 702.95 nm
    lo, hi = ranges[0]
    assert math.isclose(lo, 701.0, abs_tol=1e-6)
    assert math.isclose(hi, 702.95, abs_tol=1e-6)


def test_fitted_ranges_empty_idxtofit():
    fd = synth_fit_data(fitted=())
    fd["idxtofit"] = (np.array([], dtype=int), np.array([], dtype=int))
    assert fitted_ranges_for_star(fd) == []


def test_mask_to_ranges_nans_outside():
    common_w = np.array([700.0, 701.5, 703.5, 706.5])
    y = np.array([1.0, 2.0, 3.0, 4.0])
    out = mask_to_ranges(y, common_w, [(701.0, 702.95)])
    assert np.isnan(out[0])
    assert out[1] == 2.0
    assert np.isnan(out[2]) and np.isnan(out[3])
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `conda run -n asap python -m pytest tests/test_stacked_payload.py -v`
Expected: FAIL — `cannot import name 'fitted_ranges_for_star'`

- [ ] **Step 3: Write the implementation**

Append to `data_processing.py` (new section after the single-star helpers):

```python
# ══════════════════════════════════════════════════════════════════════════════
# Teff-stack mode (stacked multi-star view)
# ══════════════════════════════════════════════════════════════════════════════


def fitted_ranges_for_star(fit_data: dict) -> List[Tuple[float, float]]:
    """Contiguous wavelength spans of the pixels this star actually fitted.

    Derived from ``idxtofit``, so a region filtered out for this star (the
    per-star filtering workflow) contributes no span. Reuses the gap
    detection in ``compute_observed_ranges``.
    """
    wvl, idxtofit = fit_data["wvl"], fit_data["idxtofit"]
    ws = []
    for order in range(wvl.shape[0]):
        pix = idxtofit[1][idxtofit[0] == order]
        if len(pix):
            ws.append(np.asarray(wvl[order])[pix] / 10.0)
    if not ws:
        return []
    w = np.sort(np.concatenate(ws))
    w = w[np.isfinite(w)]
    if w.size < 2:
        return []
    return compute_observed_ranges({"_": (w, w, w)})


def mask_to_ranges(
    y: np.ndarray, common_w: np.ndarray, ranges: List[Tuple[float, float]]
) -> np.ndarray:
    """NaN out ``y`` at grid points outside every ``(lo, hi)`` range."""
    keep = np.zeros(common_w.shape, dtype=bool)
    for lo, hi in ranges:
        keep |= (common_w >= lo) & (common_w <= hi)
    out = np.asarray(y, dtype=float).copy()
    out[~keep] = np.nan
    return out
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `conda run -n asap python -m pytest tests/test_stacked_payload.py -v`
Expected: 3 PASS

---

### Task 7: `build_stacked_payload` — the `stacked: true` store payload

**Files:**
- Modify: `data_processing.py`
- Modify: `tests/test_stacked_payload.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_stacked_payload.py`:

```python
from wave_explorer.data_processing import build_stacked_payload


def _stack_dataset():
    """Two synthetic stars with different Teff and different fitted pixels."""
    cool = synth_fit_data(fitted=((20, 60),))
    hot = synth_fit_data(fitted=((20, 60), (120, 160)))
    common_w = np.arange(700.0, 710.0, 0.05, dtype=np.float32)
    return {
        "common_w": common_w,
        "fit_data_cache": {"hot_star": hot, "cool_star": cool},
        "stack_teffs": {"cool_star": 3000.0, "hot_star": 4000.0},
        "ll_entries": [
            # inside both stars' first fitted block (701.0–702.95 nm)
            {"lower": 701.2, "upper": 701.8, "element": "Fe", "ion": "1",
             "center": 701.5},
            # inside hot star's second block only (706.0–707.95 nm)
            {"lower": 706.2, "upper": 706.8, "element": "Ti", "ion": "1",
             "center": 706.5},
        ],
        "ll_hover_stats": [],
        "region_summary": [],
    }


def test_stars_sorted_by_teff_with_offsets():
    p = build_stacked_payload(_stack_dataset(), offset_step=0.5)
    assert p["stacked"] is True
    slugs = [s["slug"] for s in p["stars"]]
    assert slugs == ["cool_star", "hot_star"]          # Teff ascending
    assert [s["offset"] for s in p["stars"]] == [0.0, 0.5]
    assert p["offsetStep"] == 0.5


def test_fit_masked_to_fitted_ranges():
    p = build_stacked_payload(_stack_dataset(), offset_step=0.5)
    cool = p["stars"][0]
    w = p["wavelengths"]
    # grid point inside cool star's only fitted block → fit present
    i_in = min(range(len(w)), key=lambda i: abs(w[i] - 702.0))
    assert cool["fitFlux"][i_in] is not None
    # grid point inside the hot-only block → cool star's fit masked
    i_out = min(range(len(w)), key=lambda i: abs(w[i] - 707.0))
    assert cool["fitFlux"][i_out] is None
    assert p["stars"][1]["fitFlux"][i_out] is not None


def test_per_star_region_matrix():
    p = build_stacked_payload(_stack_dataset(), offset_step=0.5)
    # region 0: both stars fit it
    per0 = p["regions"][0]["perStar"]
    assert len(per0) == 2
    assert per0[0]["npix"] > 0 and per0[1]["npix"] > 0
    assert per0[0]["chi2"] is not None
    # region 1: hot star only — cool star (index 0) has npix == 0
    per1 = p["regions"][1]["perStar"]
    assert per1[0]["npix"] == 0 and per1[0]["chi2"] is None
    assert per1[1]["npix"] > 0


def test_payload_is_strict_json():
    p = build_stacked_payload(_stack_dataset(), offset_step=0.5)
    s = json.dumps(p)          # would raise on actual NaN with allow_nan=False
    assert "NaN" not in s
    json.dumps(p, allow_nan=False)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `conda run -n asap python -m pytest tests/test_stacked_payload.py -v`
Expected: 4 new FAIL — `cannot import name 'build_stacked_payload'`

- [ ] **Step 3: Write the implementation**

Append to `data_processing.py` (same Teff-stack section):

```python
def build_stacked_payload(dataset: dict, offset_step: float = 0.5) -> dict:
    """Payload for the Teff-stack view (``stacked: true`` variant).

    One obs/fit trace pair per star on the dataset's common grid, each
    offset by ``i * offset_step`` with stars in Teff-ascending order
    (coolest at offset 0). Each star's fit is NaN-masked to its own
    fitted-pixel spans so per-star region filtering is visible. All
    non-finite values become None (strict JSON). ``regions[i]["perStar"]``
    carries each displayed star's χ²/N and pixel count in trace order.
    """
    common_w = np.asarray(dataset["common_w"], dtype=float)
    cache = dataset["fit_data_cache"]
    teffs = dataset["stack_teffs"]  # slug -> Teff (K)
    slugs = sorted(cache, key=lambda s: teffs[s])

    def _vals(arr):
        return [float(v) if np.isfinite(v) else None for v in arr]

    stars = []
    for i, slug in enumerate(slugs):
        fd = cache[slug]
        flat = flatten_full_spectrum(fd)
        if flat is None:
            continue
        w, obs, fit = flat
        oi = interp_to_common_grid(w, obs, common_w)
        fi = interp_to_common_grid(w, fit, common_w)
        fi = mask_to_ranges(fi, common_w, fitted_ranges_for_star(fd))
        stars.append(
            {
                "slug": slug,
                "teff": float(teffs[slug]),
                "offset": float(i * offset_step),
                "flux": _vals(oi),
                "fitFlux": _vals(fi),
            }
        )

    payload = {
        "stacked": True,
        "offsetStep": float(offset_step),
        "wavelengths": [float(v) for v in common_w],
        "lambdaMin": float(common_w[0]),
        "lambdaMax": float(common_w[-1]),
        "stars": stars,
    }
    payload.update(_build_region_metadata(dataset))

    star_order = [s["slug"] for s in stars]
    for i, e in enumerate(dataset.get("ll_entries", [])):
        per_star = []
        for slug in star_order:
            c2, npix = compute_region_chi2_for_star(
                cache[slug], float(e["lower"]), float(e["upper"])
            )
            per_star.append(
                {
                    "chi2": float(c2) if np.isfinite(c2) else None,
                    "npix": int(npix),
                }
            )
        payload["regions"][i]["perStar"] = per_star
    return payload
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `conda run -n asap python -m pytest tests/test_stacked_payload.py -v`
Expected: 7 PASS

---

### Task 8: `build_stacked_dataset` + smoke test on real retrievals

**Files:**
- Modify: `data_processing.py`
- Create: `tests/test_stacked_dataset.py`

- [ ] **Step 1: Write the failing smoke test**

Create `tests/test_stacked_dataset.py` (same real-data pattern as `test_app_smoke.py`):

```python
"""Smoke test: the Teff-stack dataset builds on the real 06_retrievals."""
from pathlib import Path

from wave_explorer.data_processing import build_stacked_dataset

REF_DIR = Path(
    "/net/vdesk/data2/cobelens/MRP/new/obs-data-example/06_retrievals"
)


def test_stacked_dataset_builds():
    ds = build_stacked_dataset(REF_DIR, "v2", None, 0.01, 1, None, n_stack=4)
    assert ds["stacked"] is True
    p = ds["stacked_payload"]
    assert p["stacked"] is True
    assert 1 <= len(p["stars"]) <= 4
    teffs = [s["teff"] for s in p["stars"]]
    assert teffs == sorted(teffs)
    # offsets ascend with Teff
    offsets = [s["offset"] for s in p["stars"]]
    assert offsets == sorted(offsets)
    # statistics are scoped to the displayed stars
    assert set(ds["stack_teffs"]) == set(ds["fit_data_cache"])
    # any "__mean__" restore must restore the stack, not a mean view
    assert ds["mean_payload"] is ds["stacked_payload"]
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `conda run -n asap python -m pytest tests/test_stacked_dataset.py -v`
Expected: FAIL — `cannot import name 'build_stacked_dataset'`

- [ ] **Step 3: Write the implementation**

Append to `data_processing.py` (same Teff-stack section):

```python
def build_stacked_dataset(
    retrievals_dir: Path,
    suffix: str,
    line_list_path: Optional[str],
    grid_step_nm: float,
    smooth_window: int,
    vald_path: Optional[str] = None,
    n_stack: int = 10,
    offset_step: float = 0.5,
) -> dict:
    """Build the Teff-stack dataset: N even-Teff stars, stacked view.

    Same shape as ``build_dataset`` restricted to the picked slugs (so
    every existing callback works unchanged, with statistics scoped to
    the displayed stars) plus ``stacked``, ``stack_teffs`` and
    ``stacked_payload``. A picked star whose fit-data.fits fails to load
    is substituted by the next-nearest-Teff unused candidate.
    """
    from .stack_select import select_stack_stars

    found = discover_output_folders(retrievals_dir, suffix)
    if not found:
        raise RuntimeError(
            f"No output folders for suffix '{suffix}' in {retrievals_dir}"
        )
    sel = select_stack_stars(found, n_stack)
    for w in sel["warnings"]:
        print(f"  ⚠ {w}")
    if not sel["picked"]:
        raise RuntimeError("No stars with a usable Teff in results.txt.")

    # Verify each pick loads; substitute next-nearest-Teff on failure.
    picked_slugs = {p["slug"] for p in sel["picked"]}
    unused = [c for c in sel["candidates"] if c["slug"] not in picked_slugs]
    final = []
    for p in sel["picked"]:
        cand = p
        while cand is not None:
            try:
                load_fit_data(str(found[cand["slug"]]))
                final.append(cand)
                break
            except Exception:
                print(
                    f"  ⚠ {cand['slug']}: fit-data.fits failed to load — "
                    "substituting"
                )
                if unused:
                    unused.sort(key=lambda c: abs(c["teff"] - p["teff"]))
                    cand = unused.pop(0)
                else:
                    cand = None
    if not final:
        raise RuntimeError("No valid fit-data.fits loaded for the Teff stack.")

    dataset = build_dataset(
        retrievals_dir=retrievals_dir,
        suffix=suffix,
        line_list_path=line_list_path,
        grid_step_nm=grid_step_nm,
        smooth_window=smooth_window,
        vald_path=vald_path,
        only_slugs=[c["slug"] for c in final],
    )
    dataset["stacked"] = True
    dataset["stack_teffs"] = {
        c["slug"]: c["teff"]
        for c in final
        if c["slug"] in dataset["fit_data_cache"]
    }
    dataset["stacked_payload"] = build_stacked_payload(dataset, offset_step)
    # Any "__mean__" restore in stacked mode must restore the stack.
    dataset["mean_payload"] = dataset["stacked_payload"]
    return dataset
```

- [ ] **Step 4: Run the smoke test (slow — loads real FITS)**

Run: `conda run -n asap python -m pytest tests/test_stacked_dataset.py -v`
Expected: PASS

- [ ] **Step 5: Run the full Python test suite**

Run: `conda run -n asap python -m pytest tests/ -v`
Expected: all PASS (pre-existing failures, if any, noted and unchanged)

---

### Task 9: CLI flags + layout wiring

**Files:**
- Modify: `app.py:140-205` (argparse + main)
- Modify: `layout.py` (`build_header`, `build_layout`)
- Modify: `tests/test_stacked_dataset.py` (app-level assertion)

- [ ] **Step 1: Write the failing test**

Append to `tests/test_stacked_dataset.py`:

```python
from wave_explorer.app import create_app
from wave_explorer.data_processing import build_stacked_dataset as _bsd


def test_stacked_app_builds_and_hides_star_select():
    ds = _bsd(REF_DIR, "v2", None, 0.01, 1, None, n_stack=3)
    app = create_app(ds)
    layout_str = str(app.layout)
    assert "star-select" in layout_str          # component present (callbacks wired)
    assert "Teff stack" in layout_str           # header chip
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `conda run -n asap python -m pytest tests/test_stacked_dataset.py::test_stacked_app_builds_and_hides_star_select -v`
Expected: FAIL — `'Teff stack' not in layout`

- [ ] **Step 3: Wire the layout**

In `layout.py`:

(a) In `build_header`, after the `ll regions` chip (`layout.py:106-112`), add:

```python
            *(
                [
                    html.Div(
                        className="h-chip c-amber",
                        children=[
                            "mode ",
                            html.Span(
                                f"Teff stack ×{len(dataset['stack_teffs'])}",
                                className="hc-val",
                            ),
                        ],
                    )
                ]
                if dataset.get("stacked")
                else []
            ),
```

(b) In `build_layout`, at the top of the function add:

```python
    stacked = bool(dataset.get("stacked"))
```

(c) Replace the toolbar subtitle `html.Div("Observation, fit & residuals", className="display-md")` with:

```python
                                            html.Div(
                                                "Teff sequence · stacked offsets"
                                                if stacked
                                                else "Observation, fit & residuals",
                                                className="display-md",
                                            ),
```

(d) On the `html.Div` wrapping the star dropdown + spinner (the one with
`style={"display": "flex", "gap": "8px", ...}` around `dcc.Dropdown(id="star-select", ...)`),
make the style conditional so the components stay in the DOM (their callbacks
still register) but invisible:

```python
                                                style=(
                                                    {"display": "none"}
                                                    if stacked
                                                    else {
                                                        "display": "flex",
                                                        "gap": "8px",
                                                        "alignItems": "center",
                                                        "marginTop": "6px",
                                                    }
                                                ),
```

(e) The `spectrum-data-store` initial data (`layout.py:984-987`) becomes:

```python
            dcc.Store(
                id="spectrum-data-store",
                data=(
                    dataset["stacked_payload"]
                    if stacked
                    else build_spectrum_payload(dataset)
                ),
            ),
```

- [ ] **Step 4: Wire the CLI**

In `app.py`, after the `--smooth-window` argument add:

```python
    parser.add_argument(
        "--stack-teff",
        nargs="?",
        const=10,
        type=int,
        default=None,
        metavar="N",
        help="Teff-stack mode: pick N stars (default 10) spanning the "
        "retrieved Teff range and show them stacked with vertical "
        "offsets instead of averaged.",
    )
    parser.add_argument(
        "--stack-offset",
        type=float,
        default=0.5,
        help="Vertical offset between consecutive stars in "
        "normalized-flux units (stack mode only).",
    )
```

In `main()`, replace the single `dataset = build_dataset(...)` call with:

```python
    if args.stack_teff:
        from .data_processing import build_stacked_dataset

        dataset = build_stacked_dataset(
            retrievals_dir=Path(args.retrievals_dir).resolve(),
            suffix=args.suffix,
            line_list_path=args.line_list,
            grid_step_nm=args.grid_step,
            smooth_window=args.smooth_window,
            vald_path=args.vald_list,
            n_stack=args.stack_teff,
            offset_step=args.stack_offset,
        )
    else:
        dataset = build_dataset(
            retrievals_dir=Path(args.retrievals_dir).resolve(),
            suffix=args.suffix,
            line_list_path=args.line_list,
            grid_step_nm=args.grid_step,
            smooth_window=args.smooth_window,
            vald_path=args.vald_list,
        )
```

After the `Stars` banner line, add:

```python
    if dataset.get("stacked"):
        print(f"  Mode           : Teff stack ({len(dataset['stack_teffs'])} stars)")
        for s in dataset["stacked_payload"]["stars"]:
            print(f"    {s['slug']:<16s} Teff = {s['teff']:7.1f} K")
```

Also add the new example to the argparse epilog:

```
  python -m wave_explorer --suffix ds_leo --stack-teff
  python -m wave_explorer --suffix ds_leo --stack-teff 8 --stack-offset 0.6
```

- [ ] **Step 5: Run the tests**

Run: `conda run -n asap python -m pytest tests/test_stacked_dataset.py tests/test_app_smoke.py -v`
Expected: all PASS (normal mode untouched, stacked app builds)

---

### Task 10: `spectrum.js` — stacked rendering

**Files:**
- Modify: `assets/spectrum.js`
- Modify: `assets/styles.css`

No JS test infra exists; correctness is verified in Task 12 by running the app. Make each edit exactly as shown.

- [ ] **Step 1: Make the main-panel height mode-dependent**

At the geometry block (`spectrum.js:17-26`), `MAIN` is already a mutable object. Add after `var fullBottom = RESID.top + RESID.h;`:

```js
  var MAIN_H_NORMAL = MAIN.h;                  // 320
  var MAIN_H_STACKED = fullBottom - MAIN.top;  // resid panel absorbed
```

- [ ] **Step 2: Make `buildPath` NaN/null-safe and offset-aware**

Replace the whole `buildPath` function (`spectrum.js:183-192`) with:

```js
  function buildPath(arr, yFn, offset) {
    var w = data.wavelengths, d = "", started = false;
    var off = offset || 0;
    for (var i = 0; i < w.length; i++) {
      if (w[i] < view.min - 0.05 || w[i] > view.max + 0.05) continue;
      var v = arr[i];
      if (v == null || !isFinite(v)) { started = false; continue; }
      var x = xScale(w[i]).toFixed(2), y = yFn(v + off).toFixed(2);
      d += (started ? "L" : "M") + x + "," + y;
      started = true;
    }
    return d;
  }
```

(This also fixes mean-view paths silently drawing through null gaps.)

- [ ] **Step 3: Add the Teff colormap + hovered-star state**

After the `elementColor` function (`spectrum.js:83-87`), add:

```js
  function teffColor(t) {
    if (!data || !data.stars || data.stars.length < 2) return "var(--accent)";
    var ts = data.stars.map(function (s) { return s.teff; });
    var tmin = Math.min.apply(null, ts), tmax = Math.max.apply(null, ts);
    var u = tmax > tmin ? (t - tmin) / (tmax - tmin) : 0.5;
    // cool red (hue 8) → hot blue (hue 215)
    return "hsl(" + Math.round(8 + 207 * u) + ", 58%, 42%)";
  }
```

In the module-state block (near `var hoveredIdx = null;`, `spectrum.js:39`), add:

```js
  var hoveredStar = null;    // index into data.stars (stacked mode)
```

- [ ] **Step 4: Re-fit scales for stacked payloads in `sync()`**

In `sync()`, replace the scale-fitting block inside `if (newData) { ... }` — the part from `var fmin = Infinity...` through `residMax = Math.max(0.01, rmax * 1.15);` (`spectrum.js:854-862`) — with:

```js
      MAIN.h = data.stacked ? MAIN_H_STACKED : MAIN_H_NORMAL;
      var fmin = Infinity, fmax = -Infinity, rmax = 0;
      if (data.stacked) {
        data.stars.forEach(function (s) {
          for (var i = 0; i < s.flux.length; i++) {
            var o = s.flux[i], f = s.fitFlux[i];
            if (o != null && isFinite(o)) {
              fmin = Math.min(fmin, o + s.offset);
              fmax = Math.max(fmax, o + s.offset);
            }
            if (f != null && isFinite(f)) {
              fmin = Math.min(fmin, f + s.offset);
              fmax = Math.max(fmax, f + s.offset);
            }
          }
        });
        if (!isFinite(fmin)) { fmin = 0; fmax = 1; }
      } else {
        for (var i = 0; i < data.flux.length; i++) {
          fmin = Math.min(fmin, data.flux[i], data.fitFlux[i]);
          fmax = Math.max(fmax, data.flux[i], data.fitFlux[i]);
          rmax = Math.max(rmax, Math.abs(data.resid[i]));
        }
      }
      var fpad = 0.04 * (fmax - fmin || 1);
      fluxRange = { min: fmin - fpad, max: fmax + fpad };
      residMax = Math.max(0.01, rmax * 1.15);
```

(The mean-view loop tolerates null the same way it tolerated NaN: Math.min/max
with null coerces to 0 — unchanged behavior. The stacked branch is strict.)

- [ ] **Step 5: Branch `render()` for stacked mode**

In `render()` (`spectrum.js:218-327`), apply these edits — everything keyed off `var stk = !!(data && data.stacked);` declared immediately after `var tk = ticks();` (it must precede the `fluxTicks` line, which uses it in edit (c)):

(a) Backgrounds + grid + continuum/zero lines — replace the block from
`// backgrounds` through the resid zero-line `parts.push(el("line", {...yResid(0)...}))` with:

```js
    // backgrounds
    parts.push(rect(PAD.left, MAIN.top, innerW, MAIN.h, "var(--paper)"));
    if (!stk) {
      parts.push(rect(PAD.left, RESID.top, innerW, RESID.h, "var(--paper-soft)"));
    }

    // grid
    var grid = el("g", { class: "spectrum-grid" });
    tk.arr.forEach(function (t) {
      grid.appendChild(line(xScale(t), MAIN.top, xScale(t), MAIN.top + MAIN.h));
      if (!stk) {
        grid.appendChild(line(xScale(t), RESID.top, xScale(t), RESID.top + RESID.h));
      }
    });
    fluxTicks.forEach(function (f) {
      grid.appendChild(line(PAD.left, yMain(f), PAD.left + innerW, yMain(f)));
    });
    if (!stk) {
      residTicks.forEach(function (rv) {
        grid.appendChild(line(PAD.left, yResid(rv), PAD.left + innerW, yResid(rv)));
      });
    }
    parts.push(grid);

    // continuum + zero lines
    if (stk) {
      data.stars.forEach(function (s) {
        parts.push(el("line", {
          class: "continuum-line",
          x1: PAD.left, x2: PAD.left + innerW,
          y1: yMain(1.0 + s.offset), y2: yMain(1.0 + s.offset),
          opacity: 0.35,
        }));
      });
    } else {
      parts.push(el("line", {
        class: "continuum-line",
        x1: PAD.left, x2: PAD.left + innerW, y1: yMain(1.0), y2: yMain(1.0),
      }));
      parts.push(el("line", {
        x1: PAD.left, x2: PAD.left + innerW, y1: yResid(0), y2: yResid(0),
        stroke: "var(--ink-3)", "stroke-width": 0.8, opacity: 0.5,
      }));
    }
```

(b) Data lines — replace the three `parts.push(el("path", ...))` lines and the
residual-outlier-dots block (`spectrum.js:293-310`) with:

```js
    // data lines
    if (stk) {
      data.stars.forEach(function (s, k) {
        var hov = hoveredStar === k;
        parts.push(el("path", {
          class: "obs-line",
          d: buildPath(s.flux, yMain, s.offset),
          style: hov ? "opacity:1;stroke-width:1.5" : null,
        }));
        parts.push(el("path", {
          class: "fit-line",
          d: buildPath(s.fitFlux, yMain, s.offset),
          style: "stroke:" + teffColor(s.teff) +
            (hov ? ";stroke-width:2.2" : ""),
        }));
      });
      // pinned star labels at the left edge
      data.stars.forEach(function (s) {
        parts.push(el("text", {
          class: "star-label",
          x: PAD.left + 8,
          y: yMain(1.0 + s.offset) - 6,
          fill: teffColor(s.teff),
        }, s.slug + " · " + Math.round(s.teff) + " K"));
      });
    } else {
      parts.push(el("path", { class: "obs-line", d: buildPath(data.flux, yMain) }));
      parts.push(el("path", { class: "fit-line", d: buildPath(data.fitFlux, yMain) }));
      parts.push(el("path", { class: "resid-line", d: buildPath(data.resid, yResid) }));

      // residual outlier dots
      var dots = el("g", {});
      var w = data.wavelengths, rd = data.resid;
      for (var i = 0; i < w.length; i++) {
        if (w[i] < view.min || w[i] > view.max) continue;
        if (rd[i] != null && Math.abs(rd[i]) > residMax * 0.55) {
          dots.appendChild(el("circle", {
            cx: xScale(w[i]), cy: yResid(rd[i]), r: 1.6,
            fill: rd[i] > 0 ? "var(--accent)" : "var(--ink)", opacity: 0.7,
          }));
        }
      }
      parts.push(dots);
    }
```

(c) Flux tick count — replace `var fluxTicks = niceTicks(fluxRange.min, fluxRange.max, 5);` with:

```js
    var fluxTicks = niceTicks(fluxRange.min, fluxRange.max, stk ? 9 : 5);
```

(Note: `stk` must therefore be declared before this line — declare it immediately after `var tk = ticks();`.)

- [ ] **Step 6: Branch `renderAxes()` for stacked mode**

Change the signature to `function renderAxes(tk, fluxTicks, residTicks, stk)` and pass `stk` at the call site (`parts.push(renderAxes(tk, fluxTicks, residTicks, stk));`). Inside:

(a) Wrap the resid y-axis block — from `// resid y-axis` through the `"obs − fit"` text — in `if (!stk) { ... }`.

(b) Replace the main y-axis title text `"normalized flux"` with:

```js
    }, stk ? "normalized flux + offset" : "normalized flux"));
```

(c) Replace the legend block (from `// legend` to `g.appendChild(lg);`) with:

```js
    // legend
    var lg = el("g", {
      transform: "translate(" + (PLOT_W - PAD.right - 200) + "," +
        (MAIN.top + 8) + ")",
    });
    lg.appendChild(el("rect", {
      x: 0, y: 0, width: 196, height: 26, rx: 5, fill: "var(--paper)",
      stroke: "var(--hairline-soft)",
    }));
    lg.appendChild(el("line", {
      x1: 10, x2: 28, y1: 13, y2: 13, stroke: "var(--ink-3)", "stroke-width": 1.4,
    }));
    lg.appendChild(el("text", {
      class: "spectrum-axis-label", x: 32, y: 16,
    }, "obs"));
    lg.appendChild(el("line", {
      x1: 66, x2: 84, y1: 13, y2: 13,
      stroke: stk ? "hsl(110, 58%, 42%)" : "var(--accent)", "stroke-width": 1.6,
    }));
    lg.appendChild(el("text", {
      class: "spectrum-axis-label", x: 88, y: 16,
    }, stk ? "fit (Teff color)" : "fit"));
    if (!stk) {
      lg.appendChild(el("line", {
        x1: 118, x2: 136, y1: 13, y2: 13, stroke: "var(--ink-3)",
        "stroke-width": 1.2, "stroke-dasharray": "3 2",
      }));
      lg.appendChild(el("text", {
        class: "spectrum-axis-label", x: 140, y: 16,
      }, "resid"));
    }
    g.appendChild(lg);
```

- [ ] **Step 7: Add the CSS**

Append to `assets/styles.css`:

```css
/* ── Teff-stack mode ─────────────────────────────────────────────────── */
.star-label {
  font-size: 11px;
  font-weight: 600;
  paint-order: stroke;
  stroke: var(--paper);
  stroke-width: 3px;
}
.cursor-tooltip .tt-row.dim { opacity: 0.45; }
.cursor-tooltip .tt-row.hl span { font-weight: 700; }
```

- [ ] **Step 8: Syntax-check the JS**

Run: `node --check assets/spectrum.js`
Expected: no output (exit 0). If `node` is unavailable, load the app once in Task 12 and check the browser console instead.

---

### Task 11: `spectrum.js` — stacked tooltip + nearest-star hover

**Files:**
- Modify: `assets/spectrum.js`

- [ ] **Step 1: Add the vertical coordinate to `svgCoords`**

Replace `svgCoords` (`spectrum.js:558-562`) with:

```js
  function svgCoords(e) {
    var rect = svgEl.getBoundingClientRect();
    var px = ((e.clientX - rect.left) / rect.width) * PLOT_W;
    var py = ((e.clientY - rect.top) / rect.height) * PLOT_H;
    return { px: px, py: py, lambda: xInvert(px),
             clientX: e.clientX, clientY: e.clientY };
  }
```

- [ ] **Step 2: Add `nearestStar`**

After `hitRegion` (`spectrum.js:705-711`), add:

```js
  function nearestStar(lambda, py) {
    if (!data || !data.stars || !data.stars.length) return null;
    var idx = nearestIndex(lambda), best = null, bestD = Infinity;
    for (var k = 0; k < data.stars.length; k++) {
      var s = data.stars[k];
      var v = s.flux[idx];
      var base = (v != null && isFinite(v)) ? v : 1.0;
      var d = Math.abs(yMain(base + s.offset) - py);
      if (d < bestD) { bestD = d; best = k; }
    }
    return best;
  }
```

- [ ] **Step 3: Track the hovered star in `onMove` and clear it in `onLeave`**

In `onMove`, replace the trailing hover block:

```js
    // hover
    var hit = hitRegion(p.lambda);
    hoveredIdx = hit;
    if (data && data.stacked) hoveredStar = nearestStar(p.lambda, p.py);
    updateTooltip(p);
    scheduleRender();
```

In `onLeave`, after `hoveredIdx = null;` add:

```js
    hoveredStar = null;
```

- [ ] **Step 4: Add the stacked tooltip branch**

In `updateTooltip` (`spectrum.js:723-767`), insert a stacked branch right after the `if (!tip || !data) return;` guard and `var cl = p.lambda;`:

```js
    if (data.stacked) {
      var sIdx = hoveredStar != null ? hoveredStar : 0;
      var s = data.stars[sIdx];
      var di = nearestIndex(cl);
      var ov = s.flux[di], fv = s.fitFlux[di];
      var html =
        '<div class="tt-title"><span>' + s.slug + "</span><span>" +
        Math.round(s.teff) + " K</span></div>" +
        ttRow("cursor λ", cl.toFixed(3)) +
        ttRow("obs flux", ov != null && isFinite(ov) ? ov.toFixed(4) : "—") +
        ttRow("fit", fv != null && isFinite(fv) ? fv.toFixed(4) : "—");

      if (hoveredIdx != null) {
        var r = effRegion(hoveredIdx), c2 = regionChi2(hoveredIdx);
        html += '<div class="tt-sep"></div>' +
          '<div class="tt-title"><span>Region #' + (hoveredIdx + 1) +
          '</span><span class="q-badge q-' + qualityTier(c2) + '">' +
          qualityLabel(c2) + "</span></div>" +
          ttRow("range", r.lower.toFixed(3) + " – " + r.upper.toFixed(3)) +
          ttRow("med χ²/N", c2 != null && isFinite(c2) ? c2.toFixed(3) : "—");
        var reg = data.regions && data.regions[hoveredIdx];
        if (reg && reg.perStar) {
          html += '<div class="tt-sep"></div>' +
            '<div class="tt-row"><span>star</span><span>χ²/N</span></div>';
          // hottest first → rows mirror the visual stacking (coolest at bottom)
          for (var k = data.stars.length - 1; k >= 0; k--) {
            var st = data.stars[k], ps = reg.perStar[k];
            var used = ps && ps.npix > 0;
            var cls = (used ? "" : " dim") + (k === sIdx ? " hl" : "");
            html += '<div class="tt-row' + cls + '"><span>' +
              (used ? "✓ " : "✗ ") + st.slug + "</span><span>" +
              (used && ps.chi2 != null ? ps.chi2.toFixed(2) : "—") +
              "</span></div>";
          }
        }
      }

      var vh = "";
      var nearS = nearbyVald(cl, 0.08, 4);
      if (nearS.length) {
        vh = '<div class="tt-sep"></div>' +
          '<div class="tt-row"><span>VALD nearby</span><span></span></div>';
        for (var q = 0; q < nearS.length; q++) {
          var nq = nearS[q].idx;
          vh += ttRow(
            vald.elements[nq] + " " + romanize(vald.ions[nq]) +
              " @ " + vald.wavelengths[nq].toFixed(3),
            "d=" + vald.depths[nq].toFixed(2)
          );
        }
      }
      tip.innerHTML = html + vh;
      tip.style.display = "block";
      tip.style.left = (p.clientX + 16) + "px";
      tip.style.top = (p.clientY + 16) + "px";
      return;
    }
```

(The existing mean-view tooltip code below stays untouched; it only runs when
`data.stacked` is falsy, so its `sampleAt("flux"|...)` calls never see a
stacked payload.)

- [ ] **Step 5: Syntax-check the JS**

Run: `node --check assets/spectrum.js`
Expected: exit 0.

---

### Task 12: End-to-end verification

**Files:** none (manual run)

- [ ] **Step 1: Run the full Python suite once more**

Run: `conda run -n asap python -m pytest tests/ -v`
Expected: all PASS

- [ ] **Step 2: Launch the app in stacked mode**

```bash
cd /net/vdesk/data2/cobelens/MRP/new/obs-data-example
conda run -n asap python -m wave_explorer --suffix v2 --stack-teff --port 8051
```

Expected banner: `Mode : Teff stack (… stars)` followed by the per-star Teff list (ascending), plus any dedup/Teff warnings.

- [ ] **Step 3: Browser checklist (http://127.0.0.1:8051)**

- [ ] N stacked spectra, coolest at the bottom, fit traces colored red→blue with Teff
- [ ] No residual panel; main panel fills the canvas; y-axis reads "normalized flux + offset"
- [ ] Star labels (`slug · Teff K`) pinned at the left edge while panning/zooming
- [ ] Fit traces visibly break in regions a star did not use
- [ ] Hovering: tooltip header shows the star nearest the cursor; its traces highlight
- [ ] Hovering inside a region: per-star table with ✓/✗ and per-star χ²/N, hottest on top
- [ ] Region select → edge-drag works; draw mode (D) adds a region; candidate stats show N-star values
- [ ] Exclude/restore from table and header buttons; Save Curated File writes a timestamped list
- [ ] VALD toggle + depth slider still work
- [ ] Normal mode regression: relaunch without `--stack-teff`, confirm the mean view, residual panel, and star-focus dropdown all behave as before

---

## Self-review notes (already applied)

- Spec coverage: CLI (T9), selection+dedup+warnings (T1-T4), pipeline+masking (T5-T8), payload+perStar (T7), rendering/labels/colormap (T10), tooltip (T11), editing-unchanged + hidden dropdown (T9, verified T12), error handling (T4/T8), testing (T1-T9, T12).
- `stk` declaration order in `render()` fixed: declared after `var tk = ticks();`, before `fluxTicks` uses it.
- `buildPath` null-guard also protects the mean view (Dash serializes NaN→null).
- Star-focus callbacks stay registered; the hidden dropdown never fires them, and `mean_payload` is aliased to the stacked payload as a belt-and-braces fallback.
