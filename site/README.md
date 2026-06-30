## Static demo (GitHub Pages)

A fully interactive, server-free demo runs on preloaded `ds_leo` data at
**https://dionco.github.io/wave_explorer/**.

### Rebuild and publish

To rebuild the demo, you need the `asap` env, spectroscopy data, and model grid on your machine. From `new/obs-data-example`:

    /net/vdesk/data2/cobelens/.conda/envs/asap/bin/python -m wave_explorer.scripts.export_demo \
        --built-at "$(date +%F)" \
        --grid-path /net/vdesk/data2/cobelens/MRP/new/grid_models/hdf5-narval-full/
    node --test wave_explorer/tests/demo_compute.test.mjs   # parity gate
    bash wave_explorer/scripts/publish_gh_pages.sh

The demo is read-with-local-editing: drags/draws recompute χ² live but nothing
persists. The single-star full-range views (`ds_leo`, `gl_581`, `gj_1289`)
require a one-time `model-full.fits` precompute, handled by the export script.
