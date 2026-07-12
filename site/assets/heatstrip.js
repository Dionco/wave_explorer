/**
 * Wave Explorer — Heat-strip mini-map
 *
 * A client-side navigation strip beneath the spectrum:
 *   - a viewport box tracks the spectrum's current x-range
 *   - click / drag the strip to move the spectrum view
 *
 * Reads / writes the view through window.WaveExplorer (exposed by
 * spectrum.js) — the heat-strip and the SVG spectrum share one view state.
 */

(function () {
  "use strict";

  var rafPending = false;
  var dragging = false;
  var dragPointerId = null;   // pointer that owns the active drag

  function clamp(v, lo, hi) {
    return v < lo ? lo : v > hi ? hi : v;
  }

  function bounds(strip) {
    var lmin = parseFloat(strip.dataset.lmin);
    var lmax = parseFloat(strip.dataset.lmax);
    if (!isFinite(lmin) || !isFinite(lmax) || lmax <= lmin) return null;
    return { lmin: lmin, lmax: lmax, span: lmax - lmin };
  }

  // -- Viewport sync --------------------------------------------------------

  function syncViewport() {
    rafPending = false;
    var strip = document.getElementById("heatstrip");
    var vp = document.getElementById("heatstrip-viewport");
    if (!strip || !vp || !window.WaveExplorer) return;
    var b = bounds(strip);
    var r = window.WaveExplorer.getView();
    if (!b || !r) return;
    var left = clamp(((r.min - b.lmin) / b.span) * 100, 0, 100);
    var right = clamp(((r.max - b.lmin) / b.span) * 100, 0, 100);
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
    var strip = document.getElementById("heatstrip");
    if (!strip || !window.WaveExplorer) return;
    var b = bounds(strip);
    var r = window.WaveExplorer.getView();
    if (!b || !r) return;
    var rect = strip.getBoundingClientRect();
    // A hidden/collapsed strip has width 0 → frac would be NaN and poison
    // the shared view state through setView. Bail out instead.
    if (!(rect.width > 0)) return;
    var frac = clamp((clientX - rect.left) / rect.width, 0, 1);
    if (!isFinite(frac)) return;
    var lam = b.lmin + frac * b.span;
    var viewSpan = Math.min(b.span, r.max - r.min);
    var lo = lam - viewSpan / 2;
    var hi = lam + viewSpan / 2;
    if (lo < b.lmin) { hi += b.lmin - lo; lo = b.lmin; }
    if (hi > b.lmax) { lo -= hi - b.lmax; hi = b.lmax; }
    window.WaveExplorer.setView(clamp(lo, b.lmin, b.lmax),
      clamp(hi, b.lmin, b.lmax));
  }

  function setupStrip() {
    var strip = document.getElementById("heatstrip");
    if (!strip) return;
    strip.addEventListener("pointerdown", function (e) {
      if (dragging) return; // a second pointer must not steal the drag
      dragging = true;
      dragPointerId = e.pointerId;
      try { strip.setPointerCapture(e.pointerId); } catch (err) {}
      jumpToClientX(e.clientX);
      e.preventDefault();
    });
    strip.addEventListener("pointermove", function (e) {
      if (dragging && e.pointerId === dragPointerId) jumpToClientX(e.clientX);
    });
    function endDrag(e) {
      if (dragging && e.pointerId !== dragPointerId) return;
      dragging = false;
      dragPointerId = null;
      try { strip.releasePointerCapture(e.pointerId); } catch (err) {}
    }
    strip.addEventListener("pointerup", endDrag);
    strip.addEventListener("pointercancel", endDrag);
  }

  // -- Init -----------------------------------------------------------------

  function bindViewChange(attempt) {
    if (window.WaveExplorer && window.WaveExplorer.onViewChange) {
      window.WaveExplorer.onViewChange(scheduleSync);
      scheduleSync();
      return;
    }
    if (attempt < 80) {
      setTimeout(function () { bindViewChange(attempt + 1); }, 150);
    }
  }

  var initAttempts = 0;

  function init() {
    // Dash renders the layout client-side after this script runs, so
    // #heatstrip may not exist yet — poll until it does before binding
    // the click/drag listeners (setupStrip does not retry on its own).
    var strip = document.getElementById("heatstrip");
    if (!strip) {
      if (++initAttempts > 100) {
        console.warn("wave-explorer heatstrip: #heatstrip never appeared; giving up");
        return;
      }
      setTimeout(init, 100);
      return;
    }
    setupStrip();
    bindViewChange(0);
    window.addEventListener("resize", scheduleSync);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
