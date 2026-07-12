# Teff-Stack Mode — Design

**Date**: 2026-06-11
**Status**: Approved design, pending implementation plan

## Summary

A new CLI-activated mode for wave_explorer that, instead of averaging all
stars pixel-by-pixel into one mean spectrum, picks N stars (default 10)
spanning the retrieved Teff range and renders them **stacked with vertical
offsets** — a visual temperature sequence. Region curation (add / adjust /
exclude / save) stays fully active. All χ² statistics are computed over the
N displayed stars, and per-star region usage (regions filtered out for some
stars by the filtering workflow) is made visible both in the traces and in a
redesigned tooltip.

## Activation

```bash
python -m wave_explorer --suffix <suffix> --stack-teff        # 10 stars
python -m wave_explorer --suffix <suffix> --stack-teff 8      # custom count
python -m wave_explorer --suffix <suffix> --stack-teff --stack-offset 0.6
```

- `--stack-teff [N]` — optional int, `nargs="?"`, `const=10`. Absent → app
  behaves exactly as today (mean view).
- `--stack-offset Δ` — vertical spacing between consecutive stars in
  normalized-flux units. Default `0.5`.

## Star selection (backend, no FITS loading)

1. Discover `output_*_<suffix>` folders via the existing
   `discover_output_folders()`.
2. Parse Teff from each folder's `results.txt`
   (`flt : teff : <value> <err>` line). Missing/unparseable Teff → star
   skipped, startup warning printed.
3. **Dedup duplicate-named star dirs** (e.g. `gl_15a` vs `gl15a`): normalize
   slugs by stripping underscores (lowercase compare); among duplicates keep
   the folder whose `results.txt` has the newest mtime; print dropped
   duplicates at startup.
4. **Even-Teff spread pick**: sort candidates by Teff; compute N evenly
   spaced target temperatures from min(Teff) to max(Teff) (endpoints always
   included); greedily assign each target its nearest unused star. Fewer
   than N usable stars → take all, warn.
5. Startup banner lists the chosen stars with their Teffs.

## Data pipeline

- Load `fit-data.fits` for the picked stars only. If one fails to load,
  fall back to the next-nearest-Teff unused candidate (warn). If none load,
  abort with a clear error (mirrors the current "No valid fit-data.fits"
  failure).
- Build the common wavelength grid over the picked stars (existing
  machinery: `flatten_full_spectrum` + `interp_to_common_grid` +
  `smooth_nan`), but **no averaging** — keep per-star obs and fit arrays.
- **Full-range fit traces** (changed 2026-06-11, user decision): the model in
  `fit-data.fits` is finite on every pixel, so each star's fit trace spans the
  star's entire observed range — it is NOT masked to the fitted windows.
  Per-star region usage is conveyed by the tooltip's per-star ✓/✗ table
  (`perStar`, from `idxtofit` pixel counts) instead of trace gaps. The
  masking helpers (`fitted_ranges_for_star`, `mask_to_ranges`) remain as
  tested utilities.
- Line list resolution unchanged (`resolve_line_list_path` over the picked
  stars' configs).

## Statistics (scope: the N displayed stars)

- Region summary / band coloring / region table: existing
  `summarize_region_chi2` run on the N-star `fit_data_cache`.
- **Per-region × per-star matrix**: for every line-list region and every
  displayed star, `compute_region_chi2_for_star()` → (χ²/N, npix).
  `npix == 0` ⇒ region filtered out for that star. Shipped in the payload
  for tooltips.
- Custom drawn regions: existing `compute_custom_region_chi2` on the N-star
  cache — its `per_star_chi2` output is automatically consistent with the
  displayed stars.

## Payload (new variant, same `spectrum-data-store`)

```js
{
  stacked: true,
  wavelengths: [...],            // common grid
  stars: [                       // sorted by Teff ascending
    { slug, teff, offset,        // offset = i * Δ
      flux: [...], fitFlux: [...] },   // fitFlux NaN where not fitted
    ...
  ],
  lambdaMin, lambdaMax,
  // existing region metadata (_build_region_metadata), extended with
  // per-star stats per region:
  regions: [ { idx, chi2, n_stars, n_pix,
               perStar: [ { slug, chi2, npix }, ... ] }, ... ],
  chi2Thresholds, elementColors, elementColorFallback,
}
```

Size ≈ 10× the mean-view payload (a few MB) — acceptable for a local app.

## Rendering (`spectrum.js` learns the stacked variant)

- **No residual panel** in stacked mode; the main panel takes the full
  height. Y-axis label: "normalized flux + offset".
- Stars sorted by Teff, **coolest at the bottom**, star *i* drawn at
  `flux + i·Δ`.
- Per star, two traces: observed in the neutral obs color (same for all
  stars), **fit colored by a Teff colormap** (cool = red → hot = blue).
  Fit traces span each star's full observed range (see Data pipeline).
- **Pinned label at the left edge** of each star's baseline:
  `<slug> · <Teff> K`. Stays visible while panning/zooming.
- Pan / zoom / y-autoscale work as today over the larger y-range.
- Region bands, χ² coloring, heatstrip, VALD overlay (+ depth slider),
  keyboard navigation: unchanged.

## Tooltip (stacked mode)

- Header: the star **nearest the cursor vertically**, with name, Teff, and
  obs/fit values at the cursor wavelength. That star's traces get a subtle
  highlight.
- Inside a line-list region, append the region block: # / element / bounds /
  median χ²/N over the N stars, then an **N-row per-star table**:
  `star · used ✓/✗ · χ²/N`. Hovered star's row highlighted; filtered-out
  stars (✗) dimmed.
- Outside regions: star header only (plus VALD line info as today).

## Region editing — fully active

Edge-drag adjust, draw-mode add (candidate panel stats now reflect the N
stars), exclude / restore, region table, heatstrip, save-curated-list: all
existing callbacks reused unchanged. Recomputation paths already accept a
`fit_data_cache`, which in this mode simply contains the N stars.

## Hidden in stacked mode

- `star-select` dropdown and the full-model spinner (single-star full-range
  focus does not apply).

## Error handling

| Failure | Behavior |
|---|---|
| results.txt missing / no teff line | star skipped, warning |
| duplicate star names | normalized-name dedup, newest results.txt wins, warning |
| < N usable stars | use all, warning |
| fit-data.fits load failure | substitute next-nearest-Teff candidate, warning |
| zero stars load | abort with clear error |

## Testing

- pytest units (synthetic data, no real FITS):
  - results.txt Teff parser
  - dedup rule (normalized names, mtime winner)
  - even-Teff picker (endpoints included, greedy nearest, < N fallback)
  - stacked payload builder: offsets, Teff sort order, full-range fit from
    idxtofit, per-region per-star matrix, strict-JSON (no NaN leaks —
    non-finite → null)
- JS side verified by running the app against `06_retrievals`.

## Out of scope

- Single-star full-range model (model-full.fits) integration in stacked mode.
- Interactive re-picking of stars from within the UI (restart with a
  different `--stack-teff` / future `--stack-stars` list instead).
- Per-star residual display.
