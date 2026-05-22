/**
 * Wave Explorer — custom SVG spectrum component.
 *
 * Vanilla-JS port of the Claude Design `spectrum.jsx` handoff. Renders the
 * flux + residual panels into #spectrum-graph, owns pan / zoom / select /
 * edge-drag / draw / hover, and writes results back to Dash stores:
 *   - selected-region-store : {region_idx} on click  (null clears)
 *   - drag-result-store     : {region_idx, bound, new_x_nm} on edge-drag commit
 *   - draw-region-store     : {lo, hi} when the draw-confirm popover is accepted
 *
 * window.WaveExplorer exposes getView/setView/onViewChange for heatstrip.js.
 * window.activateDrawMode(bool) is kept for the existing draw-mode callbacks.
 */
(function () {
  "use strict";

  // ── Geometry (from spectrum.jsx) ─────────────────────────────────────────
  var PLOT_W = 1380;
  var MAIN = { top: 20, h: 320 };
  var GAP = 14;
  var RESID = { top: MAIN.top + MAIN.h + GAP, h: 130 };
  var X_LABEL_Y = RESID.top + RESID.h + 18;
  var PLOT_H = X_LABEL_Y + 14;
  var PAD = { right: 28, left: 60 };
  var innerW = PLOT_W - PAD.left - PAD.right;
  var fullBottom = RESID.top + RESID.h;

  var DRAG_THRESHOLD = 4; // px (SVG units) gate for click-vs-pan
  var MIN_SPAN = 0.4;     // nm — min zoom span
  var MIN_REGION_W = 0.005; // nm — min region width on edge-drag
  var EDGE_HIT = 8;       // half-width of an edge hit zone, SVG units

  // ── Module state ─────────────────────────────────────────────────────────
  var data = null;          // spectrum-data-store payload
  var llEntries = [];       // live region geometry/state (ll-entries-store)
  var pendingChanges = {};   // staged edits, keyed by string index
  var view = null;          // {min, max}
  var selectedIdx = null;
  var hoveredIdx = null;
  var cursorPx = null;       // SVG-space cursor x, or null
  var drawMode = false;
  var fluxRange = null;      // {min, max}
  var residMax = 1;          // symmetric resid half-range

  var interaction = null;    // active gesture (mutable during a drag)
  var rafPending = false;
  var viewChangeCbs = [];
  var svgEl = null;
  var lastGotoTick = null;   // last goto-region-store tick acted on

  // ── Quality coding ───────────────────────────────────────────────────────
  function qualityTier(c2) {
    if (c2 == null || !isFinite(c2)) return "miss";
    var t = (data && data.chi2Thresholds) || [5, 15, 30];
    if (c2 < t[0]) return "good";
    if (c2 < t[1]) return "fair";
    if (c2 < t[2]) return "poor";
    return "bad";
  }
  var Q_COLOR = {
    good: "#4f7a4d", fair: "#b88829", poor: "#c87338",
    bad: "#9c3d2e", miss: "#9c9684",
  };
  var Q_FILL = {
    good: "rgba(79,122,77,0.16)", fair: "rgba(184,136,41,0.16)",
    poor: "rgba(200,115,56,0.18)", bad: "rgba(156,61,46,0.20)",
    miss: "rgba(156,150,132,0.14)",
  };
  function qualityLabel(c2) {
    return { good: "GOOD", fair: "FAIR", poor: "POOR", bad: "BAD", miss: "—" }[
      qualityTier(c2)
    ];
  }
  function romanize(n) {
    return { 1: "I", 2: "II", 3: "III", 4: "IV", 5: "V" }[parseInt(n, 10)] ||
      String(n);
  }
  function elementColor(sym) {
    if (!data) return "#75705f";
    return (data.elementColors && data.elementColors[sym]) ||
      data.elementColorFallback || "#75705f";
  }

  // ── Accessors ────────────────────────────────────────────────────────────
  function host() { return document.getElementById("spectrum-graph"); }

  function effRegion(i) {
    // Region geometry/state merged with any staged pending edit.
    var base = llEntries[i];
    if (!base) return null;
    var pc = pendingChanges[String(i)] || {};
    return {
      idx: i,
      lower: pc.lower != null ? +pc.lower : +base.lower,
      upper: pc.upper != null ? +pc.upper : +base.upper,
      excluded: pc.excluded != null ? !!pc.excluded : !!base.excluded,
      element: String(base.element || "?"),
      ion: String(base.ion || "1"),
      pending: Object.keys(pc).length > 0,
    };
  }
  function regionChi2(i) {
    var r = data && data.regions && data.regions[i];
    return r ? r.chi2 : null;
  }
  function regionStats(i) {
    var r = (data && data.regions && data.regions[i]) || {};
    return { n_stars: r.n_stars || 0, n_pix: r.n_pix || 0 };
  }

  // ── Scales ───────────────────────────────────────────────────────────────
  function xScale(w) {
    return PAD.left + ((w - view.min) / (view.max - view.min)) * innerW;
  }
  function xInvert(px, v) {
    v = v || view;
    return v.min + ((px - PAD.left) / innerW) * (v.max - v.min);
  }
  function yMain(f) {
    var r = fluxRange;
    return MAIN.top + (1 - (f - r.min) / (r.max - r.min)) * MAIN.h;
  }
  function yResid(rv) {
    return RESID.top + RESID.h / 2 - (rv / residMax) * (RESID.h / 2);
  }

  function clampView(nmin, nmax) {
    var lo = data.lambdaMin, hi = data.lambdaMax;
    var maxSpan = hi - lo;
    var span = nmax - nmin;
    if (span < MIN_SPAN) {
      var c = (nmin + nmax) / 2;
      nmin = c - MIN_SPAN / 2; nmax = c + MIN_SPAN / 2; span = MIN_SPAN;
    }
    if (span > maxSpan) return { min: lo, max: hi };
    if (nmin < lo) { nmax += lo - nmin; nmin = lo; }
    if (nmax > hi) { nmin -= nmax - hi; nmax = hi; }
    return { min: nmin, max: nmax };
  }

  function sampleAt(key, lambda) {
    var arr = data[key], w = data.wavelengths;
    var frac = (lambda - data.lambdaMin) / (data.lambdaMax - data.lambdaMin);
    var i = Math.round(frac * (w.length - 1));
    i = Math.max(0, Math.min(w.length - 1, i));
    return arr[i];
  }

  // ── Path building ────────────────────────────────────────────────────────
  function buildPath(arr, yFn) {
    var w = data.wavelengths, d = "", started = false;
    for (var i = 0; i < w.length; i++) {
      if (w[i] < view.min - 0.05 || w[i] > view.max + 0.05) continue;
      var x = xScale(w[i]).toFixed(2), y = yFn(arr[i]).toFixed(2);
      d += (started ? "L" : "M") + x + "," + y;
      started = true;
    }
    return d;
  }

  function ticks() {
    var span = view.max - view.min, step;
    if (span < 2) step = 0.2;
    else if (span < 5) step = 0.5;
    else if (span < 12) step = 1;
    else if (span < 25) step = 2;
    else step = 5;
    var arr = [], start = Math.ceil(view.min / step) * step;
    for (var t = start; t <= view.max; t += step) arr.push(t);
    return { arr: arr, step: step };
  }

  // ── SVG element helper ───────────────────────────────────────────────────
  var NS = "http://www.w3.org/2000/svg";
  function el(tag, attrs, text) {
    var n = document.createElementNS(NS, tag);
    for (var k in attrs) {
      if (attrs[k] != null) n.setAttribute(k, attrs[k]);
    }
    if (text != null) n.textContent = text;
    return n;
  }

  // ── Render ───────────────────────────────────────────────────────────────
  function render() {
    var h = host();
    if (!h || !data || !view) return;
    if (!svgEl) {
      svgEl = el("svg", {
        class: "spectrum-svg",
        viewBox: "0 0 " + PLOT_W + " " + PLOT_H,
        preserveAspectRatio: "none",
      });
      svgEl.style.touchAction = "none";
      h.appendChild(svgEl);
      bindPointer();
    }
    svgEl.setAttribute(
      "class",
      "spectrum-svg" +
        (interaction && interaction.kind === "pan" && interaction.activated
          ? " panning"
          : "") +
        (drawMode || (interaction && interaction.kind === "draw")
          ? " drawing"
          : "")
    );

    var tk = ticks();
    var fluxTicks = niceTicks(fluxRange.min, fluxRange.max, 5);
    var residTicks = [-residMax * 0.66, 0, residMax * 0.66];
    var parts = [];

    // backgrounds
    parts.push(rect(PAD.left, MAIN.top, innerW, MAIN.h, "var(--paper)"));
    parts.push(rect(PAD.left, RESID.top, innerW, RESID.h, "var(--paper-soft)"));

    // grid
    var grid = el("g", { class: "spectrum-grid" });
    tk.arr.forEach(function (t) {
      grid.appendChild(line(xScale(t), MAIN.top, xScale(t), MAIN.top + MAIN.h));
      grid.appendChild(line(xScale(t), RESID.top, xScale(t), RESID.top + RESID.h));
    });
    fluxTicks.forEach(function (f) {
      grid.appendChild(line(PAD.left, yMain(f), PAD.left + innerW, yMain(f)));
    });
    residTicks.forEach(function (rv) {
      grid.appendChild(line(PAD.left, yResid(rv), PAD.left + innerW, yResid(rv)));
    });
    parts.push(grid);

    // continuum + zero lines
    parts.push(el("line", {
      class: "continuum-line",
      x1: PAD.left, x2: PAD.left + innerW, y1: yMain(1.0), y2: yMain(1.0),
    }));
    parts.push(el("line", {
      x1: PAD.left, x2: PAD.left + innerW, y1: yResid(0), y2: yResid(0),
      stroke: "var(--ink-3)", "stroke-width": 0.8, opacity: 0.5,
    }));

    // region bands
    parts.push(renderRegions());

    // draw-in-progress preview
    if (interaction && interaction.kind === "draw" && interaction.preview) {
      var p = interaction.preview;
      var dx1 = xScale(Math.min(p.x0, p.x1)), dx2 = xScale(Math.max(p.x0, p.x1));
      parts.push(el("rect", {
        x: dx1, y: MAIN.top, width: Math.max(1, dx2 - dx1),
        height: fullBottom - MAIN.top, fill: "rgba(179,85,59,0.18)",
        stroke: "var(--accent)", "stroke-width": 1.5, "stroke-dasharray": "4 3",
      }));
    }

    // data lines
    parts.push(el("path", { class: "obs-line", d: buildPath(data.flux, yMain) }));
    parts.push(el("path", { class: "fit-line", d: buildPath(data.fitFlux, yMain) }));
    parts.push(el("path", { class: "resid-line", d: buildPath(data.resid, yResid) }));

    // residual outlier dots
    var dots = el("g", {});
    var w = data.wavelengths, rd = data.resid;
    for (var i = 0; i < w.length; i++) {
      if (w[i] < view.min || w[i] > view.max) continue;
      if (Math.abs(rd[i]) > residMax * 0.55) {
        dots.appendChild(el("circle", {
          cx: xScale(w[i]), cy: yResid(rd[i]), r: 1.6,
          fill: rd[i] > 0 ? "var(--accent)" : "var(--ink)", opacity: 0.7,
        }));
      }
    }
    parts.push(dots);

    // cursor crosshair
    if (cursorPx != null && cursorPx > PAD.left && cursorPx < PAD.left + innerW) {
      parts.push(el("line", {
        x1: cursorPx, x2: cursorPx, y1: MAIN.top, y2: fullBottom,
        stroke: "var(--ink)", "stroke-width": 0.6, "stroke-dasharray": "2 3",
        opacity: 0.35, "pointer-events": "none",
      }));
    }

    // axes
    parts.push(renderAxes(tk, fluxTicks, residTicks));

    // commit
    svgEl.textContent = "";
    parts.forEach(function (n) { svgEl.appendChild(n); });
  }

  function rect(x, y, w, h, fill) {
    return el("rect", { x: x, y: y, width: w, height: h, fill: fill });
  }
  function line(x1, y1, x2, y2) {
    return el("line", { x1: x1, y1: y1, x2: x2, y2: y2 });
  }

  function renderRegions() {
    var g = el("g", {});
    for (var i = 0; i < llEntries.length; i++) {
      var r = effRegion(i);
      if (!r) continue;
      if (r.upper < view.min || r.lower > view.max) continue;
      var x1 = xScale(r.lower), x2 = xScale(r.upper);
      var bw = Math.max(1, x2 - x1);
      var c2 = regionChi2(i);
      var tier = qualityTier(c2);
      var fill = r.excluded ? "rgba(156,61,46,0.07)" : Q_FILL[tier];
      var stroke = r.excluded ? "rgba(156,61,46,0.5)" : Q_COLOR[tier];
      var isSel = i === selectedIdx;
      var isHov = i === hoveredIdx;
      var dim = selectedIdx != null && !isSel;

      var rg = el("g", { class: "region-band" + (dim ? " dim" : "") });

      // main + resid bands
      rg.appendChild(el("rect", {
        x: x1, y: MAIN.top, width: bw, height: MAIN.h, fill: fill,
        stroke: r.excluded ? stroke : "none",
        "stroke-dasharray": r.excluded ? "3 3" : null,
        "stroke-width": r.excluded ? 1 : 0,
        "data-region": i, style: "cursor:pointer",
      }));
      rg.appendChild(el("rect", {
        x: x1, y: RESID.top, width: bw, height: RESID.h, fill: fill,
        opacity: 0.7, "data-region": i, style: "cursor:pointer",
      }));
      // element rail (bottom of main)
      rg.appendChild(el("rect", {
        x: x1, y: MAIN.top + MAIN.h - 3, width: bw, height: 3,
        fill: elementColor(r.element), opacity: r.excluded ? 0.3 : 0.9,
      }));
      // quality stripe (top of main)
      rg.appendChild(el("rect", {
        x: x1, y: MAIN.top, width: bw, height: 2, fill: stroke,
        opacity: r.excluded ? 0.25 : 1,
      }));
      // pending accent stripe
      if (r.pending && !r.excluded) {
        rg.appendChild(el("rect", {
          x: x1, y: MAIN.top + 4, width: bw, height: 2, fill: "var(--accent)",
        }));
      }
      // selection glow
      if (isSel) {
        rg.appendChild(el("rect", {
          x: x1 - 2, y: MAIN.top - 2, width: x2 - x1 + 4,
          height: fullBottom - MAIN.top + 4, rx: 3, fill: "none",
          stroke: "var(--accent)", "stroke-width": 2, opacity: 0.85,
        }));
      } else if (isHov) {
        rg.appendChild(el("rect", {
          x: x1 - 1, y: MAIN.top, width: x2 - x1 + 2,
          height: fullBottom - MAIN.top, fill: "none", stroke: stroke,
          "stroke-width": 1.5, opacity: 0.6,
        }));
      }
      // edge handles — only on the selected region
      if (isSel) {
        [["lo", x1], ["hi", x2]].forEach(function (pair) {
          var edge = pair[0], hx = pair[1];
          rg.appendChild(el("rect", {
            class: "region-edge", "data-region-edge": edge, "data-region": i,
            x: hx - EDGE_HIT, y: MAIN.top, width: EDGE_HIT * 2,
            height: fullBottom - MAIN.top,
          }));
          var hg = el("g", {
            transform: "translate(" + hx + "," + (MAIN.top + MAIN.h / 2) + ")",
            style: "pointer-events:none",
          });
          hg.appendChild(el("line", {
            x1: 0, x2: 0, y1: MAIN.top - (MAIN.top + MAIN.h / 2),
            y2: fullBottom - (MAIN.top + MAIN.h / 2), stroke: stroke,
            "stroke-width": 1, opacity: 0.6, "stroke-dasharray": "3 2",
          }));
          hg.appendChild(el("rect", {
            class: "drag-handle", x: -5, y: -16, width: 10, height: 32, rx: 2.5,
          }));
          rg.appendChild(hg);
        });
      }
      // element label
      if (bw > 30) {
        rg.appendChild(el("text", {
          class: "element-label", x: (x1 + x2) / 2, y: MAIN.top + 14,
          fill: elementColor(r.element), opacity: r.excluded ? 0.45 : 1,
        }, r.element + " " + romanize(r.ion)));
      }
      g.appendChild(rg);
    }
    return g;
  }

  function renderAxes(tk, fluxTicks, residTicks) {
    var g = el("g", {});
    // x-axis
    g.appendChild(el("line", {
      x1: PAD.left, x2: PAD.left + innerW, y1: fullBottom, y2: fullBottom,
      stroke: "var(--hairline)",
    }));
    tk.arr.forEach(function (t) {
      g.appendChild(el("line", {
        x1: xScale(t), x2: xScale(t), y1: fullBottom, y2: fullBottom + 4,
        stroke: "var(--hairline)",
      }));
      g.appendChild(el("text", {
        class: "spectrum-axis-label", x: xScale(t), y: fullBottom + 18,
        "text-anchor": "middle",
      }, t.toFixed(tk.step < 1 ? 1 : 0)));
    });
    g.appendChild(el("text", {
      class: "spectrum-axis-label", x: PLOT_W - PAD.right, y: fullBottom + 18,
      "text-anchor": "end", style: "font-weight:600",
    }, "λ (nm)"));
    // main y-axis
    g.appendChild(el("line", {
      x1: PAD.left, x2: PAD.left, y1: MAIN.top, y2: MAIN.top + MAIN.h,
      stroke: "var(--hairline)",
    }));
    fluxTicks.forEach(function (f) {
      g.appendChild(el("text", {
        class: "spectrum-axis-label", x: PAD.left - 8, y: yMain(f) + 3,
        "text-anchor": "end",
      }, f.toFixed(2)));
    });
    g.appendChild(el("text", {
      class: "spectrum-axis-label", x: PAD.left + 6, y: MAIN.top + 12,
      "text-anchor": "start", style: "font-weight:600",
    }, "normalized flux"));
    // resid y-axis
    g.appendChild(el("line", {
      x1: PAD.left, x2: PAD.left, y1: RESID.top, y2: RESID.top + RESID.h,
      stroke: "var(--hairline)",
    }));
    residTicks.forEach(function (rv) {
      g.appendChild(el("text", {
        class: "spectrum-axis-label", x: PAD.left - 8, y: yResid(rv) + 3,
        "text-anchor": "end",
      }, (rv > 0 ? "+" : "") + rv.toFixed(3)));
    });
    g.appendChild(el("text", {
      class: "spectrum-axis-label", x: PAD.left + 6, y: RESID.top + 12,
      "text-anchor": "start", style: "font-weight:600",
    }, "obs − fit"));
    // legend
    var lg = el("g", {
      transform: "translate(" + (PLOT_W - PAD.right - 200) + "," +
        (MAIN.top + 8) + ")",
    });
    lg.appendChild(el("rect", {
      x: 0, y: 0, width: 196, height: 26, rx: 5, fill: "var(--paper)",
      stroke: "var(--hairline-soft)",
    }));
    lg.appendChild(el("line", {
      x1: 10, x2: 28, y1: 13, y2: 13, stroke: "var(--ink-3)", "stroke-width": 1.4,
    }));
    lg.appendChild(el("text", {
      class: "spectrum-axis-label", x: 32, y: 16,
    }, "obs"));
    lg.appendChild(el("line", {
      x1: 66, x2: 84, y1: 13, y2: 13, stroke: "var(--accent)", "stroke-width": 1.6,
    }));
    lg.appendChild(el("text", {
      class: "spectrum-axis-label", x: 88, y: 16,
    }, "fit"));
    lg.appendChild(el("line", {
      x1: 118, x2: 136, y1: 13, y2: 13, stroke: "var(--ink-3)",
      "stroke-width": 1.2, "stroke-dasharray": "3 2",
    }));
    lg.appendChild(el("text", {
      class: "spectrum-axis-label", x: 140, y: 16,
    }, "resid"));
    g.appendChild(lg);
    return g;
  }

  function niceTicks(lo, hi, count) {
    var step = (hi - lo) / (count - 1), out = [];
    for (var i = 0; i < count; i++) out.push(lo + i * step);
    return out;
  }

  // ── Render scheduling ────────────────────────────────────────────────────
  function scheduleRender() {
    if (rafPending) return;
    rafPending = true;
    window.requestAnimationFrame(function () {
      rafPending = false;
      render();
    });
  }

  // ── Pointer interaction ──────────────────────────────────────────────────
  function svgCoords(e) {
    var rect = svgEl.getBoundingClientRect();
    var px = ((e.clientX - rect.left) / rect.width) * PLOT_W;
    return { px: px, lambda: xInvert(px), clientX: e.clientX, clientY: e.clientY };
  }

  function bindPointer() {
    svgEl.addEventListener("pointerdown", onDown);
    svgEl.addEventListener("pointermove", onMove);
    svgEl.addEventListener("pointerup", onUp);
    svgEl.addEventListener("pointercancel", onCancel);
    svgEl.addEventListener("pointerleave", onLeave);
    svgEl.addEventListener("wheel", onWheel, { passive: false });
  }

  function onDown(e) {
    if (e.button !== 0) return;
    var p = svgCoords(e);
    svgEl.setPointerCapture(e.pointerId);

    if (drawMode) {
      interaction = { kind: "draw", startLambda: p.lambda,
        preview: { x0: p.lambda, x1: p.lambda }, pointerId: e.pointerId };
      scheduleRender();
      return;
    }

    var edge = e.target && e.target.getAttribute &&
      e.target.getAttribute("data-region-edge");
    if (edge && selectedIdx != null) {
      var r = effRegion(selectedIdx);
      if (r) {
        interaction = { kind: "edge", regionIdx: selectedIdx, edge: edge,
          originalLo: r.lower, originalHi: r.upper, pointerId: e.pointerId };
        return;
      }
    }

    interaction = { kind: "pan", startClientX: e.clientX,
      viewMin: view.min, viewMax: view.max, pointerId: e.pointerId,
      downLambda: p.lambda, activated: false };
  }

  function onMove(e) {
    var p = svgCoords(e);
    cursorPx = p.px;
    var it = interaction;

    if (it && it.kind === "edge") {
      var lo = it.originalLo, hi = it.originalHi;
      if (it.edge === "lo") lo = Math.min(p.lambda, hi - MIN_REGION_W);
      else hi = Math.max(p.lambda, lo + MIN_REGION_W);
      stageEdgePreview(it.regionIdx, lo, hi);
      scheduleRender();
      return;
    }
    if (it && it.kind === "draw") {
      it.preview = { x0: it.startLambda, x1: p.lambda };
      scheduleRender();
      return;
    }
    if (it && it.kind === "pan") {
      var dxPx = e.clientX - it.startClientX;
      if (!it.activated) {
        var dxSvgGate = (dxPx / svgEl.getBoundingClientRect().width) * PLOT_W;
        if (Math.abs(dxSvgGate) < DRAG_THRESHOLD) return;
        it.activated = true;
      }
      var dxSvg = (dxPx / svgEl.getBoundingClientRect().width) * PLOT_W;
      var span = it.viewMax - it.viewMin;
      var dLambda = -(dxSvg / innerW) * span;
      view = clampView(it.viewMin + dLambda, it.viewMax + dLambda);
      emitViewChange();
      scheduleRender();
      return;
    }

    // hover
    var hit = hitRegion(p.lambda);
    hoveredIdx = hit;
    updateTooltip(p);
    scheduleRender();
  }

  function onUp(e) {
    var it = interaction;
    try { svgEl.releasePointerCapture(e.pointerId); } catch (_) {}

    if (it && it.kind === "edge") {
      var r = effRegion(it.regionIdx);
      if (r) {
        var bound = it.edge === "lo" ? "lower" : "upper";
        var newX = it.edge === "lo" ? r.lower : r.upper;
        setProps("drag-result-store",
          { region_idx: it.regionIdx, bound: bound, new_x_nm: newX });
      }
      interaction = null;
      return;
    }
    if (it && it.kind === "draw") {
      var p = svgCoords(e);
      var lo = Math.min(it.startLambda, p.lambda);
      var hi = Math.max(it.startLambda, p.lambda);
      interaction = null;
      if (hi - lo > 0.01) openDrawPopover(lo, hi, e.clientX, e.clientY);
      else scheduleRender();
      return;
    }
    if (it && it.kind === "pan") {
      if (!it.activated) {
        var sel = hitRegion(it.downLambda);
        selectedIdx = sel;
        setProps("selected-region-store", sel == null ? null : { region_idx: sel });
      }
      interaction = null;
      scheduleRender();
      return;
    }
  }

  function onCancel(e) {
    try { svgEl.releasePointerCapture(e.pointerId); } catch (_) {}
    interaction = null;
    scheduleRender();
  }

  function onLeave() {
    if (interaction) return;
    cursorPx = null;
    hoveredIdx = null;
    hideTooltip();
    scheduleRender();
  }

  function onWheel(e) {
    e.preventDefault();
    var p = svgCoords(e);
    var factor = e.deltaY > 0 ? 1.15 : 1 / 1.15;
    var span = view.max - view.min;
    var newSpan = Math.max(MIN_SPAN,
      Math.min(data.lambdaMax - data.lambdaMin, span * factor));
    var nmin = p.lambda - ((p.lambda - view.min) / span) * newSpan;
    view = clampView(nmin, nmin + newSpan);
    emitViewChange();
    scheduleRender();
  }

  function hitRegion(lambda) {
    for (var i = 0; i < llEntries.length; i++) {
      var r = effRegion(i);
      if (r && lambda >= r.lower && lambda <= r.upper) return i;
    }
    return null;
  }

  // Stage an in-flight edge preview into pendingChanges so the band stretches
  // live. Mirrors the server's stage_drag; the committed value is sent on up.
  function stageEdgePreview(i, lo, hi) {
    var pc = Object.assign({}, pendingChanges[String(i)] || {});
    pc.lower = lo; pc.upper = hi; pc.center = 0.5 * (lo + hi);
    pendingChanges = Object.assign({}, pendingChanges);
    pendingChanges[String(i)] = pc;
  }

  // ── Tooltip ──────────────────────────────────────────────────────────────
  function updateTooltip(p) {
    var tip = document.getElementById("cursor-tooltip");
    if (!tip || !data) return;
    var cl = p.lambda;
    var head;
    if (hoveredIdx != null) {
      var r = effRegion(hoveredIdx), c2 = regionChi2(hoveredIdx);
      var st = regionStats(hoveredIdx);
      head =
        '<div class="tt-title"><span>Region #' + (hoveredIdx + 1) +
        '</span><span class="q-badge q-' + qualityTier(c2) + '">' +
        qualityLabel(c2) + "</span></div>" +
        ttRow("χ²/N", c2 != null && isFinite(c2) ? c2.toFixed(3) : "—") +
        ttRow("range", r.lower.toFixed(3) + " – " + r.upper.toFixed(3)) +
        ttRow("width", (r.upper - r.lower).toFixed(3) + " nm") +
        ttRow("n stars", st.n_stars) +
        ttRow("n pix", st.n_pix) +
        '<div class="tt-sep"></div>';
    } else {
      head = '<div class="tt-title"><span>cursor</span></div>';
    }
    var resid = sampleAt("resid", cl);
    tip.innerHTML = head +
      ttRow("cursor λ", cl.toFixed(3)) +
      ttRow("obs flux", sampleAt("flux", cl).toFixed(4)) +
      ttRow("fit", sampleAt("fitFlux", cl).toFixed(4)) +
      ttRow("resid", (resid >= 0 ? "+" : "") + resid.toFixed(4));
    tip.style.display = "block";
    tip.style.left = (p.clientX + 16) + "px";
    tip.style.top = (p.clientY + 16) + "px";
  }
  function ttRow(k, v) {
    return '<div class="tt-row"><span>' + k + "</span><span>" + v +
      "</span></div>";
  }
  function hideTooltip() {
    var tip = document.getElementById("cursor-tooltip");
    if (tip) tip.style.display = "none";
  }

  // ── Draw-confirm popover ─────────────────────────────────────────────────
  function openDrawPopover(lo, hi, clientX, clientY) {
    var pop = document.getElementById("draw-confirm-popover");
    if (!pop) return;
    var rt = document.getElementById("draw-confirm-range-text");
    if (rt) rt.textContent = lo.toFixed(3) + " – " + hi.toFixed(3) + " nm";
    pop.setAttribute("data-lo", lo);
    pop.setAttribute("data-hi", hi);
    pop.style.display = "block";
    pop.style.left = clientX + "px";
    pop.style.top = (clientY - 40) + "px";
  }
  function wirePopover() {
    var acc = document.getElementById("draw-confirm-accept");
    var can = document.getElementById("draw-confirm-cancel");
    if (acc && !acc.__weBound) {
      acc.__weBound = true;
      acc.addEventListener("click", function () {
        var pop = document.getElementById("draw-confirm-popover");
        if (!pop) return;
        var lo = parseFloat(pop.getAttribute("data-lo"));
        var hi = parseFloat(pop.getAttribute("data-hi"));
        if (isFinite(lo) && isFinite(hi)) {
          setProps("draw-region-store", { lo: lo, hi: hi });
        }
        pop.style.display = "none";
      });
    }
    if (can && !can.__weBound) {
      can.__weBound = true;
      can.addEventListener("click", function () {
        var pop = document.getElementById("draw-confirm-popover");
        if (pop) pop.style.display = "none";
      });
    }
  }

  // ── Dash store writes ────────────────────────────────────────────────────
  function setProps(id, value) {
    if (window.dash_clientside && window.dash_clientside.set_props) {
      window.dash_clientside.set_props(id, { data: value });
    }
  }

  // ── View-change notification (heatstrip) ─────────────────────────────────
  function emitViewChange() {
    viewChangeCbs.forEach(function (cb) {
      try { cb(view.min, view.max); } catch (_) {}
    });
  }

  // ── Frame a region — move + zoom the view to it (table "go to") ──────────
  function frameRegion(i) {
    var r = effRegion(i);
    if (!r || !data) return;
    var center = 0.5 * (r.lower + r.upper);
    var width = r.upper - r.lower;
    var span = Math.max(MIN_SPAN, width * 6);
    view = clampView(center - span / 2, center + span / 2);
    emitViewChange();
    scheduleRender();
  }

  // ── Public sync entry — called by the Dash clientside callback ───────────
  function sync(specData, entries, pending, selected, drawActive, goto) {
    var firstData = false;
    if (specData && specData.wavelengths) {
      if (!data) firstData = true;
      data = specData;
    }
    if (!data) return;
    if (firstData) {
      var fmin = Infinity, fmax = -Infinity, rmax = 0;
      for (var i = 0; i < data.flux.length; i++) {
        fmin = Math.min(fmin, data.flux[i], data.fitFlux[i]);
        fmax = Math.max(fmax, data.flux[i], data.fitFlux[i]);
        rmax = Math.max(rmax, Math.abs(data.resid[i]));
      }
      var fpad = 0.04 * (fmax - fmin || 1);
      fluxRange = { min: fmin - fpad, max: fmax + fpad };
      residMax = Math.max(0.01, rmax * 1.15);
      view = { min: data.lambdaMin, max: data.lambdaMax };
    }
    if (entries != null) llEntries = entries;
    if (pending != null) pendingChanges = pending || {};
    selectedIdx = selected && selected.region_idx != null
      ? selected.region_idx : null;
    drawMode = !!drawActive;
    wirePopover();

    // Table "go to region": frame the region when the tick advances.
    if (goto && goto.tick != null && goto.tick !== lastGotoTick) {
      lastGotoTick = goto.tick;
      if (goto.region_idx != null) frameRegion(goto.region_idx);
    }
    scheduleRender();
  }

  // ── window.WaveExplorer API + draw-mode hook ─────────────────────────────
  window.WaveExplorer = {
    sync: sync,
    getView: function () { return view ? { min: view.min, max: view.max } : null; },
    setView: function (min, max) {
      if (!data) return;
      view = clampView(min, max);
      emitViewChange();
      scheduleRender();
    },
    onViewChange: function (cb) { viewChangeCbs.push(cb); },
  };
  window.activateDrawMode = function (active) {
    drawMode = !!active;
    if (drawMode && interaction && interaction.kind !== "draw") {
      interaction = null;
    }
    scheduleRender();
  };

  // ── Init — wait for the host div ─────────────────────────────────────────
  function init() {
    if (!host()) { setTimeout(init, 100); return; }
    if (window.__weSpectrumPending) {
      sync.apply(null, window.__weSpectrumPending);
    }
  }
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
