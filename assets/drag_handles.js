/**
 * ASAP Region Edge Drag + Draw Region Logic
 *
 * Drag UX (redesigned):
 *   • Grabbing a region edge stretches the green region rectangle live —
 *     the region itself is the visual feedback, no separate overlay box.
 *   • On release, drag-result-store is written. The Python callback marks
 *     the region pending and update_figure_shapes redraws it amber.
 *   • The cyan preview layer is gone entirely.
 *
 * Shape index contract:
 *   _build_ll_shapes() writes 2 shapes per region (y domain + y2 domain),
 *   so region i → Plotly shape indices  i*2  and  i*2+1.
 *   Candidate shapes are appended after, so LL indices are always stable.
 *
 * Data bootstrap:
 *   layout.py embeds window.__llEntriesData as an inline <script> before
 *   any asset loads, so llEntries is always populated on init().
 */

(function () {
  'use strict';

  const EDGE_HIT_TOLERANCE_PX = 16;
  const MIN_GAP_NM            = 0.001;
  const SHAPES_PER_REGION     = 2;   // row1 (y domain) + row2 (y2 domain)

  // Draw-mode preview colours (amber, same as pending)
  const PREVIEW_FILL   = 'rgba(255, 167, 38, 0.20)';
  const PREVIEW_STROKE = 'rgba(245, 130, 10, 0.95)';

  let llEntries            = [];
  let activeEntryIdx       = null;
  let plotlyListenersBound = false;
  let lastMouseClientX     = null;
  let lastMouseClientY     = null;

  let dragState = {
    active:    false,
    regionIdx: null,
    bound:     null,    // 'lower' | 'upper'
    currentNm: null,
  };

  let drawState = {
    active:      false,
    startX:      null,
    startNm:     null,
    endX:        null,
    endNm:       null,
    previewRect: null,
  };

  // ── Debug ──────────────────────────────────────────────────────────────────

  function debugLog() {
    if (!window.WE_DEBUG) return;
    try { console.log('[wave_explorer edge-drag]', ...arguments); } catch (e) {}
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
    const b = getPlotBounds();
    return (b && b.xaxis && b.xaxis.p2l) ? b.xaxis.p2l(px) : null;
  }

  function nmToPixel(nm) {
    const b = getPlotBounds();
    return (b && b.xaxis && b.xaxis.l2p) ? b.xaxis.l2p(nm) : null;
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
    const p = bounds.plot;
    return {
      left:   p.margin.l,
      top:    p.margin.t,
      width:  p.width  - p.margin.l - p.margin.r,
      height: p.height - p.margin.t - p.margin.b,
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
      debugLog('findNearestEdge: llEntries is EMPTY');
      return null;
    }

    const bounds = getPlotBounds();
    if (!bounds) return null;

    const graphRect = bounds.graph.getBoundingClientRect();
    const plotRect  = getPlotRectPixels(bounds);
    if (!isCursorInsidePlotArea(graphRect, plotRect, evt.clientX, evt.clientY)) return null;

    const cursorX = evt.clientX - graphRect.left;
    let best = null;

    for (let i = 0; i < llEntries.length; i++) {
      const entry = llEntries[i];
      if (!entry) continue;
      const loPx = nmToPixel(parseFloat(entry.lower));
      const hiPx = nmToPixel(parseFloat(entry.upper));
      if (loPx === null || hiPx === null) continue;

      const loDist = Math.abs(cursorX - (plotRect.left + loPx));
      const hiDist = Math.abs(cursorX - (plotRect.left + hiPx));

      if (loDist <= EDGE_HIT_TOLERANCE_PX && (!best || loDist < best.distancePx)) {
        best = { regionIdx: i, bound: 'lower', distancePx: loDist };
      }
      if (hiDist <= EDGE_HIT_TOLERANCE_PX && (!best || hiDist < best.distancePx)) {
        best = { regionIdx: i, bound: 'upper', distancePx: hiDist };
      }
    }

    if (best) debugLog('edge hit', best);
    return best;
  }

  // ── Live shape stretch ─────────────────────────────────────────────────────
  //
  // Calls Plotly.relayout() directly in the browser — no server round-trip.
  // region i → shape indices  i*2  (row1)  and  i*2+1  (row2).
  // We update only the dragged edge (x0 for lower bound, x1 for upper).

  function stretchRegionShape(regionIdx, bound, newNm) {
    const graph = getGraphDiv();
    if (!graph || typeof Plotly === 'undefined') return;

    const prop = bound === 'lower' ? 'x0' : 'x1';
    const base = regionIdx * SHAPES_PER_REGION;
    const update = {};
    update[`shapes[${base}].${prop}`]     = newNm;
    update[`shapes[${base + 1}].${prop}`] = newNm;

    Plotly.relayout(graph, update);
  }

  // ── Cursor management ──────────────────────────────────────────────────────

  function setEdgeHoverCursor(evt) {
    if (drawState.active || dragState.active) return;
    applyGraphCursor(findNearestEdgeFromEvent(evt) ? 'col-resize' : '');
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

    const entry     = llEntries[hit.regionIdx];
    const initialNm = parseFloat(hit.bound === 'lower' ? entry.lower : entry.upper);
    if (!Number.isFinite(initialNm)) return;

    dragState.active    = true;
    dragState.regionIdx = hit.regionIdx;
    dragState.bound     = hit.bound;
    dragState.currentNm = initialNm;
    activeEntryIdx      = hit.regionIdx;
    applyGraphCursor('col-resize');

    debugLog('drag start', { regionIdx: hit.regionIdx, bound: hit.bound });

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

    const graphRect   = bounds.graph.getBoundingClientRect();
    const plotRect    = getPlotRectPixels(bounds);
    const relX        = (evt.clientX - graphRect.left) - plotRect.left;
    const candidateNm = pixelToNm(relX);
    if (!Number.isFinite(candidateNm)) return;

    const clampedNm = clampDraggedNm(llEntries[dragState.regionIdx], dragState.bound, candidateNm);
    if (!Number.isFinite(clampedNm)) return;

    dragState.currentNm = clampedNm;

    // Stretch the actual region shape — the region itself is the feedback.
    stretchRegionShape(dragState.regionIdx, dragState.bound, clampedNm);

    evt.preventDefault();
  }

  function onDocumentDragUp(evt) {
    if (!dragState.active) return;

    const { regionIdx, bound, currentNm: newNm } = dragState;
    dragState = { active: false, regionIdx: null, bound: null, currentNm: null };

    // Update the local JS mirror so findNearestEdgeFromEvent() immediately
    // uses the new position — without this the hit-test stays locked to the
    // original coordinates and the ghost edge becomes the only draggable target.
    if (Number.isFinite(newNm) && llEntries[regionIdx]) {
      llEntries[regionIdx][bound] = newNm;
      llEntries[regionIdx].center = 0.5 * (
        parseFloat(llEntries[regionIdx].lower) +
        parseFloat(llEntries[regionIdx].upper)
      );
    }

    // Write to Dash store → Python marks region pending → figure redraws amber.
    if (Number.isFinite(newNm) &&
        window.dash_clientside && window.dash_clientside.set_props) {
      window.dash_clientside.set_props('drag-result-store', {
        data: { region_idx: regionIdx, bound, new_x_nm: newNm },
      });
    }

    applyGraphCursor('');
    setEdgeHoverCursor(evt);
  }

  // ── SVG overlay (draw-mode only) ───────────────────────────────────────────

  function initSvg() {
    const overlay = document.getElementById('drag-handles-overlay');
    if (!overlay) return;

    let svg = document.getElementById('drag-handles-svg');
    if (!svg) {
      svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
      svg.id             = 'drag-handles-svg';
      svg.style.cssText  = 'width:100%;height:100%;position:absolute;top:0;left:0;pointer-events:none;';
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
    const absX      = evt.clientX - graphRect.left;
    const nm        = pixelToNm(absX - plotRect.left);
    if (!Number.isFinite(nm)) return;

    drawState.startX = drawState.endX = absX;
    drawState.startNm = drawState.endNm = nm;
    evt.preventDefault();
  }

  function onSvgMouseMove(evt) {
    if (!drawState.active || drawState.startX === null) return;
    const svg    = document.getElementById('drag-handles-svg');
    const bounds = getPlotBounds();
    if (!svg || !bounds) return;

    const plotRect  = getPlotRectPixels(bounds);
    const graphRect = bounds.graph.getBoundingClientRect();
    const absX      = evt.clientX - graphRect.left;
    const nm        = pixelToNm(absX - plotRect.left);
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
    const pr = drawState.previewRect;
    pr.setAttribute('x',            lo);
    pr.setAttribute('y',            0);
    pr.setAttribute('width',        hi - lo);
    pr.setAttribute('height',       svg.getAttribute('viewBox')?.split(' ')[3] || '100%');
    pr.setAttribute('fill',         PREVIEW_FILL);
    pr.setAttribute('stroke',       PREVIEW_STROKE);
    pr.setAttribute('stroke-width', '2');
  }

  function onSvgMouseUp(evt) {
    if (!drawState.active || drawState.startNm === null || drawState.endNm === null) return;

    const lo = Math.min(drawState.startNm, drawState.endNm);
    const hi = Math.max(drawState.startNm, drawState.endNm);

    const popover = document.getElementById('draw-confirm-popover');
    if (popover) {
      const rt = document.getElementById('draw-confirm-range-text');
      if (rt) rt.textContent = `${lo.toFixed(3)} – ${hi.toFixed(3)} nm`;
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

    drawState = { active: false, startX: null, startNm: null, endX: null, endNm: null, previewRect: null };
  }

  function onSvgMouseLeave() {
    if (drawState.active && drawState.previewRect) {
      drawState.previewRect.remove();
      drawState.previewRect = null;
    }
  }

  // ── Draw-confirm popover ───────────────────────────────────────────────────

  function setupPopoverButtons() {
    const acceptBtn = document.getElementById('draw-confirm-accept');
    const cancelBtn = document.getElementById('draw-confirm-cancel');

    if (acceptBtn) {
      acceptBtn.addEventListener('click', () => {
        const p = document.getElementById('draw-confirm-popover');
        if (!p) return;
        const lo = parseFloat(p.getAttribute('data-lo'));
        const hi = parseFloat(p.getAttribute('data-hi'));
        if (Number.isFinite(lo) && Number.isFinite(hi) &&
            window.dash_clientside && window.dash_clientside.set_props) {
          window.dash_clientside.set_props('draw-region-store', { data: { lo, hi } });
        }
        p.style.display = 'none';
      });
    }

    if (cancelBtn) {
      cancelBtn.addEventListener('click', () => {
        const p = document.getElementById('draw-confirm-popover');
        if (p) p.style.display = 'none';
      });
    }
  }

  // ── Plotly hover / unhover ─────────────────────────────────────────────────

  function attachPlotlyListeners(attempt) {
    const graph = getGraphDiv();
    if (!graph || typeof graph.on !== 'function') {
      if (attempt < 60) setTimeout(() => attachPlotlyListeners(attempt + 1), 200);
      return;
    }
    if (plotlyListenersBound) return;
    graph.on('plotly_hover', (evt) => {
      const pt = evt && evt.points && evt.points[0];
      if (!pt || pt.customdata == null) return;
      const raw  = Array.isArray(pt.customdata) ? pt.customdata[0] : pt.customdata;
      const idx  = parseInt(raw, 10);
      if (!Number.isFinite(idx)) return;
      const i    = (idx >= 1 && idx <= llEntries.length) ? idx - 1 : idx;
      activeEntryIdx = (i >= 0 && i < llEntries.length) ? i : null;
    });
    graph.on('plotly_unhover', () => {
      if (!dragState.active) activeEntryIdx = null;
    });
    plotlyListenersBound = true;
    debugLog('plotly listeners bound');
  }

  // ── Initialisation ─────────────────────────────────────────────────────────

  function init() {
    const graphHost = getGraphHost();
    if (!graphHost) { setTimeout(init, 100); return; }

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

    // Read from the inline <script> embedded by layout.py — always available.
    if (window.__llEntriesData && window.__llEntriesData.length) {
      llEntries = window.__llEntriesData;
      debugLog('init: loaded from __llEntriesData', { count: llEntries.length });
    } else {
      debugLog('init: __llEntriesData not ready — waiting for updateLLEntries()');
    }
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }

  // ── Public API (called by Dash clientside callbacks) ───────────────────────

  window.updateLLEntries = function (entries) {
    llEntries = entries || [];
    debugLog('updateLLEntries', { count: llEntries.length });
  };

  window.updateHoveredRegion = function (hoverSync) {
    const ridx = hoverSync && hoverSync.region_idx;
    if (ridx == null) { if (!dragState.active) activeEntryIdx = null; return; }
    const parsed = parseInt(ridx, 10);
    if (!Number.isFinite(parsed)) return;
    const i = (parsed >= 1 && parsed <= llEntries.length) ? parsed - 1 : parsed;
    activeEntryIdx = (i >= 0 && i < llEntries.length) ? i : null;
  };

  window.activateDrawMode = function (active) {
    drawState.active = !!active;
    const svg = document.getElementById('drag-handles-svg');
    if (svg) svg.style.pointerEvents = active ? 'auto' : 'none';
    if (drawState.active) {
      dragState = { active: false, regionIdx: null, bound: null, currentNm: null };
    }
  };

})();