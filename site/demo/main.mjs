// site/demo/main.mjs
// Static controller: replaces the Dash server for the wave_explorer demo.

import { customRegionChi2, residualMetrics } from "./compute.mjs";

// 1) Dash shim — installed synchronously so any spectrum.js event is captured.
const handlers = {};               // storeId -> fn(data); filled in later tasks
window.dash_clientside = window.dash_clientside || {};
window.dash_clientside.no_update = Symbol("no_update");
window.dash_clientside.set_props = (id, props) => {
  const fn = handlers[id];
  if (fn && props && "data" in props) fn(props.data);
};

const state = {
  manifest: null, meta: null, mean: null,
  llEntries: [], pending: {}, selected: null,
  drawActive: false, valdVisible: false, valdDepthMin: 0.10,
  view: "__mean__", specByView: {},   // cache loaded spectrum payloads
  gotoTick: 0,
};

async function getJSON(file) {
  const r = await fetch(`payload/${file}`);
  if (!r.ok) throw new Error(`fetch payload/${file}: ${r.status}`);
  return r.json();
}

function currentVald() {
  const spec = state.specByView[state.view];
  return (spec && spec.vald) || state.meta.vald || null;
}

// --- Region helpers (Task 7) ---

function regionBounds(idx) {
  const staged = state.pending[String(idx)];
  const e = (staged && typeof staged === "object") ? staged : state.llEntries[idx];
  return e ? [Number(e.lower), Number(e.upper)] : null;
}

async function renderSelectedStats() {
  const { renderStats, buildHistogram } = await import("./render.mjs");
  const statsEl = document.getElementById("candidate-stats");
  const histEl = document.getElementById("chi2-histogram");
  const rangeEl = document.getElementById("status-range");
  const idx = state.selected && state.selected.region_idx;
  const bounds = idx == null ? null : regionBounds(idx);
  if (!bounds) {
    statsEl.textContent = "Click a region in the spectrum to see statistics.";
    rangeEl.textContent = "";
    const vals = state.meta.region_summary.map((r) => r.med_chi2).filter(Number.isFinite);
    histEl.innerHTML = buildHistogram(vals, `${vals.length} fitted regions`);
    return;
  }
  let [lo, hi] = bounds;
  const c = customRegionChi2(state.meta.fitpix, lo, hi);
  const rs = residualMetrics(state.meta.common_w, state.meta.mean_resid, state.meta.std_resid, lo, hi);
  if (!Number.isFinite(c.median_chi2)) {
    statsEl.innerHTML = `<div style="font-family:monospace;font-size:11px;color:#75705f">λ  ${lo.toFixed(3)} – ${hi.toFixed(3)} nm</div>`
      + `<div style="color:#9c9684;margin-top:8px;font-size:13px">No fitted pixels in this interval.</div>`;
    rangeEl.textContent = `${lo.toFixed(3)} – ${hi.toFixed(3)} nm  ·  no fitted pixels`;
    return;
  }
  statsEl.innerHTML = renderStats(c, rs, lo, hi);
  histEl.innerHTML = buildHistogram(c.per_star_chi2, `Region #${idx + 1}  ·  ${c.n_stars} stars`, "star");
  rangeEl.textContent = `${lo.toFixed(3)} – ${hi.toFixed(3)} nm  ·  χ²/N = ${c.median_chi2.toFixed(3)}`;
}

function showSelectedChip(idx) {
  const cont = document.getElementById("selected-region-container");
  if (idx == null) { cont.style.display = "none"; return; }
  cont.style.display = "";
  document.getElementById("selected-region-label").textContent = `Region #${idx + 1}`;
}

// register the store handler (fires when spectrum.js / keyboard.js click a region)
handlers["selected-region-store"] = (data) => {
  state.selected = data;            // {region_idx} or null
  showSelectedChip(data ? data.region_idx : null);
  syncSpectrum();                   // re-highlight in the plot
  renderSelectedStats();
};

// table navigation wiring (passed into renderAll)
function wire() {
  document.getElementById("table-body").addEventListener("click", (ev) => {
    const navBtn = ev.target.closest("[data-nav]");
    const row = ev.target.closest("[data-region]");
    const idx = navBtn ? Number(navBtn.dataset.nav) : (row ? Number(row.dataset.region) : null);
    if (idx == null) return;
    state.selected = { region_idx: idx };
    state.gotoTick += 1;
    showSelectedChip(idx);
    syncSpectrum({ region_idx: idx, tick: state.gotoTick });   // spectrum.js frames the region
    renderSelectedStats();
  });
  document.getElementById("selected-clear-btn").addEventListener("click", () => {
    state.selected = null;
    document.getElementById("selected-region-container").style.display = "none";
    syncSpectrum();
    renderSelectedStats();
  });
}

// Push the full state into spectrum.js. Single source of truth for the plot.
export function syncSpectrum(goto = null) {
  const spec = state.specByView[state.view];
  window.WaveExplorer.sync(
    spec, state.llEntries, state.pending, state.selected,
    state.drawActive, goto, currentVald(), state.valdVisible, state.valdDepthMin,
  );
}

async function boot() {
  state.manifest = await getJSON("manifest.json");
  state.meta = await getJSON("meta.json");
  state.mean = await getJSON("mean.json");
  state.specByView["__mean__"] = state.mean;
  state.llEntries = state.meta.ll_entries.map((e) => ({ ...e }));

  // heatstrip needs λ-bounds on its wrapper before heatstrip.js reads them
  const hs = document.getElementById("heatstrip");
  hs.dataset.lmin = String(state.manifest.lambdaMin);
  hs.dataset.lmax = String(state.manifest.lambdaMax);

  syncSpectrum();                  // render the mean spectrum
  // Task 6 fills header/heatstrip/histogram/table; Task 7+ wire handlers.
  const { renderAll } = await import("./render.mjs");
  renderAll(state, { handlers, syncSpectrum, wire });
}

boot().catch((err) => {
  console.error(err);
  const el = document.getElementById("candidate-stats");
  if (el) el.textContent = "Failed to load demo data: " + err.message;
});
