// site/demo/render.mjs
import { C, chi2Color, chi2Label, chi2Tier, chi2Pct, fmt } from "./theme.mjs";

const esc = (s) => String(s).replace(/[&<>"]/g, (c) =>
  ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

export function buildHistogram(values, subtitle, unit = "region") {
  const binW = 2.0, nBins = 22;
  const bins = new Array(nBins).fill(0);
  const vals = (values || []).filter((v) => v != null && Number.isFinite(+v));
  for (const v of vals) bins[Math.min(nBins - 1, Math.max(0, Math.trunc(v / binW)))]++;
  const peak = Math.max(1, ...bins);
  const bars = bins.map((count, i) => {
    const h = ((count / peak) * 100).toFixed(1);
    const bg = chi2Color((i + 0.5) * binW);
    return `<div class="hist-bar" title="χ²/N ${i*binW}–${(i+1)*binW}${i===nBins-1?'+':''} · ${count} ${unit}${count===1?'':'s'}">`
      + `<div class="hist-bar-fill" style="height:${h}%;background:${bg}"></div></div>`;
  }).join("");
  return `<div class="hist-card"><div class="hist-head">`
    + `<span class="eyebrow">χ²/N distribution</span><span class="subtitle">${esc(subtitle)}</span></div>`
    + `<div class="hist-bars">${bars}</div>`
    + `<div class="hist-legend">`
    + `<div class="legend-item"><span class="legend-swatch" style="background:${C.green}"></span>good</div>`
    + `<div class="legend-item"><span class="legend-swatch" style="background:${C.amber}"></span>fair</div>`
    + `<div class="legend-item"><span class="legend-swatch" style="background:${C.orange}"></span>poor</div>`
    + `<div class="legend-item"><span class="legend-swatch" style="background:${C.red}"></span>bad</div></div></div>`;
}

export function renderStats(chi2, resid, lo, hi) {
  const c2 = chi2.median_chi2, color = chi2Color(c2), label = chi2Label(c2), pct = chi2Pct(c2);
  const block = (key, body) => `<div class="stat-block"><div class="stat-key">${key}</div>${body}</div>`;
  const rrow = (k, v) => `<div class="resid-row"><span class="rr-key">${k}</span><span class="rr-val">${v}</span></div>`;
  return `<div>
    <div style="font-family:${C.MONO||"monospace"};font-size:11px;color:${C.muted};margin-bottom:12px;background:${C.bg};padding:6px 10px;border-radius:5px;border:1px solid ${C.border2}">
      λ  ${lo.toFixed(3)} – ${hi.toFixed(3)} nm  ·  Δλ = ${(hi-lo).toFixed(3)} nm</div>
    <div class="stat-grid">
      ${block("χ²/N  median",
        `<div style="display:flex;align-items:baseline;gap:6px">
           <div class="stat-val" style="color:${color}">${fmt(c2, 3)}</div>
           <span><span class="quality-badge" style="color:${color};background:${color}22;border:1px solid ${color}44">${label}</span></span>
         </div>
         <div class="chi2-track"><div class="chi2-fill" style="width:${pct}%;background:${color}"></div></div>`)}
      ${block("χ²/N  16–84%", `<div class="stat-val" style="font-size:14px;color:${C.text}">${fmt(chi2.p16_chi2,2)} – ${fmt(chi2.p84_chi2,2)}</div>`)}
      ${block("Stars", `<div><span class="stat-val" style="color:${C.cyan}">${chi2.n_stars}</span><span class="stat-unit"> ★</span></div>`)}
      ${block("Median pix/star", `<div><span class="stat-val" style="color:${C.text}">${chi2.med_npix}</span><span class="stat-unit"> px</span></div>`)}
    </div>
    <div class="divider"></div>
    <div style="font-family:monospace;font-size:10px;letter-spacing:.1em;text-transform:uppercase;color:${C.dim};margin-bottom:8px">Residual diagnostics</div>
    <div class="resid-grid">
      ${rrow("mean", fmt(resid.mean_resid, 4, true))}
      ${rrow("|mean|", fmt(resid.mean_abs_resid, 4))}
      ${rrow("|p95|", fmt(resid.p95_abs_resid, 4))}
      ${rrow("|res|/σ  mean", fmt(resid.mean_norm_resid, 3))}
      ${rrow("grid pts", String(resid.n_grid || 0))}
    </div></div>`;
}

export function renderTableRows(rows, llEntries) {
  return rows.slice(0, 50).map((row, i) => {
    const col = chi2Color(row.med_chi2);
    const ri = row.region_idx ?? i;
    const excluded = !!(llEntries[ri] && llEntries[ri].excluded);
    const trCls = excluded ? ' class="asap-row-excluded"' : "";
    return `<tr data-region="${ri}"${trCls}>
      <td class="rank-num">${i + 1}</td>
      <td>${row.center.toFixed(3)}</td>
      <td>${row.lower.toFixed(3)} – ${row.upper.toFixed(3)}</td>
      <td style="color:${col};font-weight:700">${row.med_chi2.toFixed(3)}</td>
      <td><span class="q-badge q-${chi2Tier(row.med_chi2)}">${chi2Label(row.med_chi2)}</span></td>
      <td>${row.n_stars}</td>
      <td>${row.med_npix}</td>
      <td><button class="btn btn-xs btn-cyan" data-nav="${ri}" title="Navigate to region">→</button></td>
    </tr>`;
  }).join("");
}

function headerChips(m) {
  const chip = (cls, label, val) => `<div class="h-chip ${cls}">${label} <span class="hc-val">${esc(val)}</span></div>`;
  return chip("c-cyan", "suffix", m.suffix)
    + chip("c-green", "stars", m.nStars)
    + chip("", "λ", `${m.lambdaMin.toFixed(1)} – ${m.lambdaMax.toFixed(1)} nm`)
    + chip("", "ll regions", m.nRegions);
}

export function renderAll(state, ctx) {
  const m = state.manifest, meta = state.meta;
  document.getElementById("header-chips").innerHTML = headerChips(m);
  document.getElementById("status-summary").textContent =
    `Wave Explorer · ASAP · ${m.suffix} · ${m.nStars} stars · ${m.nRegions} regions`;

  // default histogram = median χ²/N of every fitted region
  const defaultVals = meta.region_summary.map((r) => r.med_chi2).filter(Number.isFinite);
  document.getElementById("chi2-histogram").innerHTML =
    buildHistogram(defaultVals, `${defaultVals.length} fitted regions`);

  // heatstrip blocks (build_heatstrip_regions port)
  const span = Math.max(1e-6, m.lambdaMax - m.lambdaMin);
  const chi2Map = new Map(meta.region_summary.map((r) => [r.region_idx, r.med_chi2]));
  document.getElementById("heatstrip-regions").innerHTML = state.llEntries.map((e, idx) => {
    const left = ((e.lower - m.lambdaMin) / span) * 100;
    const width = Math.max(0.18, ((e.upper - e.lower) / span) * 100);
    const c2 = chi2Map.get(idx);
    const bg = c2 != null ? chi2Color(c2) : C.dim;
    return `<div class="heatstrip-region${e.excluded ? " excluded" : ""}" style="left:${left.toFixed(4)}%;width:${width.toFixed(4)}%;background:${bg}"></div>`;
  }).join("");

  // worst-regions table
  document.getElementById("table-body").innerHTML =
    renderTableRows(meta.region_summary, state.llEntries);

  // star-select options
  document.getElementById("star-select").innerHTML =
    m.views.map((v) => `<option value="${esc(v.id)}">${esc(v.label)}</option>`).join("");

  ctx.wire && ctx.wire();          // handler wiring added in Task 7+
}
