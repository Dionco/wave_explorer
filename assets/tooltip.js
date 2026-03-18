/**
 * ASAP Cursor-Tracking Tooltip
 *
 * Tracks mouse position and displays region statistics
 * in a tooltip that follows the cursor when hovering over fitted regions.
 *
 * FIX: Tooltip now binds DIRECTLY to plotly_hover / plotly_unhover events.
 * Previously the display path went through the Dash clientside-callback system,
 * which introduced enough async delay that plotly_unhover (synchronous) always
 * fired first and hid the tooltip before it ever appeared.
 */

(function () {
  'use strict';

  let lastCursorX = 0;
  let lastCursorY = 0;
  let llStats = [];       // populated by Dash clientside callback
  let _plotlyBound = false;

  // ── Helpers ──────────────────────────────────────────────────────────────

  function debugLog() {
    if (!window.WE_DEBUG) return;
    try { console.log('[wave_explorer tooltip]', ...arguments); } catch (_) {}
  }

  function getGraphDiv() {
    const host = document.getElementById('spectrum-graph');
    if (!host) return null;
    if (typeof host.on === 'function' && host._fullLayout) return host;
    const inner = host.querySelector('.js-plotly-plot');
    if (inner && typeof inner.on === 'function' && inner._fullLayout) return inner;
    if (inner && typeof inner.on === 'function') return inner;
    return (typeof host.on === 'function') ? host : null;
  }

  function formatValue(v, decimals, fallback) {
    fallback = fallback || '—';
    if (v === null || v === undefined || (typeof v === 'number' && isNaN(v))) return fallback;
    return parseFloat(v).toFixed(decimals);
  }

  // ── Tooltip DOM ───────────────────────────────────────────────────────────

  function positionTooltip() {
    const tooltip = document.getElementById('cursor-tooltip');
    if (!tooltip || tooltip.style.display === 'none') return;
    const offset = 16;
    // Keep tooltip inside viewport horizontally
    const tooltipWidth = tooltip.offsetWidth || 220;
    let left = lastCursorX + offset;
    if (left + tooltipWidth > window.innerWidth - 8) {
      left = lastCursorX - tooltipWidth - offset;
    }
    tooltip.style.left = left + 'px';
    tooltip.style.top  = (lastCursorY - 44) + 'px';
  }

  function updateTooltip(regionIdx) {
    const tooltip = document.getElementById('cursor-tooltip');
    if (!tooltip) return;

    if (regionIdx === null || regionIdx === undefined) {
      tooltip.style.display = 'none';
      return;
    }

    // Look up stats — works whether regionIdx is 0-based or 1-based
    // ll_hover_stats stores region_idx as 1-based (from data_processing.py)
    const stat = llStats.find(function (s) { return s.region_idx === regionIdx; });

    if (!stat) {
      debugLog('no stat found for regionIdx', regionIdx, '— llStats length:', llStats.length);
      tooltip.style.display = 'none';
      return;
    }

    const chi2Str = (stat.med_chi2 !== null && stat.med_chi2 !== undefined)
      ? formatValue(stat.med_chi2, 3)
      : '—';

    const chi2Color = (function (v) {
      if (v === null || v === undefined) return '#7d8590';
      if (v < 1.5) return '#3fb950';
      if (v < 3.0) return '#ffa726';
      if (v < 6.0) return '#fb8f44';
      return '#f85149';
    })(stat.med_chi2);

    tooltip.innerHTML =
      '<div style="font-weight:700;color:#58d1eb;margin-bottom:5px;font-size:12px;">' +
        'Region\u00a0#' + stat.region_idx + '\u00a0\u00b7\u00a0' + stat.element + '\u00a0' + stat.ion +
      '</div>' +
      '<div style="font-size:11px;line-height:1.55;">' +
        '<div>\u03bb\u00a0' + formatValue(stat.lower, 3) + '\u00a0\u2013\u00a0' + formatValue(stat.upper, 3) + '\u00a0nm</div>' +
        '<div style="border-top:1px solid rgba(88,209,235,0.25);margin:5px 0 4px;">' +
          '<span style="color:#7d8590;">\u03c7\u00b2/N\u00a0</span>' +
          '<span style="color:' + chi2Color + ';font-weight:700;">' + chi2Str + '</span>' +
        '</div>' +
        '<div><span style="color:#7d8590;">Stars\u00a0</span>' + (stat.n_stars || 0) + '</div>' +
        '<div><span style="color:#7d8590;">Med\u00a0pix\u00a0</span>' + (stat.med_npix || 0) + '</div>' +
        (stat.mean_resid !== null && stat.mean_resid !== undefined
          ? '<div><span style="color:#7d8590;">Mean\u00a0resid\u00a0</span>' + formatValue(stat.mean_resid, 4) + '</div>'
          : '') +
      '</div>';

    tooltip.style.display = 'block';
    positionTooltip();
  }

  // ── Mouse tracking ────────────────────────────────────────────────────────

  function setupMouseTracking() {
    document.addEventListener('mousemove', function (evt) {
      lastCursorX = evt.clientX;
      lastCursorY = evt.clientY;
      positionTooltip();
    });
  }

  // ── Direct Plotly event binding (PRIMARY display path) ────────────────────
  //
  // This replaces the previous approach of relying on the Dash clientside
  // callback to show the tooltip.  Dash's async update cycle means
  // plotly_unhover (synchronous) always fired first, hiding the tooltip
  // before the show-path could run.

  function setupPlotlyListeners(attempt) {
    const graph = getGraphDiv();
    if (!graph || typeof graph.on !== 'function') {
      if ((attempt || 0) < 80) {
        setTimeout(function () { setupPlotlyListeners((attempt || 0) + 1); }, 150);
      } else {
        debugLog('gave up waiting for Plotly graph div');
      }
      return;
    }

    if (_plotlyBound) return;
    _plotlyBound = true;

    debugLog('binding plotly_hover / plotly_unhover');

    graph.on('plotly_hover', function (evt) {
      const point = evt && evt.points && evt.points[0];
      if (!point) {
        updateTooltip(null);
        return;
      }

      const raw = Array.isArray(point.customdata) ? point.customdata[0] : point.customdata;
      if (raw === null || raw === undefined) {
        updateTooltip(null);
        return;
      }

      const regionIdx = parseInt(raw, 10);
      debugLog('plotly_hover regionIdx', regionIdx, 'llStats.length', llStats.length);

      if (Number.isFinite(regionIdx)) {
        updateTooltip(regionIdx);
      } else {
        updateTooltip(null);
      }
    });

    graph.on('plotly_unhover', function () {
      debugLog('plotly_unhover fired');
      updateTooltip(null);
    });
  }

  // ── Dash clientside callback (stats sync only, NOT display trigger) ───────
  //
  // This function is still registered so the existing Dash callback in app.py
  // continues to work — but its only job is now to keep `llStats` up to date.
  // Displaying/hiding the tooltip is handled entirely by the Plotly listeners above.

  window.dash_clientside = window.dash_clientside || {};

  window.dash_clientside.show_region_tooltip = function (hoverData, llStatsStore) {
    // Sync stats array whenever Dash pushes a new store snapshot
    if (llStatsStore && Array.isArray(llStatsStore)) {
      llStats = llStatsStore;
      debugLog('llStats synced via Dash callback, count:', llStats.length);
    }

    // Also handle hide via Dash path (belt-and-suspenders)
    if (!hoverData || !hoverData.points || hoverData.points.length === 0) {
      updateTooltip(null);
      return { region_idx: null };
    }

    const point = hoverData.points[0];
    if (!point || point.customdata === null || point.customdata === undefined) {
      updateTooltip(null);
      return { region_idx: null };
    }

    const raw = Array.isArray(point.customdata) ? point.customdata[0] : point.customdata;
    const regionIdx = parseInt(raw, 10);
    if (Number.isFinite(regionIdx)) {
      updateTooltip(regionIdx);
      return { region_idx: regionIdx };
    }

    updateTooltip(null);
    return { region_idx: null };
  };

  // Expose for external callers (drag_handles.js hover sync)
  window.updateTooltipForRegion = updateTooltip;

  // ── Init ──────────────────────────────────────────────────────────────────

  function init() {
    setupMouseTracking();
    setupPlotlyListeners(0);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }

})();