/**
 * ASAP Region Edge Drag + Draw Region Logic
 *
 * Manages:
 * 1. Direct dragging of LL region edges (no SVG handles)
 * 2. Click-drag-to-draw new region mode via SVG overlay
 * 3. Confirmation popover for new regions
 *
 * STARTUP RACE FIX
 * ─────────────────
 * Dash fires the clientside callback that supplies ll-entries data almost
 * immediately after the page loads — often before this script has finished
 * executing.  The old code did:
 *
 *   if (window.updateLLEntries) { window.updateLLEntries(entries); }
 *
 * …which silently dropped the data when this script hadn't loaded yet.
 * Because ll-entries-store only changes again on an explicit Save, llEntries
 * stayed empty for the entire session.
 *
 * The fix is a two-part handshake:
 *   • app.py always writes entries to window.__llEntriesData (a plain global).
 *   • init() reads window.__llEntriesData after defining window.updateLLEntries.
 *
 * Whichever side runs first, the data is never lost.
 */

(function() {
  'use strict';

  const EDGE_HIT_TOLERANCE_PX = 16;
  const MIN_GAP_NM = 0.001;
  const PREVIEW_FILL = 'rgba(255, 167, 38, 0.20)';
  const PREVIEW_STROKE = 'rgba(245, 130, 10, 0.95)';
  const DRAG_PREVIEW_FILL = 'rgba(88, 209, 235, 0.20)';
  const DRAG_PREVIEW_STROKE = 'rgba(88, 209, 235, 0.95)';

  let llEntries = [];
  let activeEntryIdx = null;
  let plotlyListenersBound = false;
  let lastMouseClientX = null;
  let lastMouseClientY = null;

  let dragState = {
    active: false,
    regionIdx: null,
    bound: null, // 'lower' or 'upper'
    currentNm: null,
  };

  let drawState = {
    active: false,
    startX: null,
    startNm: null,
    endX: null,
    endNm: null,
    previewRect: null,
  };

  let dragPreview = {
    layer: null,
    row1Rect: null,
    row2Rect: null,
    row1Edge: null,
    row2Edge: null,
  };

  // ── Debug logging ──────────────────────────────────────────────────────────

  function debugLog() {
    if (!window.WE_DEBUG) return;
    try {
      console.log('[wave_explorer edge-drag]', ...arguments);
    } catch (e) { /* no-op */ }
  }

  // ── Plotly graph accessors ─────────────────────────────────────────────────

  function getGraphHost() {
    return document.getElementById('spectrum-graph');
  }

  function getGraphDiv() {
    const host = getGraphHost();
    if (!host) return null;
    if (host._fullLayout && typeof host.on === 'function') return host;
    const inner = host.querySelector('.js-plotly-plot');
    if (inner && inner._fullLayout) return inner;
    return inner || host;
  }

  function getPlotBounds() {
    const graph = getGraphDiv();
    if (!graph || !graph._fullLayout || !graph._fullLayout.xaxis) return null;
    return {
      graph,
      plot:   graph._fullLayout,
      xaxis:  graph._fullLayout.xaxis,
      yaxis:  graph._fullLayout.yaxis,
      yaxis2: graph._fullLayout.yaxis2,
    };
  }

  function pixelToNm(px) {
    const bounds = getPlotBounds();
    if (!bounds || !bounds.xaxis || !bounds.xaxis.p2l) return null;
    return bounds.xaxis.p2l(px);
  }

  function nmToPixel(nm) {
    const bounds = getPlotBounds();
    if (!bounds || !bounds.xaxis || !bounds.xaxis.l2p) return null;
    return bounds.xaxis.l2p(nm);
  }

  // ── Geometry helpers ───────────────────────────────────────────────────────

  function clampDraggedNm(entry, bound, candidateNm) {
    if (!entry || !Number.isFinite(candidateNm)) return null;
    const lower = parseFloat(entry.lower);
    const upper = parseFloat(entry.upper);
    if (!Number.isFinite(lower) || !Number.isFinite(upper)) return null;
    if (bound === 'lower') return Math.min(candidateNm, upper - MIN_GAP_NM);
    if (bound === 'upper') return Math.max(candidateNm, lower + MIN_GAP_NM);
    return null;
  }

  function getPlotRectPixels(bounds) {
    const plot = bounds.plot;
    return {
      left:   plot.margin.l,
      top:    plot.margin.t,
      width:  plot.width  - plot.margin.l - plot.margin.r,
      height: plot.height - plot.margin.t - plot.margin.b,
    };
  }

  function isCursorInsidePlotArea(graphRect, plotRect, clientX, clientY) {
    const x = clientX - graphRect.left;
    const y = clientY - graphRect.top;
    return x >= plotRect.left && x <= (plotRect.left + plotRect.width) &&
           y >= plotRect.top  && y <= (plotRect.top  + plotRect.height);
  }

  function findNearestEdgeFromEvent(evt) {
    if (!llEntries.length) {
      debugLog('findNearestEdge: llEntries is EMPTY — drag cannot start. Ensure window.updateLLEntries() has been called.');
      return null;
    }

    const bounds = getPlotBounds();
    if (!bounds) return null;

    const graphRect = bounds.graph.getBoundingClientRect();
    const plotRect  = getPlotRectPixels(bounds);
    if (!isCursorInsidePlotArea(graphRect, plotRect, evt.clientX, evt.clientY)) return null;

    const cursorXInGraph = evt.clientX - graphRect.left;
    let best = null;

    for (let i = 0; i < llEntries.length; i++) {
      const entry = llEntries[i];
      if (!entry) continue;

      const loPx = nmToPixel(parseFloat(entry.lower));
      const hiPx = nmToPixel(parseFloat(entry.upper));
      if (loPx === null || hiPx === null) continue;

      const loAbsPx = plotRect.left + loPx;
      const hiAbsPx = plotRect.left + hiPx;
      const loDist  = Math.abs(cursorXInGraph - loAbsPx);
      const hiDist  = Math.abs(cursorXInGraph - hiAbsPx);

      if (loDist <= EDGE_HIT_TOLERANCE_PX && (!best || loDist < best.distancePx)) {
        best = { regionIdx: i, bound: 'lower', distancePx: loDist };
      }
      if (hiDist <= EDGE_HIT_TOLERANCE_PX && (!best || hiDist < best.distancePx)) {
        best = { regionIdx: i, bound: 'upper', distancePx: hiDist };
      }
    }

    if (best) {
      debugLog('edge hit', {
        regionIdx: best.regionIdx,
        bound: best.bound,
        distancePx: Number(best.distancePx.toFixed(2)),
      });
    }
    return best;
  }

  // ── SVG drag preview ───────────────────────────────────────────────────────

  function getDragOverlaySvg() {
    return document.getElementById('drag-handles-svg');
  }

  function getAxisBandPx(plotRect, axisObj) {
    const domain = (axisObj && axisObj.domain && axisObj.domain.length === 2)
      ? axisObj.domain : [0, 1];
    const yTop    = plotRect.top + (1.0 - domain[1]) * plotRect.height;
    const yBottom = plotRect.top + (1.0 - domain[0]) * plotRect.height;
    return { y: yTop, height: Math.max(0, yBottom - yTop) };
  }

  function ensureDragPreviewLayer() {
    if (dragPreview.layer) return dragPreview.layer;
    const svg = getDragOverlaySvg();
    if (!svg) return null;

    const layer = document.createElementNS('http://www.w3.org/2000/svg', 'g');
    layer.id = 'edge-drag-preview-layer';
    layer.style.display = 'none';
    layer.style.pointerEvents = 'none';

    const makeRect = () => {
      const rect = document.createElementNS('http://www.w3.org/2000/svg', 'rect');
      rect.setAttribute('fill', DRAG_PREVIEW_FILL);
      rect.setAttribute('stroke', DRAG_PREVIEW_STROKE);
      rect.setAttribute('stroke-width', '1.5');
      return rect;
    };

    const makeEdge = () => {
      const line = document.createElementNS('http://www.w3.org/2000/svg', 'line');
      line.setAttribute('stroke', DRAG_PREVIEW_STROKE);
      line.setAttribute('stroke-width', '2');
      line.setAttribute('stroke-linecap', 'round');
      return line;
    };

    dragPreview.row1Rect = makeRect();
    dragPreview.row2Rect = makeRect();
    dragPreview.row1Edge = makeEdge();
    dragPreview.row2Edge = makeEdge();
    layer.appendChild(dragPreview.row1Rect);
    layer.appendChild(dragPreview.row2Rect);
    layer.appendChild(dragPreview.row1Edge);
    layer.appendChild(dragPreview.row2Edge);
    svg.appendChild(layer);
    dragPreview.layer = layer;
    return layer;
  }

  function hideDragPreview() {
    if (dragPreview.layer) dragPreview.layer.style.display = 'none';
  }

  function updateDragPreview(regionIdx, bound, newNm) {
    const bounds = getPlotBounds();
    if (!bounds) return;
    const layer = ensureDragPreviewLayer();
    if (!layer) return;

    const entry = llEntries[regionIdx];
    if (!entry) return;

    const baseLo = parseFloat(entry.lower);
    const baseHi = parseFloat(entry.upper);
    if (!(Number.isFinite(baseLo) && Number.isFinite(baseHi))) return;

    const loNm = (bound === 'lower') ? newNm : baseLo;
    const hiNm = (bound === 'upper') ? newNm : baseHi;
    if (!(Number.isFinite(loNm) && Number.isFinite(hiNm))) return;

    const plotRect  = getPlotRectPixels(bounds);
    const loPxRel   = nmToPixel(loNm);
    const hiPxRel   = nmToPixel(hiNm);
    if (!(Number.isFinite(loPxRel) && Number.isFinite(hiPxRel))) return;

    const x0    = plotRect.left + Math.min(loPxRel, hiPxRel);
    const x1    = plotRect.left + Math.max(loPxRel, hiPxRel);
    const w     = Math.max(1, x1 - x0);
    const edgeX = (bound === 'lower')
      ? plotRect.left + loPxRel
      : plotRect.left + hiPxRel;

    const row1Band = getAxisBandPx(plotRect, bounds.yaxis);
    const row2Band = getAxisBandPx(plotRect, bounds.yaxis2);

    const applyRect = (rect, band) => {
      rect.setAttribute('x', x0);
      rect.setAttribute('y', band.y);
      rect.setAttribute('width', w);
      rect.setAttribute('height', band.height);
    };
    const applyLine = (line, band) => {
      line.setAttribute('x1', edgeX);
      line.setAttribute('x2', edgeX);
      line.setAttribute('y1', band.y);
      line.setAttribute('y2', band.y + band.height);
    };

    applyRect(dragPreview.row1Rect, row1Band);
    applyRect(dragPreview.row2Rect, row2Band);
    applyLine(dragPreview.row1Edge, row1Band);
    applyLine(dragPreview.row2Edge, row2Band);
    layer.style.display = 'block';
  }

  // ── Cursor management ──────────────────────────────────────────────────────

  function setEdgeHoverCursor(evt) {
    if (drawState.active || dragState.active) return;
    const target = findNearestEdgeFromEvent(evt);
    applyGraphCursor(target ? 'col-resize' : '');
  }

  function applyGraphCursor(cursor) {
    const graph = getGraphDiv();
    const host  = getGraphHost();
    if (graph) {
      graph.style.cursor = cursor;
      graph.querySelectorAll('.draglayer, .nsewdrag, .main-svg').forEach(el => {
        el.style.cursor = cursor;
      });
    }
    if (host) host.style.cursor = cursor;
  }

  // ── Mouse event handlers ───────────────────────────────────────────────────

  function onDocumentMouseDown(evt) {
    if (drawState.active) return;
    const hit = findNearestEdgeFromEvent(evt);
    if (!hit) return;

    const entry = llEntries[hit.regionIdx];
    if (!entry) return;

    const initialNm = parseFloat(hit.bound === 'lower' ? entry.lower : entry.upper);
    if (!Number.isFinite(initialNm)) return;

    dragState.active    = true;
    dragState.regionIdx = hit.regionIdx;
    dragState.bound     = hit.bound;
    dragState.currentNm = initialNm;
    activeEntryIdx      = hit.regionIdx;
    applyGraphCursor('col-resize');

    debugLog('edge drag start', { regionIdx: hit.regionIdx, bound: hit.bound });
    updateDragPreview(hit.regionIdx, hit.bound, initialNm);

    evt.preventDefault();
    evt.stopPropagation();
  }

  function onDocumentDragMove(evt) {
    if (!dragState.active) {
      setEdgeHoverCursor(evt);
      return;
    }

    const bounds = getPlotBounds();
    if (!bounds) return;

    const graphRect  = bounds.graph.getBoundingClientRect();
    const plotRect   = getPlotRectPixels(bounds);
    const relX       = (evt.clientX - graphRect.left) - plotRect.left;
    const candidateNm = pixelToNm(relX);
    if (!Number.isFinite(candidateNm)) return;

    const entry     = llEntries[dragState.regionIdx];
    const clampedNm = clampDraggedNm(entry, dragState.bound, candidateNm);
    if (!Number.isFinite(clampedNm)) return;

    dragState.currentNm = clampedNm;
    updateDragPreview(dragState.regionIdx, dragState.bound, clampedNm);
    evt.preventDefault();
  }

  function onDocumentDragUp(evt) {
    if (!dragState.active) return;

    const regionIdx = dragState.regionIdx;
    const bound     = dragState.bound;
    const newNm     = dragState.currentNm;

    dragState = { active: false, regionIdx: null, bound: null, currentNm: null };

    if (Number.isFinite(newNm) &&
        window.dash_clientside && window.dash_clientside.set_props) {
      window.dash_clientside.set_props('drag-result-store', {
        data: { region_idx: regionIdx, bound, new_x_nm: newNm },
      });
    }

    hideDragPreview();
    applyGraphCursor('');
    setEdgeHoverCursor(evt);
  }

  // ── SVG draw mode ──────────────────────────────────────────────────────────

  function initSvg() {
    const overlay = document.getElementById('drag-handles-overlay');
    if (!overlay) return;

    let svg = document.getElementById('drag-handles-svg');
    if (!svg) {
      svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
      svg.id = 'drag-handles-svg';
      svg.setAttribute('xmlns', 'http://www.w3.org/2000/svg');
      svg.style.width    = '100%';
      svg.style.height   = '100%';
      svg.style.position = 'absolute';
      svg.style.top      = '0';
      svg.style.left     = '0';
      svg.style.pointerEvents = 'none';
      overlay.appendChild(svg);
    }

    svg.addEventListener('mousedown',  onSvgMouseDown);
    svg.addEventListener('mousemove',  onSvgMouseMove);
    svg.addEventListener('mouseup',    onSvgMouseUp);
    svg.addEventListener('mouseleave', onSvgMouseLeave);
  }

  function onSvgMouseDown(evt) {
    if (!drawState.active) return;
    const bounds = getPlotBounds();
    if (!bounds) return;

    const plotRect  = getPlotRectPixels(bounds);
    const graphRect = bounds.graph.getBoundingClientRect();
    const absX  = evt.clientX - graphRect.left;
    const relX  = absX - plotRect.left;
    const nm    = pixelToNm(relX);
    if (!Number.isFinite(nm)) return;

    drawState.startX  = absX;
    drawState.startNm = nm;
    drawState.endX    = absX;
    drawState.endNm   = nm;
    evt.preventDefault();
  }

  function onSvgMouseMove(evt) {
    if (!drawState.active || drawState.startX === null) return;

    const svg    = document.getElementById('drag-handles-svg');
    const bounds = getPlotBounds();
    if (!svg || !bounds) return;

    const plotRect  = getPlotRectPixels(bounds);
    const graphRect = bounds.graph.getBoundingClientRect();
    const absX  = evt.clientX - graphRect.left;
    const relX  = absX - plotRect.left;
    const nm    = pixelToNm(relX);
    if (!Number.isFinite(nm)) return;

    drawState.endX  = absX;
    drawState.endNm = nm;

    if (!drawState.previewRect) {
      drawState.previewRect = document.createElementNS('http://www.w3.org/2000/svg', 'rect');
      drawState.previewRect.setAttribute('opacity', '0.8');
      svg.appendChild(drawState.previewRect);
    }

    const lo = Math.min(drawState.startX, drawState.endX);
    const hi = Math.max(drawState.startX, drawState.endX);
    drawState.previewRect.setAttribute('x', lo);
    drawState.previewRect.setAttribute('y', 0);
    drawState.previewRect.setAttribute('width', hi - lo);
    drawState.previewRect.setAttribute('height', svg.getAttribute('viewBox')?.split(' ')[3] || '100%');
    drawState.previewRect.setAttribute('fill', PREVIEW_FILL);
    drawState.previewRect.setAttribute('stroke', PREVIEW_STROKE);
    drawState.previewRect.setAttribute('stroke-width', '2');
  }

  function onSvgMouseUp(evt) {
    if (!drawState.active || drawState.startNm === null || drawState.endNm === null) return;

    const lo = Math.min(drawState.startNm, drawState.endNm);
    const hi = Math.max(drawState.startNm, drawState.endNm);

    const popover = document.getElementById('draw-confirm-popover');
    if (popover) {
      const rangeText = document.getElementById('draw-confirm-range-text');
      if (rangeText) rangeText.textContent = `${lo.toFixed(3)} – ${hi.toFixed(3)} nm`;
      popover.style.display = 'block';
      popover.style.left    = `${drawState.endX}px`;
      popover.style.top     = `${evt.clientY - 40}px`;
      popover.setAttribute('data-lo', lo);
      popover.setAttribute('data-hi', hi);
    }

    if (drawState.previewRect) {
      drawState.previewRect.remove();
      drawState.previewRect = null;
    }

    drawState = {
      active: false, startX: null, startNm: null,
      endX: null, endNm: null, previewRect: null,
    };
  }

  function onSvgMouseLeave() {
    if (drawState.active && drawState.previewRect) {
      drawState.previewRect.remove();
      drawState.previewRect = null;
    }
  }

  // ── Confirmation popover buttons ───────────────────────────────────────────

  function setupPopoverButtons() {
    const acceptBtn = document.getElementById('draw-confirm-accept');
    const cancelBtn = document.getElementById('draw-confirm-cancel');

    if (acceptBtn) {
      acceptBtn.addEventListener('click', () => {
        const popover = document.getElementById('draw-confirm-popover');
        if (!popover) return;
        const lo = parseFloat(popover.getAttribute('data-lo'));
        const hi = parseFloat(popover.getAttribute('data-hi'));
        if (Number.isFinite(lo) && Number.isFinite(hi) &&
            window.dash_clientside && window.dash_clientside.set_props) {
          window.dash_clientside.set_props('draw-region-store', { data: { lo, hi } });
        }
        popover.style.display = 'none';
      });
    }

    if (cancelBtn) {
      cancelBtn.addEventListener('click', () => {
        const popover = document.getElementById('draw-confirm-popover');
        if (popover) popover.style.display = 'none';
      });
    }
  }

  // ── Plotly event hooks ─────────────────────────────────────────────────────

  function onPlotlyAfterPlot() {
    debugLog('plotly_afterplot');
  }

  function onPlotlyHover(evt) {
    const point = evt && evt.points && evt.points.length ? evt.points[0] : null;
    if (!point || point.customdata === undefined || point.customdata === null) return;
    const raw    = Array.isArray(point.customdata) ? point.customdata[0] : point.customdata;
    const parsed = parseInt(raw, 10);
    if (!Number.isFinite(parsed)) return;
    const idx      = (parsed >= 1 && parsed <= llEntries.length) ? parsed - 1 : parsed;
    activeEntryIdx = (idx >= 0 && idx < llEntries.length) ? idx : null;
  }

  function onPlotlyUnhover() {
    if (!dragState.active) activeEntryIdx = null;
  }

  function attachPlotlyListeners(attempt) {
    const graph = getGraphDiv();
    if (!graph || typeof graph.on !== 'function') {
      if (attempt < 60) setTimeout(() => attachPlotlyListeners(attempt + 1), 200);
      return;
    }
    if (plotlyListenersBound) return;
    graph.on('plotly_afterplot', onPlotlyAfterPlot);
    graph.on('plotly_relayout',  onPlotlyAfterPlot);
    graph.on('plotly_hover',     onPlotlyHover);
    graph.on('plotly_unhover',   onPlotlyUnhover);
    plotlyListenersBound = true;
  }

  // ── Initialisation ─────────────────────────────────────────────────────────

  function init() {
    const graphHost = getGraphHost();
    if (!graphHost) {
      setTimeout(init, 100);
      return;
    }

    initSvg();
    setupPopoverButtons();

    document.addEventListener('mousemove', (evt) => {
      lastMouseClientX = evt.clientX;
      lastMouseClientY = evt.clientY;
      onDocumentDragMove(evt);
    }, { passive: false, capture: true });

    document.addEventListener('mousedown', onDocumentMouseDown, true);
    document.addEventListener('mouseup',   onDocumentDragUp,    true);

    attachPlotlyListeners(0);

    // ── STARTUP RACE FIX ──────────────────────────────────────────────────
    // The Dash clientside callback that calls window.updateLLEntries() fires
    // early in the page lifecycle — often before this script has run.
    // app.py always caches the entries in window.__llEntriesData first.
    // We read it here so we never miss the initial payload.
    if (window.__llEntriesData && window.__llEntriesData.length) {
      llEntries = window.__llEntriesData;
      debugLog('init: loaded llEntries from __llEntriesData cache', {
        count: llEntries.length,
      });
    } else {
      debugLog('init: __llEntriesData not ready yet — will be set by updateLLEntries()');
    }
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }

  // ── Public API (called by Dash clientside callbacks) ───────────────────────

  window.updateLLEntries = function(entries) {
    llEntries = entries || [];
    debugLog('updateLLEntries', { count: llEntries.length });
  };

  window.updateHoveredRegion = function(hoverSync) {
    const ridx = hoverSync && hoverSync.region_idx;
    if (ridx === null || ridx === undefined) {
      if (!dragState.active) activeEntryIdx = null;
      return;
    }
    const parsed = parseInt(ridx, 10);
    if (!Number.isFinite(parsed)) return;
    const idx      = (parsed >= 1 && parsed <= llEntries.length) ? parsed - 1 : parsed;
    activeEntryIdx = (idx >= 0 && idx < llEntries.length) ? idx : null;
  };

  window.activateDrawMode = function(active) {
    drawState.active = !!active;
    const svg = document.getElementById('drag-handles-svg');
    if (svg) svg.style.pointerEvents = active ? 'auto' : 'none';
    if (drawState.active) {
      dragState = { active: false, regionIdx: null, bound: null, currentNm: null };
      hideDragPreview();
    }
  };

})();