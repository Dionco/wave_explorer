# Task 1 Spike — Findings (gl_382, real data)

Status: **GO**. The corner-load approach is verified against real data.

## Step 1 — `load_obs` / order structure
`SA.load_obs(file)` returns 4 items:
- `med_wvl`, `med_spectrum`, `med_err`: **2D, shape (40, 6642)** = (n_orders, n_pix_per_order), Angstrom.
- `radvel`: scalar.

So the spectrum is already **per-order (40 echelle orders)**. There is NO `SA.orders`
attribute. **"Full-order regions" = use these 40 rows directly**: `regions[o] = [wvl[o][0],
wvl[o][-1]]`, `nan_mask = ones`. No order-boundary discovery needed.

Order wavelength coverage: order 0 ≈ 3698–3836 Å … order 39 ≈ 10078–10487 Å.

## Step 2 — array contract from a normal windowed load
Loaded grid `/net/vdesk/data2/cobelens/MRP/new/grid_models/hdf5-narval-full/` (1651 files,
**no grid.info** → ASAP's oldstyle loader lists the dir).

- `regions` shape (17, 2); `obs_wvl` (17, 1257).
- **`SA.grid_n` shape (11, 10, 3, 5, 1, 17, 2297)** with dim order
  **[B(0), teff(1), logg(2), mh(3), alpha(4), region(5), wave(6)]** — confirmed matches
  `(d5, d1, d2, d3, d4, d6, d7)`.
- `SA.nwvls` shape (17, 2297) = **(region, wave), parameter-INDEPENDENT** (unchanged when
  slicing grid by parameter nodes).
- Axes: teffs 3000..3900 step 100; loggs [4.5,5.0,5.5]; mhs [-0.5..0.5 step .25];
  alphas [0.0] (single node); bs [0..10] kG (11 field components).
- **`SA.diskIntegrationMode = 0`** → the active model is `gen_spec_int_spectra`
  (NOT `gen_spec_mu`; this grid is loaded by the oldstyle loader, no mu disk-integration).
- `SA.adjcont = True`.

## Step 3 — KEY TEST: corner-slice reproduces the windowed FIT
Best-fit (results.txt via `read_res_v2`): teff=3528.32, logg=4.659, mh=0.250, afe=0.0,
rv=-0.139, vsini=3.266, vmac=0.0, mag_ff = 11-vector (sum≈1.0).

Bracketing nodes: teff[3500,3600], logg[4.5,5.0], mh[0.25,0.5], alpha[0.0 single].
Corner grid `grid_n2` shape (11, 2, 2, 2, 1, 17, 2297).

Slicing recipe (dim order above):
```python
grid_n2 = SA.grid_n[:, it_idx][:, :, il_idx][:, :, :, im_idx][:, :, :, :, ia_idx]
```
then `gen_spec(..., SA.nwvls, grid_n2, coeffs, T,L,M,A, teffs2,loggs2,mhs2,alphas2, ...)`.

**Result: max abs diff = 0.000e+00, median = 0.000e+00 over all 21369 finite points.**
The corner-sliced model is **bit-identical** to the full-grid model. The interpolator only
ever uses the bracketing nodes, so restricting the grid to them is exact.

## Implications for the plan
1. **Grid path:** `config_copy.ini` `pathToGrid` is stale (`asap/asap_v0.1_example/...`,
   missing). Real grid: `grid_models/hdf5-narval-full/`. `load_run_inputs` must accept a
   grid-path override / fallback and not trust the config value blindly.
2. **Full-order regions** are trivial (the 40 `load_obs` rows) — no `create_regions` needed
   for the full-range path.
3. **grid_n dim order is [B, teff, logg, mh, alpha, region, wave]** — locked in.
4. **diskIntegrationMode 0 (gen_spec_int_spectra)** for this grid; no mu handling required.
5. **Corner-load can reuse ASAP's own `load_grid`** by pointing it at a temp grid dir
   containing only the bracketing files (8 atmo-corners × 11 B = up to 88 files), instead
   of a hand-written h5py reader. ASAP then builds grid_n in the correct order itself.
   This de-risks Task 4 and avoids reimplementing the HDF5 read / vacuum conversion.
