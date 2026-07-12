# wave_explorer — ASAP Line Curation Dashboard

A Dash app for exploring and curating the ASAP line-list regions against a
campaign of retrieval outputs. It loads every star's `fit-data.fits` for a
given output suffix, stacks observed/model spectra onto a common wavelength
grid, computes per-region χ²/N statistics, and renders everything with a
custom client-side SVG spectrum component (no Plotly) so pan/zoom, hover,
region dragging, and drawing stay at interactive frame rates.

A static, server-less export of the app is published as a demo at
<https://dionco.github.io/wave_explorer/>.

## Quick start

```bash
cd new/obs-data-example/
alias wepy=/net/vdesk/data2/cobelens/.conda/envs/asap/bin/python

wepy -m wave_explorer                  # no suffix → lists available campaigns
wepy -m wave_explorer bic_optimal_region_filtering_v1
# or explore one run only:
wepy -m wave_explorer 06_retrievals/ds_leo/output_ds_leo_bic_optimal_region_filtering_v1
# → http://127.0.0.1:8050
```

Use the `asap` env's python directly (`conda activate` on this cluster leaves
base python shadowing the env).

### CLI

```
python -m wave_explorer [SUFFIX] [options]
```

`SUFFIX` picks which retrieval run of each star to load (folders
`06_retrievals/<star>/output_<star>_<SUFFIX>`). Run without one — or with
`--list-suffixes` — to see everything available with star counts; a typo'd
suffix suggests close matches. `--suffix SUFFIX` still works too.

Alternatively, pass a **path to a single `output_*` folder** instead of a
suffix to load exactly that one run (one star; the line list is auto-detected
from that run's `config_copy.ini`). Not compatible with `--stack-teff`.

| Flag | Meaning |
|------|---------|
| `--list-suffixes` | list every available suffix (with star counts) and exit |
| `--retrievals-dir` | defaults to `./06_retrievals` (or sibling `obs-data-example/06_retrievals`) |
| `--line-list` | explicit line list; otherwise auto-detected from the runs' `config_copy.ini` majority vote (errors on a tie) |
| `--vald-list` | VALD3 short-format list for the absorption-line overlay; defaults to the bundled `data/DionCobelens.017597` (700–1000 nm) |
| `--grid-step` | common wavelength grid step in nm (default 0.01) |
| `--smooth-window` | boxcar smoothing of the displayed mean spectra (default 1 = off) |
| `--stack-teff [N]` | Teff-stack mode: show N stars (default 10) spanning the campaign's Teff range as offset spectra instead of the mean |
| `--stack-offset` | vertical offset between stacked spectra |
| `--host/--port/--debug/--debug-hover` | server options |

Flags are grouped in `--help` (data selection / display / server / debugging),
and dataset errors (missing suffix, line-list tie, busy port) exit with a
short actionable message instead of a traceback.

### Keyboard shortcuts

`D` toggle draw mode · `Z` undo · `X` exclude/restore selected region ·
`Esc` clear selection · `Ctrl/⌘+S` save curated line list. Shortcuts are
suppressed while typing in inputs and when Ctrl/Alt/Meta chords are held
(except Ctrl+S).

## What you can do

- **Inspect**: mean observed vs model spectrum with residual panel, per-region
  χ²/N shading, hover tooltip with per-region stats, χ² histogram, worst-regions
  table, and a full-range heatstrip that doubles as a pan/zoom minimap.
  Double-click the spectrum to reset the view.
- **Curate**: drag region edges directly in the plot, exclude/restore regions
  (from plot, table, or heatstrip), draw brand-new regions (D), undo (Z),
  then save — writes a timestamped curated line list next to the original via
  atomic replace. Pending (unsaved) edits are previewed everywhere; table rows
  with pending bounds mark their (stale) χ² with `*`.
- **Focus a star**: the star dropdown switches the plot to a single star's
  full-wavelength-range observed + model spectrum. The full-range model is
  computed on demand by `full_model/` (see below) and cached as
  `model-full.fits` in the star's output folder.
- **VALD overlay**: toggleable absorption-line markers filtered by central
  depth, from the bundled VALD list.

## Architecture

```
wave_explorer/
├── app.py              # app factory + argparse CLI
├── data_processing.py  # dataset build: FITS loading, common grid, χ², payloads
├── layout.py           # header/heatstrip/histogram/stats/table + dcc.Stores
├── theme.py            # palette + χ² tier colors/labels
├── vald.py             # VALD3 short-format parser + overlay payload
├── stack_select.py     # Teff-stack star selection
├── callbacks/
│   ├── candidate.py    # region selection, stats panel, table→plot navigation
│   ├── regions.py      # drag/exclude/draw/delete/undo/save (pending-changes model)
│   ├── star_focus.py   # star dropdown → full-range model via subprocess driver
│   └── table.py        # worst-regions table refresh
├── assets/             # spectrum.js (SVG renderer), heatstrip.js, keyboard.js,
│   │                   # styles.css, fonts/ (self-hosted woff2)
├── full_model/         # standalone full-range model driver (see below)
├── scripts/
│   ├── export_demo.py      # build the static demo payloads + site/
│   └── publish_gh_pages.sh # publish site/ to gh-pages (git commit-tree)
└── site/               # committed static demo (GitHub Pages)
```

**Data flow.** `build_dataset()` runs once at startup: it discovers the output
folders, loads every `fit-data.fits` into `fit_data_cache`, interpolates all
stars onto a common grid (`linspace`, float32), and computes per-region χ²
summaries. Stars with fewer than 100 overlapping finite pixels are dropped
from *both* the mean stack and the χ² sample (they are reported at startup),
so plot and statistics always describe the same sample.

The spectrum itself is **not** a Dash figure: `build_spectrum_payload()`
serializes rounded wavelength/flux/model/residual arrays (non-finite → `null`
gaps) into `spectrum-data-store`, and a clientside callback feeds that plus
the live region state (`ll-entries-store`, `pending-changes-store`,
`selected-region-store`, draw mode, goto ticks, VALD stores) into
`window.WaveExplorer.sync()` in `assets/spectrum.js`, which renders SVG
directly. Static layers (grid, data paths, region bands, axes) are only
rebuilt when their inputs change; the crosshair/hover layer updates
independently per pointer frame, and all data scans binary-search the view
window. Edits flow back through small stores (`drag-result-store`,
`draw-region-store`) into server callbacks that maintain a pending-changes
dict plus an O(changed-entry) undo history, and persist on explicit save.

## full_model — on-demand full-range model spectra

`fit-data.fits` stores the model only inside the fitted line-list windows.
`full_model/` reconstructs the model over the star's full observed range by
re-running ASAP `gen_spec` at the best-fit parameters from `results.txt`,
loading only the ~16 grid corner nodes bracketing (Teff, logg, [M/H], [α/Fe])
per B-component via a temp directory of symlinks (exact — bit-identical to the
full grid, see `full_model/SPIKE_findings.md`). Fitted veiling is applied when
the run fit it.

It runs as a subprocess of the Dash app (keeps ASAP + grid memory out of the
server): `python -m wave_explorer.full_model <output_folder>` — also usable
standalone to pre-warm stars. The result is cached as `model-full.fits`
(atomic write) and invalidated when `results.txt` or `config_copy.ini` is
newer. Interpreter resolution: the app's own python if it can import ASAP,
else the asap env's python, else `conda run -n asap`.

Paths are overridable via `WAVE_EXPLORER_ASAP_PATH` (ASAP checkout) and
`WAVE_EXPLORER_GRID_PATH` (model grid); defaults point at this cluster's
locations.

**Known limitation:** the star-focus callback computes synchronously and can
hold a Dash worker for up to 600 s on a cold star (~1 min typical). Concurrent
requests for the same star are deduplicated with a per-folder lock. Moving to
`background=True` requires installing `diskcache` and wiring a
`DiskcacheManager`.

## Static demo (site/)

`scripts/export_demo.py` exports the payloads (default 730–1000 nm window,
`--only-stars` to restrict the star set) plus a JS shim so the *same*
`spectrum.js` runs without a server; the result is committed under `site/` and
published with `scripts/publish_gh_pages.sh` (uses `git commit-tree`; Pages
builds can take ~8 min). Parity between the Python and in-browser χ² recompute
is gated by `tests/test_export_demo.py` and `tests/demo_compute.test.mjs`.

## Testing

```bash
/net/vdesk/data2/cobelens/.conda/envs/asap/bin/python -m pytest tests/ full_model/tests/ -q
node tests/demo_compute.test.mjs
```

The suite exercises payload builders, callback logic (via direct function
calls), the VALD parser, teff-stack selection, the full_model driver against a
real star (oracle test asserts parity with `fit-data.fits` in fitted windows),
and the demo export parity gate. `tests/test_app_smoke.py` builds the real v2
dataset and constructs the app.

## Known limitations

- Single-user tool: independent Dash callbacks read-modify-write the pending
  stores, so two browser sessions editing simultaneously can lose one
  session's staged (unsaved) edit. Saves themselves are atomic and
  timestamped to the microsecond.
- χ² shown for a region whose bounds have pending edits is the last computed
  value (marked `*` in the table) until saved/recomputed.
- The full-range model's continuum is normalized per order, so line depths in
  unfitted zones are guidance, not fitted measurements; orders below 4001 Å
  are dropped (no grid coverage).
