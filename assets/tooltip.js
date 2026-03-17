/**
 * ASAP Cursor-Tracking Tooltip
 * 
 * Tracks mouse position and displays region statistics
 * in a tooltip that follows the cursor when hovering over fitted regions.
 */

(function() {
  'use strict';
  
  let lastCursorX = 0;
  let lastCursorY = 0;
  let llStats = [];
  let hoveredRegionIdx = null;

  function debugLog() {
    if (!window.WE_DEBUG) return;
    try {
      console.log('[wave_explorer tooltip]', ...arguments);
    } catch (e) {
      // no-op
    }
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
  
  // ══════════════════════════════════════════════════════════════
  // Utilities
  // ══════════════════════════════════════════════════════════════
  
  function formatValue(v, fmt = '.3f', fallback = '—') {
    if (v === null || v === undefined || isNaN(v)) {
      return fallback;
    }
    return parseFloat(v).toFixed(parseInt(fmt[1]));
  }
  
  // ══════════════════════════════════════════════════════════════
  // Tooltip Creation & Positioning
  // ══════════════════════════════════════════════════════════════
  
  function updateTooltip(regionIdx) {
    const tooltip = document.getElementById('cursor-tooltip');
    if (!tooltip) return;
    
    if (regionIdx === null) {
      tooltip.style.display = 'none';
      hoveredRegionIdx = null;
      return;
    }
    
    // Find region stats
    const stat = llStats.find(s => s.region_idx === regionIdx);
    if (!stat) {
      tooltip.style.display = 'none';
      return;
    }
    
    // Build HTML
    const chi2Val = stat.med_chi2!== null && stat.med_chi2 !== undefined ? stat.med_chi2 : null;
    let chi2Str = '—';
    if (chi2Val !== null) {
      chi2Str = formatValue(chi2Val, '.3f');
    }
    
    const html = `
      <div style="font-weight: bold; color: #58d1eb; margin-bottom: 4px;">
        Region #${stat.region_idx}
      </div>
      <div style="font-size: 10px; line-height: 1.4;">
        <div>λ ${formatValue(stat.lower, '.3f')} – ${formatValue(stat.upper, '.3f')} nm</div>
        <div>Center: ${formatValue(stat.center, '.3f')} nm</div>
        <div style="border-top: 1px solid rgba(88, 209, 235, 0.3); margin: 4px 0; padding-top: 4px;">
          <div>χ²/N: ${chi2Str}</div>
          <div>Stars: ${stat.n_stars || 0}</div>
          <div>Median pix: ${stat.med_npix || 0}</div>
        </div>
      </div>
    `;
    
    tooltip.innerHTML = html;
    tooltip.style.display = 'block';
    
    // Position at cursor
    const offset = 14;
    tooltip.style.left = (lastCursorX + offset) + 'px';
    tooltip.style.top = (lastCursorY - 40) + 'px';
    
    hoveredRegionIdx = regionIdx;
  }
  
  // ══════════════════════════════════════════════════════════════
  // Event Listeners
  // ══════════════════════════════════════════════════════════════
  
  function setupMouseTracking() {
    document.addEventListener('mousemove', (evt) => {
      lastCursorX = evt.clientX;
      lastCursorY = evt.clientY;
      
      // If tooltip is visible, update its position
      const tooltip = document.getElementById('cursor-tooltip');
      if (tooltip && tooltip.style.display !== 'none') {
        const offset = 14;
        tooltip.style.left = (lastCursorX + offset) + 'px';
        tooltip.style.top = (lastCursorY - 40) + 'px';
      }
    });
  }
  
  // ══════════════════════════════════════════════════════════════
  // Dash Clientside Callback Setup
  // ══════════════════════════════════════════════════════════════
  
  window.dash_clientside = window.dash_clientside || {};
  
  window.dash_clientside.show_region_tooltip = function(hoverData, llStatsStore) {
    if (!llStatsStore) {
      llStats = [];
    } else {
      llStats = llStatsStore;
    }
    
    if (!hoverData || !hoverData.points || hoverData.points.length === 0) {
      updateTooltip(null);
      return { region_idx: null };
    }
    
    // Extract region index from customdata
    const point = hoverData.points[0];
    if (point && point.customdata !== undefined && point.customdata !== null) {
      const raw = Array.isArray(point.customdata) ? point.customdata[0] : point.customdata;
      const regionIdx = parseInt(raw);
      updateTooltip(regionIdx);
      return { region_idx: Number.isFinite(regionIdx) ? regionIdx : null };
    } else {
      updateTooltip(null);
      return { region_idx: null };
    }
  };
  
  // ══════════════════════════════════════════════════════════════
  // Plotly unhover — hide tooltip when cursor leaves all traces
  // ══════════════════════════════════════════════════════════════

  function setupPlotlyUnhover() {
    const graph = getGraphDiv();
    if (!graph || typeof graph.on !== 'function') {
      debugLog('plotly_unhover bind deferred (graph not ready)');
      setTimeout(setupPlotlyUnhover, 200);
      return;
    }
    debugLog('binding plotly_unhover listener');
    graph.on('plotly_unhover', function() {
      debugLog('plotly_unhover fired');
      updateTooltip(null);
    });
  }

  // ══════════════════════════════════════════════════════════════
  // Initialization
  // ══════════════════════════════════════════════════════════════
  
  function init() {
    setupMouseTracking();
    setupPlotlyUnhover();
  }
  
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
