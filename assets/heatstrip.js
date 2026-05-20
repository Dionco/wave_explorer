/**
 * Wave Explorer — Heat-strip mini-map
 *
 * A client-side navigation strip beneath the spectrum:
 *   - a viewport box tracks the spectrum's current x-range
 *   - click / drag the strip to move the spectrum view
 *
 * Everything here is client-side (no server round-trip) and the viewport
 * sync is requestAnimationFrame-throttled, so panning stays buttery smooth
 * even while Plotly streams continuous relayout events.
 */

(function () {
  "use strict";

  var rafPending = false;
  var dragging = false;

  function getGraphDiv() {
    var host = document.getElementById("spectrum-graph");
    if (!host) return null;
    if (typeof host.on === "function" && host._fullLayout) return host;
    var inner = host.querySelector(".js-plotly-plot");
    if (inner && typeof inner.on === "function") return inner;
    return typeof host.on === "function" ? host : null;
  }

  function clamp(v, lo, hi) {
    return v < lo ? lo : v > hi ? hi : v;
  }

  function bounds(strip) {
    var lmin = parseFloat(strip.dataset.lmin);
    var lmax = parseFloat(strip.dataset.lmax);
    if (!isFinite(lmin) || !isFinite(lmax) || lmax <= lmin) return null;
    return { lmin: lmin, lmax: lmax, span: lmax - lmin };
  }

  function currentRange(gd) {
    try {
      var ax = gd && gd._fullLayout && gd._fullLayout.xaxis;
      if (ax && ax.range && ax.range.length === 2) {
        var a = +ax.range[0];
        var b = +ax.range[1];
        if (isFinite(a) && isFinite(b)) return b > a ? [a, b] : [b, a];
      }
    } catch (e) {
      /* ignore */
    }
    return null;
  }

  // -- Viewport sync --------------------------------------------------------

  function syncViewport() {
    rafPending = false;
    var gd = getGraphDiv();
    var strip = document.getElementById("heatstrip");
    var vp = document.getElementById("heatstrip-viewport");
    if (!gd || !strip || !vp) return;
    var b = bounds(strip);
    var r = currentRange(gd);
    if (!b || !r) return;
    var left = clamp(((r[0] - b.lmin) / b.span) * 100, 0, 100);
    var right = clamp(((r[1] - b.lmin) / b.span) * 100, 0, 100);
    vp.style.left = left + "%";
    vp.style.width = Math.max(0.4, right - left) + "%";
  }

  function scheduleSync() {
    if (rafPending) return;
    rafPending = true;
    window.requestAnimationFrame(syncViewport);
  }

  // -- Navigation -----------------------------------------------------------

  function jumpToClientX(clientX) {
    var gd = getGraphDiv();
    var strip = document.getElementById("heatstrip");
    if (!gd || !strip || !window.Plotly || !window.Plotly.relayout) return;
    var b = bounds(strip);
    if (!b) return;
    var rect = strip.getBoundingClientRect();
    var frac = clamp((clientX - rect.left) / rect.width, 0, 1);
    var lam = b.lmin + frac * b.span;
    var r = currentRange(gd) || [b.lmin, b.lmax];
    var viewSpan = Math.min(b.span, r[1] - r[0]);
    var lo = lam - viewSpan / 2;
    var hi = lam + viewSpan / 2;
    if (lo < b.lmin) {
      hi += b.lmin - lo;
      lo = b.lmin;
    }
    if (hi > b.lmax) {
      lo -= hi - b.lmax;
      hi = b.lmax;
    }
    window.Plotly.relayout(gd, {
      "xaxis.range": [clamp(lo, b.lmin, b.lmax), clamp(hi, b.lmin, b.lmax)],
    });
  }

  function setupStrip() {
    var strip = document.getElementById("heatstrip");
    if (!strip) return;

    strip.addEventListener("pointerdown", function (e) {
      dragging = true;
      try {
        strip.setPointerCapture(e.pointerId);
      } catch (err) {
        /* ignore */
      }
      jumpToClientX(e.clientX);
      e.preventDefault();
    });

    strip.addEventListener("pointermove", function (e) {
      if (dragging) jumpToClientX(e.clientX);
    });

    function endDrag(e) {
      dragging = false;
      try {
        strip.releasePointerCapture(e.pointerId);
      } catch (err) {
        /* ignore */
      }
    }
    strip.addEventListener("pointerup", endDrag);
    strip.addEventListener("pointercancel", endDrag);
  }

  // -- Plotly binding -------------------------------------------------------

  function bindGraph(attempt) {
    var gd = getGraphDiv();
    if (!gd || typeof gd.on !== "function") {
      if (attempt < 80) {
        setTimeout(function () {
          bindGraph(attempt + 1);
        }, 150);
      }
      return;
    }
    // plotly_relayouting fires continuously mid-pan → live viewport tracking.
    gd.on("plotly_relayout", scheduleSync);
    gd.on("plotly_relayouting", scheduleSync);
    gd.on("plotly_afterplot", scheduleSync);
    scheduleSync();
  }

  function init() {
    setupStrip();
    bindGraph(0);
    window.addEventListener("resize", scheduleSync);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
