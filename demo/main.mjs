// site/demo/main.mjs
// Static controller: replaces the Dash server for the wave_explorer demo.

import { customRegionChi2, residualMetrics } from "./compute.mjs";
import { chi2Color } from "./theme.mjs";

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
  // Canonical per-region metadata {idx, chi2, n_stars, n_pix}, kept 1:1 with
  // llEntries by index. Injected into the spec on every sync so spectrum.js
  // colours/tooltips stay aligned after add/delete edits.
  regions: [],
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
    document.getElementById("chi2-histogram").innerHTML = "";
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
  const delBtn = document.getElementById("selected-delete-btn");
  if (idx == null) {
    cont.style.display = "none";
    if (delBtn) delBtn.style.display = "none";
    return;
  }
  cont.style.display = "";
  document.getElementById("selected-region-label").textContent = `Region #${idx + 1}`;
  if (delBtn) delBtn.style.display = "";   // a real region is selected → allow delete
}

// register the store handler (fires when spectrum.js / keyboard.js click a region)
handlers["selected-region-store"] = (data) => {
  state.selected = data;            // {region_idx} or null
  showSelectedChip(data ? data.region_idx : null);
  syncSpectrum();                   // re-highlight in the plot
  renderSelectedStats();
};

function refreshHeatstrip() {
  const m = state.manifest;
  const span = Math.max(1e-6, m.lambdaMax - m.lambdaMin);
  document.getElementById("heatstrip-regions").innerHTML = state.llEntries.map((e, idx) => {
    const eff = (state.pending[String(idx)] && typeof state.pending[String(idx)] === "object")
      ? state.pending[String(idx)] : e;
    const left = ((eff.lower - m.lambdaMin) / span) * 100;
    const width = Math.max(0.18, ((eff.upper - eff.lower) / span) * 100);
    const r = state.regions[idx];
    const c2 = r ? r.chi2 : null;
    const bg = (c2 != null) ? chi2Color(c2) : "#9c9684";
    return `<div class="heatstrip-region${eff.excluded ? " excluded" : ""}" style="left:${left.toFixed(4)}%;width:${width.toFixed(4)}%;background:${bg}"></div>`;
  }).join("");
}

// Rebuild the worst-regions table from the live llEntries + canonical regions
// (so add/delete are reflected). Mirrors the initial region_summary table:
// fitted regions only, sorted by χ²/N desc, top 50.
async function rebuildTable() {
  const { renderTableRows } = await import("./render.mjs");
  const rows = [];
  state.llEntries.forEach((e, i) => {
    const r = state.regions[i];
    const c2 = r ? r.chi2 : null;
    if (c2 == null || !Number.isFinite(c2)) return;
    rows.push({
      region_idx: i, center: Number(e.center), lower: Number(e.lower), upper: Number(e.upper),
      element: e.element, med_chi2: c2, n_stars: r.n_stars || 0, med_npix: r.n_pix || 0,
    });
  });
  rows.sort((a, b) => b.med_chi2 - a.med_chi2);
  document.getElementById("table-body").innerHTML = renderTableRows(rows, state.llEntries);
}

handlers["drag-result-store"] = (data) => {
  if (!data) return;
  const { region_idx, bound, new_x_nm } = data;          // bound: "lower" | "upper"
  const base = state.llEntries[region_idx];
  if (!base) return;
  const edited = { ...(state.pending[String(region_idx)] || base) };
  edited[bound] = Number(new_x_nm);
  if (edited.lower > edited.upper) { const t = edited.lower; edited.lower = edited.upper; edited.upper = t; }
  state.pending[String(region_idx)] = edited;
  syncSpectrum();                 // redraw shapes with the pending geometry
  if (state.selected && state.selected.region_idx === region_idx) renderSelectedStats();
  refreshHeatstrip();
};

// ADD: a drawn region becomes a real, visible region (new span on the spectrum
// + heatstrip block + table row), then is selected so its stats show.
handlers["draw-region-store"] = (data) => {
  if (!data) return;              // {lo, hi}
  let lo = Number(data.lo), hi = Number(data.hi);
  if (hi < lo) { const t = lo; lo = hi; hi = t; }
  const c = customRegionChi2(state.meta.fitpix, lo, hi);
  state.llEntries.push({
    center: (lo + hi) / 2, lower: lo, upper: hi,
    element: "new", ion: "1", excluded: false, added: true,
  });
  state.regions.push({
    idx: state.regions.length,
    chi2: Number.isFinite(c.median_chi2) ? c.median_chi2 : null,
    n_stars: c.n_stars, n_pix: c.med_npix,
  });
  const newIdx = state.llEntries.length - 1;
  state.selected = { region_idx: newIdx };
  state.gotoTick += 1;
  showSelectedChip(newIdx);
  refreshHeatstrip();
  rebuildTable();
  syncSpectrum({ region_idx: newIdx, tick: state.gotoTick });   // frame the new region
  renderSelectedStats();
};

// draw-mode toggle button
document.getElementById("draw-mode-toggle").addEventListener("click", () => {
  state.drawActive = !state.drawActive;
  window.activateDrawMode(state.drawActive);
  document.getElementById("draw-mode-toggle").classList.toggle("btn-primary", state.drawActive);
});

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
    showSelectedChip(null);
    syncSpectrum();
    renderSelectedStats();
  });
  // DELETE: remove the selected region (span disappears); splice llEntries +
  // regions together so the remaining indices stay aligned.
  const delBtn = document.getElementById("selected-delete-btn");
  if (delBtn) delBtn.addEventListener("click", () => {
    const idx = state.selected && state.selected.region_idx;
    if (idx == null || idx < 0 || idx >= state.llEntries.length) return;
    state.llEntries.splice(idx, 1);
    state.regions.splice(idx, 1);
    state.regions.forEach((r, i) => { r.idx = i; });   // keep idx labels contiguous
    state.pending = {};                                 // index-keyed; drop transient drags
    state.selected = null;
    showSelectedChip(null);
    refreshHeatstrip();
    rebuildTable();
    syncSpectrum();
    renderSelectedStats();
  });
}

// Push the full state into spectrum.js. Single source of truth for the plot.
export function syncSpectrum(goto = null) {
  const base = state.specByView[state.view];
  // Region metadata is view-independent (line-list windows); inject the canonical
  // array so colours/tooltips track add/delete edits regardless of which view is shown.
  const spec = (base && state.regions.length) ? { ...base, regions: state.regions } : base;
  window.WaveExplorer.sync(
    spec, state.llEntries, state.pending, state.selected,
    state.drawActive, goto, currentVald(), state.valdVisible, state.valdDepthMin,
  );
}

// Window [lo, hi] (nm) around the left-most region, with a little context, used
// to zoom a single-star view to one region instead of the whole 730-1000 nm range.
function firstRegionWindow() {
  let best = null;
  for (const e of state.llEntries) {
    const lo = Number(e.lower), hi = Number(e.upper);
    if (best == null || lo < best.lo) best = { lo, hi };
  }
  if (best == null) return null;
  const pad = 0.5;   // nm of context on each side
  return [best.lo - pad, best.hi + pad];
}

async function loadView(viewId) {
  if (!state.specByView[viewId]) {
    const v = state.manifest.views.find((x) => x.id === viewId);
    if (!v) return;
    state.specByView[viewId] = await getJSON(v.file);
  }
  state.view = viewId;
  syncSpectrum();      // spectrum.js resets to full λ-range when payload has fullRange:true
  // For a single-star full-range view, zoom straight into the first region so
  // buildPath only renders that window's points (spectrum.js culls to the view)
  // — much smoother than drawing the whole 730-1000 nm range at once.
  if (viewId !== "__mean__" && window.WaveExplorer && window.WaveExplorer.setView) {
    const win = firstRegionWindow();
    if (win) window.WaveExplorer.setView(win[0], win[1]);
  }
}

document.getElementById("star-select").addEventListener("change", (ev) => {
  loadView(ev.target.value);
});

document.getElementById("vald-toggle-btn").addEventListener("click", () => {
  state.valdVisible = !state.valdVisible;
  document.getElementById("vald-toggle-btn").classList.toggle("btn-primary", state.valdVisible);
  syncSpectrum();
});

document.getElementById("vald-depth-min-slider").addEventListener("input", (ev) => {
  state.valdDepthMin = Number(ev.target.value);
  syncSpectrum();
});

document.getElementById("demo-note").textContent = "demo · edits local to your browser";

async function boot() {
  state.manifest = await getJSON("manifest.json");
  state.meta = await getJSON("meta.json");
  state.mean = await getJSON("mean.json");
  state.specByView["__mean__"] = state.mean;
  state.llEntries = state.meta.ll_entries.map((e) => ({ ...e }));
  // Canonical region metadata, 1:1 with llEntries (set before the first sync so
  // the initial spectrum is coloured correctly).
  state.regions = (state.mean.regions || []).map((r) => ({ ...r }));

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
