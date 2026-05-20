/**
 * ASAP Cursor-Tracking Tooltip
 *
 * Reads ll-stats from the Dash clientside callback or from the
 * window.__llStatsData cache written by the ll-entries sync callback.
 */

(function () {
  "use strict";

  var lastCursorX = 0;
  var lastCursorY = 0;
  var llStats = [];

  function debugLog() {
    if (!window.WE_DEBUG) return;
    try {
      console.log("[wave_explorer tooltip]", ...arguments);
    } catch (e) {
      /* ignore */
    }
  }

  function getGraphDiv() {
    var host = document.getElementById("spectrum-graph");
    if (!host) return null;
    if (typeof host.on === "function" && host._fullLayout) return host;
    var inner = host.querySelector(".js-plotly-plot");
    if (inner && typeof inner.on === "function") return inner;
    return typeof host.on === "function" ? host : null;
  }

  function formatValue(v, decimals, fallback) {
    if (v === null || v === undefined || isNaN(v)) return fallback || "\u2014";
    return parseFloat(v).toFixed(decimals);
  }

  // -- Tooltip render -------------------------------------------------------

  function updateTooltip(regionIdx) {
    var tooltip = document.getElementById("cursor-tooltip");
    if (!tooltip) return;

    if (regionIdx === null || regionIdx === undefined) {
      tooltip.style.display = "none";
      return;
    }

    var stat = llStats.find(function (s) {
      return s.region_idx === regionIdx;
    });
    if (!stat) {
      tooltip.style.display = "none";
      return;
    }

    var chi2Str =
      stat.med_chi2 !== null && stat.med_chi2 !== undefined
        ? formatValue(stat.med_chi2, 3)
        : "\u2014";

    tooltip.innerHTML =
      '<div style="font-weight:bold;color:#b3553b;margin-bottom:4px">' +
      "Region #" +
      stat.region_idx +
      "</div>" +
      '<div style="font-size:10px;line-height:1.5">' +
      "<div>\u03bb " +
      formatValue(stat.lower, 3) +
      " \u2013 " +
      formatValue(stat.upper, 3) +
      " nm</div>" +
      "<div>Center: " +
      formatValue(stat.center, 3) +
      " nm</div>" +
      '<div style="border-top:1px solid rgba(179,85,59,0.3);margin:4px 0;padding-top:4px">' +
      "<div>\u03c7\u00b2/N: " +
      chi2Str +
      "</div>" +
      "<div>Stars: " +
      (stat.n_stars || 0) +
      "</div>" +
      "<div>Median pix: " +
      (stat.med_npix || 0) +
      "</div>" +
      "</div></div>";

    tooltip.style.display = "block";
    positionTooltip(tooltip);
  }

  function positionTooltip(tooltip) {
    if (!tooltip) tooltip = document.getElementById("cursor-tooltip");
    if (!tooltip || tooltip.style.display === "none") return;

    // Set provisional position so we can measure the rendered box, then
    // clamp it to the viewport so it never bleeds off the edge.
    tooltip.style.left = lastCursorX + 14 + "px";
    tooltip.style.top = lastCursorY - 40 + "px";

    var rect = tooltip.getBoundingClientRect();
    var vw = window.innerWidth || document.documentElement.clientWidth;
    var vh = window.innerHeight || document.documentElement.clientHeight;
    var margin = 8;

    var left = lastCursorX + 14;
    var top = lastCursorY - 40;
    if (left + rect.width > vw - margin) {
      // Flip to the left side of the cursor.
      left = lastCursorX - rect.width - 14;
    }
    if (left < margin) left = margin;
    if (top + rect.height > vh - margin) {
      top = vh - rect.height - margin;
    }
    if (top < margin) top = margin;

    tooltip.style.left = left + "px";
    tooltip.style.top = top + "px";
  }

  // -- Mouse tracking -------------------------------------------------------

  function setupMouseTracking() {
    document.addEventListener("mousemove", function (evt) {
      lastCursorX = evt.clientX;
      lastCursorY = evt.clientY;
      positionTooltip();
    });
  }

  // -- Dash clientside callback ---------------------------------------------

  window.dash_clientside = window.dash_clientside || {};

  window.dash_clientside.show_region_tooltip = function (
    hoverData,
    llStatsStore
  ) {
    // Update local cache if the Dash store provides fresher data.
    if (llStatsStore && llStatsStore.length) {
      llStats = llStatsStore;
    }

    if (!hoverData || !hoverData.points || !hoverData.points.length) {
      updateTooltip(null);
      return { region_idx: null };
    }

    var point = hoverData.points[0];
    if (
      point &&
      point.customdata !== undefined &&
      point.customdata !== null
    ) {
      var raw = Array.isArray(point.customdata)
        ? point.customdata[0]
        : point.customdata;
      // [L3 FIX] Always specify radix 10.
      var regionIdx = parseInt(raw, 10);
      updateTooltip(Number.isFinite(regionIdx) ? regionIdx : null);
      return {
        region_idx: Number.isFinite(regionIdx) ? regionIdx : null,
      };
    }

    updateTooltip(null);
    return { region_idx: null };
  };

  // -- Plotly unhover + mouseleave ------------------------------------------

  function setupPlotlyUnhover(attempt) {
    var graph = getGraphDiv();
    if (!graph || typeof graph.on !== "function") {
      if (attempt < 60)
        setTimeout(function () {
          setupPlotlyUnhover(attempt + 1);
        }, 200);
      return;
    }

    debugLog("binding plotly_unhover listener");
    graph.on("plotly_unhover", function () {
      debugLog("plotly_unhover fired");
      updateTooltip(null);
    });

    // [L5 FIX] Force-hide tooltip when mouse leaves the graph container,
    // since Plotly sometimes misses the unhover event on fast exits.
    var host = document.getElementById("spectrum-graph");
    if (host) {
      host.addEventListener("mouseleave", function () {
        debugLog("graph mouseleave — hiding tooltip");
        updateTooltip(null);
      });
    }
  }

  // -- Initialisation -------------------------------------------------------

  function init() {
    setupMouseTracking();
    setupPlotlyUnhover(0);

    // Read stats from the global cache if already available.
    if (window.__llStatsData && window.__llStatsData.length) {
      llStats = window.__llStatsData;
      debugLog("init: loaded llStats from __llStatsData", {
        count: llStats.length,
      });
    } else {
      debugLog("init: __llStatsData not ready — will rely on Dash callback");
    }
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
