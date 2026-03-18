/**
 * ASAP Cursor-Tracking Tooltip
 *
 * Reads window.__llStatsData (embedded inline in the HTML by layout.py)
 * on init — no dependency on the Dash callback pipeline or timing.
 */

(function() {
  'use strict';

  let lastCursorX = 0;
  let lastCursorY = 0;
  let llStats     = [];

  function debugLog() {
    if (!window.WE_DEBUG) return;
    try { console.log('[wave_explorer tooltip]', ...arguments); } catch (e) {}
  }

  function getGraphDiv() {
    const host = document.getElementById('spectrum-graph');
    if (!host) return null;
    if (typeof host.on === 'function' && host._fullLayout) return host;
    const inner = host.querySelector('.js-plotly-plot');
    if (inner && typeof inner.on === 'function') return inner;
    return (typeof host.on === 'function') ? host : null;
  }

  function formatValue(v, decimals, fallback) {
    if (v === null || v === undefined || isNaN(v)) return fallback || '—';
    return parseFloat(v).toFixed(decimals);
  }

  // ── Tooltip render ─────────────────────────────────────────────────────────

  function updateTooltip(regionIdx) {
    const tooltip = document.getElementById('cursor-tooltip');
    if (!tooltip) return;

    if (regionIdx === null || regionIdx === undefined) {
      tooltip.style.display = 'none';
      return;
    }

    const stat = llStats.find(s => s.region_idx === regionIdx);
    if (!stat) {
      tooltip.style.display = 'none';
      return;
    }

    const chi2Str = stat.med_chi2 !== null && stat.med_chi2 !== undefined
      ? formatValue(stat.med_chi2, 3) : '—';

    tooltip.innerHTML = `
      <div style="font-weight:bold;color:#58d1eb;margin-bottom:4px">
        Region #${stat.region_idx}
      </div>
      <div style="font-size:10px;line-height:1.5">
        <div>λ ${formatValue(stat.lower, 3)} – ${formatValue(stat.upper, 3)} nm</div>
        <div>Center: ${formatValue(stat.center, 3)} nm</div>
        <div style="border-top:1px solid rgba(88,209,235,0.3);margin:4px 0;padding-top:4px">
          <div>χ²/N: ${chi2Str}</div>
          <div>Stars: ${stat.n_stars || 0}</div>
          <div>Median pix: ${stat.med_npix || 0}</div>
        </div>
      </div>`;

    tooltip.style.display = 'block';
    tooltip.style.left    = (lastCursorX + 14) + 'px';
    tooltip.style.top     = (lastCursorY - 40) + 'px';
  }

  // ── Mouse tracking ─────────────────────────────────────────────────────────

  function setupMouseTracking() {
    document.addEventListener('mousemove', (evt) => {
      lastCursorX = evt.clientX;
      lastCursorY = evt.clientY;
      const tooltip = document.getElementById('cursor-tooltip');
      if (tooltip && tooltip.style.display !== 'none') {
        tooltip.style.left = (lastCursorX + 14) + 'px';
        tooltip.style.top  = (lastCursorY - 40) + 'px';
      }
    });
  }

  // ── Dash clientside callback (still works when called, but no longer required) ──

  window.dash_clientside = window.dash_clientside || {};

  window.dash_clientside.show_region_tooltip = function(hoverData, llStatsStore) {
    // Update local cache if the Dash store provides fresher data.
    if (llStatsStore && llStatsStore.length) {
      llStats = llStatsStore;
    }

    if (!hoverData || !hoverData.points || !hoverData.points.length) {
      updateTooltip(null);
      return { region_idx: null };
    }

    const point = hoverData.points[0];
    if (point && point.customdata !== undefined && point.customdata !== null) {
      const raw       = Array.isArray(point.customdata) ? point.customdata[0] : point.customdata;
      const regionIdx = parseInt(raw);
      updateTooltip(Number.isFinite(regionIdx) ? regionIdx : null);
      return { region_idx: Number.isFinite(regionIdx) ? regionIdx : null };
    }

    updateTooltip(null);
    return { region_idx: null };
  };

  // ── Plotly unhover ─────────────────────────────────────────────────────────

  function setupPlotlyUnhover(attempt) {
    const graph = getGraphDiv();
    if (!graph || typeof graph.on !== 'function') {
      if (attempt < 60) setTimeout(() => setupPlotlyUnhover(attempt + 1), 200);
      return;
    }
    debugLog('binding plotly_unhover listener');
    graph.on('plotly_unhover', () => {
      debugLog('plotly_unhover fired');
      updateTooltip(null);
    });
  }

  // ── Initialisation ─────────────────────────────────────────────────────────

  function init() {
    setupMouseTracking();
    setupPlotlyUnhover(0);

    // Read stats from the inline script that layout.py embeds in the HTML.
    // This is synchronous — available before any callback fires.
    if (window.__llStatsData && window.__llStatsData.length) {
      llStats = window.__llStatsData;
      debugLog('init: loaded llStats from __llStatsData', { count: llStats.length });
    } else {
      debugLog('init: __llStatsData not ready — will rely on Dash callback');
    }
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }

})();