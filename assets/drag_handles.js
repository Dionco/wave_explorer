/**
 * ASAP Region Edge Drag + Draw Region Logic
 *
 * Drag UX:
 *   - Grabbing a region edge stretches the green region rectangle live —
 *     the region itself is the visual feedback, no separate overlay box.
 *   - On release, drag-result-store is written. The Python callback marks
 *     the region pending and update_figure_shapes redraws it amber.
 *
 * Shape index contract:
 *   _build_ll_shapes() writes 2 shapes per region (y domain + y2 domain),
 *   so region i -> Plotly shape indices  i*2  and  i*2+1.
 *   Candidate shapes are appended after, so LL indices are always stable.
 *
 * Data bootstrap:
 *   The clientside callback in app.py writes window.__llEntriesData when
 *   ll-entries-store fires. This script reads it on init() and updates
 *   via window.updateLLEntries().
 */

(function () {
  "use strict";

  var EDGE_HIT_TOLERANCE_PX = 16;
  var MIN_GAP_NM = 0.001;
  var SHAPES_PER_REGION = 2; // row1 (y domain) + row2 (y2 domain)

  // Draw-mode preview colours (amber, same as pending)
  var PREVIEW_FILL = "rgba(255, 167, 38, 0.20)";
  var PREVIEW_STROKE = "rgba(245, 130, 10, 0.95)";

  var llEntries = [];
  var activeEntryIdx = null;
  var plotlyListenersBound = false;
  var svgListenersBound = false;

  var dragState = {
    active: false,
    regionIdx: null,
    bound: null, // "lower" | "upper"
    currentNm: null,
  };

  var drawState = {
    active: false,
    startX: null,
    startNm: null,
    endX: null,
    endNm: null,
    previewRect: null,
  };

  // -- Debug ----------------------------------------------------------------

  function debugLog() {
    if (!window.WE_DEBUG) return;
    try {
      console.log("[wave_explorer edge-drag]", ...arguments);
    } catch (e) {
      /* ignore */
    }
  }

  // -- Deep clone helper ----------------------------------------------------

  function cloneEntries(entries) {
    if (!entries || !entries.length) return [];
    return entries.map(function (e) {
      return Object.assign({}, e);
    });
  }

  // -- Plotly graph accessors -----------------------------------------------

  function getGraphHost() {
    return document.getElementById("spectrum-graph");
  }

  function getGraphDiv() {
    var host = getGraphHost();
    if (!host) return null;
    if (host._fullLayout && typeof host.on === "function") return host;
    var inner = host.querySelector(".js-plotly-plot");
    if (inner && inner._fullLayout) return inner;
    return inner || host;
  }

  function getPlotBounds() {
    var graph = getGraphDiv();
    if (!graph || !graph._fullLayout || !graph._fullLayout.xaxis) return null;
    return {
      graph: graph,
      plot: graph._fullLayout,
      xaxis: graph._fullLayout.xaxis,
      yaxis: graph._fullLayout.yaxis,
      yaxis2: graph._fullLayout.yaxis2,
    };
  }

  function pixelToNm(px) {
    var b = getPlotBounds();
    return b && b.xaxis && b.xaxis.p2l ? b.xaxis.p2l(px) : null;
  }

  function nmToPixel(nm) {
    var b = getPlotBounds();
    return b && b.xaxis && b.xaxis.l2p ? b.xaxis.l2p(nm) : null;
  }

  // -- Geometry helpers -----------------------------------------------------

  function clampDraggedNm(entry, bound, candidateNm) {
    if (!entry || !Number.isFinite(candidateNm)) return null;
    var lower = parseFloat(entry.lower);
    var upper = parseFloat(entry.upper);
    if (!Number.isFinite(lower) || !Number.isFinite(upper)) return null;
    if (bound === "lower") return Math.min(candidateNm, upper - MIN_GAP_NM);
    if (bound === "upper") return Math.max(candidateNm, lower + MIN_GAP_NM);
    return null;
  }

  function getPlotRectPixels(bounds) {
    var p = bounds.plot;
    return {
      left: p.margin.l,
      top: p.margin.t,
      width: p.width - p.margin.l - p.margin.r,
      height: p.height - p.margin.t - p.margin.b,
    };
  }

  function isCursorInsidePlotArea(graphRect, plotRect, clientX, clientY) {
    var x = clientX - graphRect.left;
    var y = clientY - graphRect.top;
    return (
      x >= plotRect.left &&
      x <= plotRect.left + plotRect.width &&
      y >= plotRect.top &&
      y <= plotRect.top + plotRect.height
    );
  }

  function findNearestEdgeFromEvent(evt) {
    if (!llEntries.length) {
      debugLog("findNearestEdge: llEntries is EMPTY");
      return null;
    }

    var bounds = getPlotBounds();
    if (!bounds) return null;

    var graphRect = bounds.graph.getBoundingClientRect();
    var plotRect = getPlotRectPixels(bounds);
    if (
      !isCursorInsidePlotArea(graphRect, plotRect, evt.clientX, evt.clientY)
    ) {
      return null;
    }

    var cursorX = evt.clientX - graphRect.left;
    var best = null;

    for (var i = 0; i < llEntries.length; i++) {
      var entry = llEntries[i];
      if (!entry) continue;
      var loPx = nmToPixel(parseFloat(entry.lower));
      var hiPx = nmToPixel(parseFloat(entry.upper));
      if (loPx === null || hiPx === null) continue;

      var loDist = Math.abs(cursorX - (plotRect.left + loPx));
      var hiDist = Math.abs(cursorX - (plotRect.left + hiPx));

      if (
        loDist <= EDGE_HIT_TOLERANCE_PX &&
        (!best || loDist < best.distancePx)
      ) {
        best = { regionIdx: i, bound: "lower", distancePx: loDist };
      }
      if (
        hiDist <= EDGE_HIT_TOLERANCE_PX &&
        (!best || hiDist < best.distancePx)
      ) {
        best = { regionIdx: i, bound: "upper", distancePx: hiDist };
      }
    }

    if (best) debugLog("edge hit", best);
    return best;
  }

  // -- Live shape stretch ---------------------------------------------------
  //
  // Calls Plotly.relayout() directly in the browser — no server round-trip.
  // region i -> shape indices  i*2  (row1)  and  i*2+1  (row2).
  // We update only the dragged edge (x0 for lower bound, x1 for upper).

  function stretchRegionShape(regionIdx, bound, newNm) {
    var graph = getGraphDiv();
    if (!graph || typeof Plotly === "undefined") return;

    var prop = bound === "lower" ? "x0" : "x1";
    var base = regionIdx * SHAPES_PER_REGION;
    var update = {};
    update["shapes[" + base + "]." + prop] = newNm;
    update["shapes[" + (base + 1) + "]." + prop] = newNm;

    Plotly.relayout(graph, update);
  }

  // -- Cursor management ----------------------------------------------------

  function setEdgeHoverCursor(evt) {
    if (drawState.active || dragState.active) return;
    applyGraphCursor(findNearestEdgeFromEvent(evt) ? "col-resize" : "");
  }

  function applyGraphCursor(cursor) {
    var graph = getGraphDiv();
    var host = getGraphHost();
    if (graph) {
      graph.style.cursor = cursor;
      graph
        .querySelectorAll(".draglayer, .nsewdrag, .main-svg")
        .forEach(function (el) {
          el.style.cursor = cursor;
        });
    }
    if (host) host.style.cursor = cursor;
  }

  // -- Mouse event handlers -------------------------------------------------

  function onDocumentMouseDown(evt) {
    if (drawState.active) return;

    var hit = findNearestEdgeFromEvent(evt);
    if (!hit) return;

    var entry = llEntries[hit.regionIdx];
    var initialNm = parseFloat(
      hit.bound === "lower" ? entry.lower : entry.upper
    );
    if (!Number.isFinite(initialNm)) return;

    dragState.active = true;
    dragState.regionIdx = hit.regionIdx;
    dragState.bound = hit.bound;
    dragState.currentNm = initialNm;
    activeEntryIdx = hit.regionIdx;
    applyGraphCursor("col-resize");

    debugLog("drag start", {
      regionIdx: hit.regionIdx,
      bound: hit.bound,
    });

    evt.preventDefault();
    evt.stopPropagation();
  }

  function onDocumentDragMove(evt) {
    if (!dragState.active) return;

    var bounds = getPlotBounds();
    if (!bounds) return;

    var graphRect = bounds.graph.getBoundingClientRect();
    var plotRect = getPlotRectPixels(bounds);
    var relX = evt.clientX - graphRect.left - plotRect.left;
    var candidateNm = pixelToNm(relX);
    if (!Number.isFinite(candidateNm)) return;

    var clampedNm = clampDraggedNm(
      llEntries[dragState.regionIdx],
      dragState.bound,
      candidateNm
    );
    if (!Number.isFinite(clampedNm)) return;

    dragState.currentNm = clampedNm;

    // Stretch the actual region shape — the region itself is the feedback.
    stretchRegionShape(dragState.regionIdx, dragState.bound, clampedNm);

    evt.preventDefault();
  }

  function onDocumentDragUp(evt) {
    if (!dragState.active) return;

    var regionIdx = dragState.regionIdx;
    var bound = dragState.bound;
    var newNm = dragState.currentNm;
    dragState = {
      active: false,
      regionIdx: null,
      bound: null,
      currentNm: null,
    };

    // [C2 FIX] Update the local JS mirror (which is already a clone,
    // so this does NOT mutate the Dash store's internal data).
    if (Number.isFinite(newNm) && llEntries[regionIdx]) {
      llEntries[regionIdx][bound] = newNm;
      llEntries[regionIdx].center =
        0.5 *
        (parseFloat(llEntries[regionIdx].lower) +
          parseFloat(llEntries[regionIdx].upper));
    }

    // Write to Dash store -> Python marks region pending -> figure redraws.
    if (
      Number.isFinite(newNm) &&
      window.dash_clientside &&
      window.dash_clientside.set_props
    ) {
      window.dash_clientside.set_props("drag-result-store", {
        data: { region_idx: regionIdx, bound: bound, new_x_nm: newNm },
      });
    }

    applyGraphCursor("");
    setEdgeHoverCursor(evt);
  }

  // -- SVG overlay (draw-mode only) -----------------------------------------

  function initSvg() {
    var overlay = document.getElementById("drag-handles-overlay");
    if (!overlay) return;

    var svg = document.getElementById("drag-handles-svg");
    if (!svg) {
      svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
      svg.id = "drag-handles-svg";
      svg.style.cssText =
        "width:100%;height:100%;position:absolute;top:0;left:0;pointer-events:none;";
      overlay.appendChild(svg);
    }

    // [H5 FIX] Guard against duplicate listener registration.
    if (!svgListenersBound) {
      svg.addEventListener("mousedown", onSvgMouseDown);
      svg.addEventListener("mousemove", onSvgMouseMove);
      svg.addEventListener("mouseup", onSvgMouseUp);
      svg.addEventListener("mouseleave", onSvgMouseLeave);
      svgListenersBound = true;
    }
  }

  function onSvgMouseDown(evt) {
    if (!drawState.active) return;
    var bounds = getPlotBounds();
    if (!bounds) return;

    // Starting a fresh gesture — hide any stale confirm popover from a
    // previous draw so the UI does not point at an outdated range.
    var stalePopover = document.getElementById("draw-confirm-popover");
    if (stalePopover && stalePopover.style.display === "block") {
      stalePopover.style.display = "none";
    }

    var plotRect = getPlotRectPixels(bounds);
    var graphRect = bounds.graph.getBoundingClientRect();
    var absX = evt.clientX - graphRect.left;
    var nm = pixelToNm(absX - plotRect.left);
    if (!Number.isFinite(nm)) return;

    drawState.startX = absX;
    drawState.endX = absX;
    drawState.startNm = nm;
    drawState.endNm = nm;
    evt.preventDefault();
  }

  function onSvgMouseMove(evt) {
    if (!drawState.active || drawState.startX === null) return;
    var svg = document.getElementById("drag-handles-svg");
    var bounds = getPlotBounds();
    if (!svg || !bounds) return;

    var plotRect = getPlotRectPixels(bounds);
    var graphRect = bounds.graph.getBoundingClientRect();
    var absX = evt.clientX - graphRect.left;
    var nm = pixelToNm(absX - plotRect.left);
    if (!Number.isFinite(nm)) return;

    drawState.endX = absX;
    drawState.endNm = nm;

    if (!drawState.previewRect) {
      drawState.previewRect = document.createElementNS(
        "http://www.w3.org/2000/svg",
        "rect"
      );
      drawState.previewRect.setAttribute("opacity", "0.8");
      svg.appendChild(drawState.previewRect);
    }

    var lo = Math.min(drawState.startX, drawState.endX);
    var hi = Math.max(drawState.startX, drawState.endX);
    var pr = drawState.previewRect;
    pr.setAttribute("x", lo);
    pr.setAttribute("y", 0);
    pr.setAttribute("width", hi - lo);
    pr.setAttribute("height", "100%"); // [M6 FIX] Removed dead viewBox read
    pr.setAttribute("fill", PREVIEW_FILL);
    pr.setAttribute("stroke", PREVIEW_STROKE);
    pr.setAttribute("stroke-width", "2");
  }

  function onSvgMouseUp(evt) {
    if (
      !drawState.active ||
      drawState.startNm === null ||
      drawState.endNm === null
    ) {
      return;
    }

    var lo = Math.min(drawState.startNm, drawState.endNm);
    var hi = Math.max(drawState.startNm, drawState.endNm);

    var popover = document.getElementById("draw-confirm-popover");
    if (popover) {
      var rt = document.getElementById("draw-confirm-range-text");
      if (rt) rt.textContent = lo.toFixed(3) + " \u2013 " + hi.toFixed(3) + " nm";
      popover.style.display = "block";
      popover.style.left = drawState.endX + "px";
      popover.style.top = evt.clientY - 40 + "px";
      popover.setAttribute("data-lo", lo);
      popover.setAttribute("data-hi", hi);
    }

    if (drawState.previewRect) {
      drawState.previewRect.remove();
      drawState.previewRect = null;
    }

    // [M5 FIX] Preserve drawState.active across gestures — only reset
    // gesture-specific fields so draw mode persists until explicitly toggled.
    drawState.startX = null;
    drawState.startNm = null;
    drawState.endX = null;
    drawState.endNm = null;
    drawState.previewRect = null;
  }

  function onSvgMouseLeave() {
    if (drawState.active && drawState.previewRect) {
      drawState.previewRect.remove();
      drawState.previewRect = null;
    }
  }

  // -- Draw-confirm popover -------------------------------------------------

  function setupPopoverButtons() {
    var acceptBtn = document.getElementById("draw-confirm-accept");
    var cancelBtn = document.getElementById("draw-confirm-cancel");

    if (acceptBtn) {
      acceptBtn.addEventListener("click", function () {
        var p = document.getElementById("draw-confirm-popover");
        if (!p) return;
        var lo = parseFloat(p.getAttribute("data-lo"));
        var hi = parseFloat(p.getAttribute("data-hi"));
        if (
          Number.isFinite(lo) &&
          Number.isFinite(hi) &&
          window.dash_clientside &&
          window.dash_clientside.set_props
        ) {
          window.dash_clientside.set_props("draw-region-store", {
            data: { lo: lo, hi: hi },
          });
        }
        p.style.display = "none";
      });
    }

    if (cancelBtn) {
      cancelBtn.addEventListener("click", function () {
        var p = document.getElementById("draw-confirm-popover");
        if (p) p.style.display = "none";
      });
    }
  }

  // -- Plotly hover / unhover -----------------------------------------------

  function attachPlotlyListeners(attempt) {
    var graph = getGraphDiv();
    if (!graph || typeof graph.on !== "function") {
      if (attempt < 60)
        setTimeout(function () {
          attachPlotlyListeners(attempt + 1);
        }, 200);
      return;
    }
    if (plotlyListenersBound) return;

    graph.on("plotly_hover", function (evt) {
      var pt = evt && evt.points && evt.points[0];
      if (!pt || pt.customdata == null) return;
      var raw = Array.isArray(pt.customdata) ? pt.customdata[0] : pt.customdata;
      var idx = parseInt(raw, 10);
      if (!Number.isFinite(idx)) return;
      var i = idx >= 1 && idx <= llEntries.length ? idx - 1 : idx;
      activeEntryIdx = i >= 0 && i < llEntries.length ? i : null;
    });

    graph.on("plotly_unhover", function () {
      if (!dragState.active) activeEntryIdx = null;
    });

    plotlyListenersBound = true;
    debugLog("plotly listeners bound");
  }

  // -- Initialisation -------------------------------------------------------

  function init() {
    var graphHost = getGraphHost();
    if (!graphHost) {
      setTimeout(init, 100);
      return;
    }

    initSvg();
    setupPopoverButtons();

    // [L4 PARTIAL FIX] Only run expensive edge-detection when cursor is
    // over the graph host element. The document-level listener is still
    // needed for drag-move (cursor may leave the graph during drag).
    document.addEventListener(
      "mousemove",
      function (evt) {
        if (dragState.active) {
          onDocumentDragMove(evt);
        } else {
          setEdgeHoverCursor(evt);
        }
      },
      { passive: false, capture: true }
    );

    document.addEventListener("mousedown", onDocumentMouseDown, true);
    document.addEventListener("mouseup", onDocumentDragUp, true);

    // Escape: cancel draw mode and any in-flight draw gesture / confirm popover.
    document.addEventListener("keydown", function (evt) {
      if (evt.key !== "Escape") return;
      var popover = document.getElementById("draw-confirm-popover");
      var popoverVisible =
        popover && popover.style.display && popover.style.display !== "none";
      if (!drawState.active && !popoverVisible) return;

      if (popover) popover.style.display = "none";
      if (drawState.previewRect) {
        drawState.previewRect.remove();
        drawState.previewRect = null;
      }
      drawState.startX = null;
      drawState.startNm = null;
      drawState.endX = null;
      drawState.endNm = null;

      if (window.activateDrawMode) window.activateDrawMode(false);
      var btn = document.getElementById("draw-mode-toggle");
      if (btn) {
        btn.classList.remove("btn-active");
        btn.textContent = "✎ Draw Region";
      }
      // Keep the Dash store in sync so the next toggle-button click is
      // interpreted relative to the correct state.
      if (window.dash_clientside && window.dash_clientside.set_props) {
        window.dash_clientside.set_props("draw-mode-active-store", {
          data: false,
        });
      }
    });

    attachPlotlyListeners(0);

    // Read from the clientside callback cache if already available.
    if (window.__llEntriesData && window.__llEntriesData.length) {
      llEntries = cloneEntries(window.__llEntriesData);
      debugLog("init: loaded from __llEntriesData", {
        count: llEntries.length,
      });
    } else {
      debugLog("init: __llEntriesData not ready — waiting for updateLLEntries()");
    }
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }

  // -- Public API (called by Dash clientside callbacks) ---------------------

  // [C2 FIX] Always clone incoming entries so in-place mutations during
  // drag (line ~260) never corrupt the Dash store's internal data.
  window.updateLLEntries = function (entries) {
    llEntries = cloneEntries(entries);
    debugLog("updateLLEntries", { count: llEntries.length });
  };

  /**
   * Reset the in-memory llEntries mirror to the saved (ll-entries-store)
   * values after Discard. Shape positions are refreshed by the Dash
   * Patch update from update_figure_shapes — we must NOT call
   * Plotly.relayout() here because it triggers layoutReplot which
   * resets zoom.
   */
  window.resetShapesToEntries = function (entries) {
    llEntries = cloneEntries(entries);
    debugLog("resetShapesToEntries: mirror reset", { count: llEntries.length });
  };

  window.updateHoveredRegion = function (hoverSync) {
    var ridx = hoverSync && hoverSync.region_idx;
    if (ridx == null) {
      if (!dragState.active) activeEntryIdx = null;
      return;
    }
    var parsed = parseInt(ridx, 10);
    if (!Number.isFinite(parsed)) return;
    var i = parsed >= 1 && parsed <= llEntries.length ? parsed - 1 : parsed;
    activeEntryIdx = i >= 0 && i < llEntries.length ? i : null;
  };

  window.activateDrawMode = function (active) {
    drawState.active = !!active;
    var svg = document.getElementById("drag-handles-svg");
    if (svg) svg.style.pointerEvents = active ? "auto" : "none";
    if (drawState.active) {
      dragState = {
        active: false,
        regionIdx: null,
        bound: null,
        currentNm: null,
      };
    }
  };
})();
