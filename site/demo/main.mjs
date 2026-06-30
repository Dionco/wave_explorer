// site/demo/main.mjs
// Static controller: replaces the Dash server for the wave_explorer demo.

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
  renderAll(state, { handlers, syncSpectrum, wire: null });
}

boot().catch((err) => {
  console.error(err);
  const el = document.getElementById("candidate-stats");
  if (el) el.textContent = "Failed to load demo data: " + err.message;
});
