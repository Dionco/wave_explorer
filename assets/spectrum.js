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

  var MAIN_H_NORMAL = MAIN.h;                  // 320
  var MAIN_H_STACKED = fullBottom - MAIN.top;  // resid panel absorbed

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
  var hoveredStar = null;    // index into data.stars (stacked mode)
  var cursorPx = null;       // SVG-space cursor x, or null
  var drawMode = false;
  var fluxRange = null;      // {min, max}
  var residMax = 1;          // symmetric resid half-range

  // ── VALD overlay state ───────────────────────────────────────────────────
  var vald = null;          // {wavelengths, elements, ions, depths, ...}
  var valdVisible = false;
  var valdDepthMin = 0.10;

  var interaction = null;    // active gesture (mutable during a drag)
  var rafPending = false;
  var rafDynPending = false; // pending lightweight (hover-layer) update
  var viewChangeCbs = [];
  var svgEl = null;
  var dynamicLayer = null;   // crosshair / hover-outline / draw-preview layer
  var rectCache = null;      // per-frame getBoundingClientRect cache
  var lastGotoTick = null;   // last goto-region-store tick acted on
  var lastPayloadFp = null;  // fingerprint of the last spectrum payload

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
  function teffColor(t) {
    if (!data || !data.stars || data.stars.length < 2) return "var(--accent)";
    var ts = data.stars.map(function (s) { return s.teff; });
    var tmin = Math.min.apply(null, ts), tmax = Math.max.apply(null, ts);
    var u = tmax > tmin ? (t - tmin) / (tmax - tmin) : 0.5;
    // cool red (hue 8) → hot blue (hue 215)
    return "hsl(" + Math.round(8 + 207 * u) + ", 58%, 42%)";
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

  function nearbyVald(lambda, halfWidthNm, maxRows) {
    if (!vald || !vald.wavelengths || !valdVisible) return [];
    var w = vald.wavelengths;
    var hits = [];
    for (var i = lowerBound(w, lambda - halfWidthNm); i < w.length; i++) {
      if (w[i] - lambda > halfWidthNm) break;  // sorted → can short-circuit
      if (vald.depths[i] < valdDepthMin) continue;
      hits.push({ idx: i, dist: Math.abs(w[i] - lambda) });
    }
    hits.sort(function (a, b) { return a.dist - b.dist; });
    return hits.slice(0, maxRows);
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
    var EPS = 1e-6;
    // Reject non-finite inputs (e.g. NaN from a zero-width heatstrip drag):
    // keep the current view instead of poisoning the scales.
    if (!isFinite(nmin) || !isFinite(nmax)) {
      return view || { min: lo, max: Math.max(hi, lo + EPS) };
    }
    // Degenerate data domain (lambdaMin === lambdaMax) → force a tiny span
    // so xScale never divides by zero.
    var maxSpan = Math.max(hi - lo, EPS);
    var span = nmax - nmin;
    if (span < MIN_SPAN) {
      var c = (nmin + nmax) / 2;
      nmin = c - MIN_SPAN / 2; nmax = c + MIN_SPAN / 2; span = MIN_SPAN;
    }
    if (span >= maxSpan) return { min: lo, max: Math.max(hi, lo + EPS) };
    if (nmin < lo) { nmax += lo - nmin; nmin = lo; }
    if (nmax > hi) { nmin -= nmax - hi; nmax = hi; }
    return { min: nmin, max: nmax };
  }

  // Smallest index i in sorted-ascending array `w` with w[i] >= x.
  function lowerBound(w, x) {
    var lo = 0, hi = w.length;
    while (lo < hi) {
      var mid = (lo + hi) >> 1;
      if (w[mid] < x) lo = mid + 1; else hi = mid;
    }
    return lo;
  }

  // Nearest index in the sorted-ascending `data.wavelengths` to `lambda`,
  // via binary search (O(log n)). Works for the uniform mean grid AND the
  // non-uniform single-star full-range axis, unlike a fractional-index map.
  function nearestIndex(lambda) {
    var w = data.wavelengths, n = w.length;
    if (n === 0) return 0;
    var lo = 0, hi = n - 1;
    if (lambda <= w[0]) return 0;
    if (lambda >= w[hi]) return hi;
    while (hi - lo > 1) {
      var mid = (lo + hi) >> 1;
      if (w[mid] <= lambda) lo = mid; else hi = mid;
    }
    // lo and hi now bracket lambda; pick the closer of the two.
    return (lambda - w[lo] <= w[hi] - lambda) ? lo : hi;
  }

  function sampleAt(key, lambda) {
    return data[key][nearestIndex(lambda)];
  }

  // Inclusive index range [i0, i1] of data.wavelengths inside [loLam, hiLam]
  // (binary search — replaces per-frame O(N) scans). Empty range → i1 < i0.
  function viewIndexRange(loLam, hiLam) {
    var w = data.wavelengths, n = w.length;
    if (!n || hiLam < w[0] || loLam > w[n - 1]) return { i0: 0, i1: -1 };
    var i0 = nearestIndex(loLam);
    if (w[i0] < loLam) i0++;
    var i1 = nearestIndex(hiLam);
    if (w[i1] > hiLam) i1--;
    return { i0: i0, i1: i1 };
  }

  // ── Path building ────────────────────────────────────────────────────────
  function buildPath(arr, yFn, offset) {
    var w = data.wavelengths, d = "", started = false;
    var off = offset || 0;
    var rng = viewIndexRange(view.min - 0.05, view.max + 0.05);
    for (var i = rng.i0; i <= rng.i1; i++) {
      var v = arr[i];
      // Non-finite / null samples are gaps → break the path (new M next).
      if (v == null || !isFinite(v)) { started = false; continue; }
      var x = xScale(w[i]).toFixed(2), y = yFn(v + off).toFixed(2);
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
    // Index-based loop — `t += step` accumulates FP error and can drop the
    // final tick when start + k*step lands a hair above view.max.
    var arr = [], start = Math.ceil(view.min / step) * step;
    var count = Math.floor((view.max - start) / step + 1e-9) + 1;
    for (var i = 0; i < count; i++) arr.push(start + i * step);
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
  function updateSvgClass() {
    if (!svgEl) return;
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
  }

  function render() {
    var h = host();
    if (!h || !data || !view) return;
    // Dash re-rendered #spectrum-graph → our svg node is detached; drop the
    // stale reference so the plot is re-created (and handlers re-bound).
    if (svgEl && (!svgEl.isConnected || svgEl.parentNode !== h)) {
      svgEl = null;
      dynamicLayer = null;
    }
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
    updateSvgClass();

    var tk = ticks();
    var stk = !!(data && data.stacked);
    var fluxTicks = niceTicks(fluxRange.min, fluxRange.max, stk ? 9 : 5);
    var residTicks = [-residMax * 0.66, 0, residMax * 0.66];
    var parts = [];

    // clip paths — keep out-of-range paths from spilling across panels
    var defs = el("defs", {});
    var cpMain = el("clipPath", { id: "we-clip-main" });
    cpMain.appendChild(el("rect", {
      x: PAD.left, y: MAIN.top, width: innerW, height: MAIN.h,
    }));
    defs.appendChild(cpMain);
    var cpResid = el("clipPath", { id: "we-clip-resid" });
    cpResid.appendChild(el("rect", {
      x: PAD.left, y: RESID.top, width: innerW, height: RESID.h,
    }));
    defs.appendChild(cpResid);
    // whole plot area, with a little y-padding for the selection glow
    var cpPlot = el("clipPath", { id: "we-clip-plot" });
    cpPlot.appendChild(el("rect", {
      x: PAD.left, y: MAIN.top - 4, width: innerW,
      height: fullBottom - MAIN.top + 8,
    }));
    defs.appendChild(cpPlot);
    parts.push(defs);

    // backgrounds
    parts.push(rect(PAD.left, MAIN.top, innerW, MAIN.h, "var(--paper)"));
    if (!stk) {
      parts.push(rect(PAD.left, RESID.top, innerW, RESID.h, "var(--paper-soft)"));
    }

    // grid
    var grid = el("g", { class: "spectrum-grid" });
    tk.arr.forEach(function (t) {
      grid.appendChild(line(xScale(t), MAIN.top, xScale(t), MAIN.top + MAIN.h));
      if (!stk) {
        grid.appendChild(line(xScale(t), RESID.top, xScale(t), RESID.top + RESID.h));
      }
    });
    fluxTicks.forEach(function (f) {
      grid.appendChild(line(PAD.left, yMain(f), PAD.left + innerW, yMain(f)));
    });
    if (!stk) {
      residTicks.forEach(function (rv) {
        grid.appendChild(line(PAD.left, yResid(rv), PAD.left + innerW, yResid(rv)));
      });
    }
    parts.push(grid);

    // continuum + zero lines
    if (stk) {
      data.stars.forEach(function (s) {
        parts.push(el("line", {
          class: "continuum-line",
          x1: PAD.left, x2: PAD.left + innerW,
          y1: yMain(1.0 + s.offset), y2: yMain(1.0 + s.offset),
          opacity: 0.35,
        }));
      });
    } else {
      parts.push(el("line", {
        class: "continuum-line",
        x1: PAD.left, x2: PAD.left + innerW, y1: yMain(1.0), y2: yMain(1.0),
      }));
      parts.push(el("line", {
        x1: PAD.left, x2: PAD.left + innerW, y1: yResid(0), y2: yResid(0),
        stroke: "var(--ink-3)", "stroke-width": 0.8, opacity: 0.5,
      }));
    }

    // region bands
    var regionsG = renderRegions();
    regionsG.setAttribute("clip-path", "url(#we-clip-plot)");
    parts.push(regionsG);

    // VALD line overlay (vertical dashed markers, below data lines so they
    // do not occlude the obs/fit curves)
    var valdG = renderVald();
    valdG.setAttribute("clip-path", "url(#we-clip-plot)");
    parts.push(valdG);

    // data lines — clipped to their panels
    var mainG = el("g", { "clip-path": "url(#we-clip-main)" });
    var residG = el("g", { "clip-path": "url(#we-clip-resid)" });
    if (stk) {
      data.stars.forEach(function (s, k) {
        var hov = hoveredStar === k;
        mainG.appendChild(el("path", {
          class: "obs-line",
          d: buildPath(s.flux, yMain, s.offset),
          style: hov ? "opacity:1;stroke-width:1.5" : null,
        }));
        mainG.appendChild(el("path", {
          class: "fit-line",
          d: buildPath(s.fitFlux, yMain, s.offset),
          style: "stroke:" + teffColor(s.teff) +
            (hov ? ";stroke-width:2.2" : ""),
        }));
      });
      // pinned star labels at the left edge
      data.stars.forEach(function (s) {
        mainG.appendChild(el("text", {
          class: "star-label",
          x: PAD.left + 8,
          y: yMain(1.0 + s.offset) - 6,
          fill: teffColor(s.teff),
        }, s.slug + " · " + Math.round(s.teff) + " K"));
      });
      parts.push(mainG);
    } else {
      mainG.appendChild(el("path", { class: "obs-line", d: buildPath(data.flux, yMain) }));
      mainG.appendChild(el("path", { class: "fit-line", d: buildPath(data.fitFlux, yMain) }));
      residG.appendChild(el("path", { class: "resid-line", d: buildPath(data.resid, yResid) }));

      // residual outlier dots
      var w = data.wavelengths, rd = data.resid;
      var rng = viewIndexRange(view.min, view.max);
      for (var i = rng.i0; i <= rng.i1; i++) {
        if (rd[i] != null && isFinite(rd[i]) &&
            Math.abs(rd[i]) > residMax * 0.55) {
          residG.appendChild(el("circle", {
            cx: xScale(w[i]), cy: yResid(rd[i]), r: 1.6,
            fill: rd[i] > 0 ? "var(--accent)" : "var(--ink)", opacity: 0.7,
          }));
        }
      }
      parts.push(mainG);
      parts.push(residG);
    }

    // axes
    parts.push(renderAxes(tk, fluxTicks, residTicks, stk));

    // commit
    svgEl.textContent = "";
    parts.forEach(function (n) { svgEl.appendChild(n); });

    // lightweight top layer: crosshair, hover outline, draw preview.
    // Rebuilt by updateDynamic() on pointermove without a full re-render.
    dynamicLayer = el("g", {
      class: "spectrum-dynamic",
      "pointer-events": "none",
      "clip-path": "url(#we-clip-plot)",
    });
    svgEl.appendChild(dynamicLayer);
    updateDynamic();
  }

  // ── Lightweight hover layer (no full rebuild on pointermove) ────────────
  function updateDynamic() {
    if (!svgEl || !dynamicLayer || !data || !view) return;
    updateSvgClass();
    dynamicLayer.textContent = "";

    // draw-in-progress preview
    if (interaction && interaction.kind === "draw" && interaction.preview) {
      var p = interaction.preview;
      var dx1 = xScale(Math.min(p.x0, p.x1)), dx2 = xScale(Math.max(p.x0, p.x1));
      dynamicLayer.appendChild(el("rect", {
        x: dx1, y: MAIN.top, width: Math.max(1, dx2 - dx1),
        height: fullBottom - MAIN.top, fill: "rgba(179,85,59,0.18)",
        stroke: "var(--accent)", "stroke-width": 1.5, "stroke-dasharray": "4 3",
      }));
    }

    // hovered-region outline (selected region keeps its glow in renderRegions)
    if (hoveredIdx != null && hoveredIdx !== selectedIdx) {
      var r = effRegion(hoveredIdx);
      if (r && !(r.upper < view.min || r.lower > view.max)) {
        var hx1 = xScale(r.lower), hx2 = xScale(r.upper);
        var c2 = regionChi2(hoveredIdx);
        var stroke = r.excluded
          ? "rgba(156,61,46,0.5)" : Q_COLOR[qualityTier(c2)];
        dynamicLayer.appendChild(el("rect", {
          x: hx1 - 1, y: MAIN.top, width: hx2 - hx1 + 2,
          height: fullBottom - MAIN.top, fill: "none", stroke: stroke,
          "stroke-width": 1.5, opacity: 0.6,
        }));
      }
    }

    // cursor crosshair
    if (cursorPx != null && cursorPx > PAD.left && cursorPx < PAD.left + innerW) {
      dynamicLayer.appendChild(el("line", {
        x1: cursorPx, x2: cursorPx, y1: MAIN.top, y2: fullBottom,
        stroke: "var(--ink)", "stroke-width": 0.6, "stroke-dasharray": "2 3",
        opacity: 0.35,
      }));
    }
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
      if (!(data && data.stacked)) {
        // resid-panel band — in stacked mode the main panel covers this
        // area, so the extra rect would double-shade the lower traces.
        rg.appendChild(el("rect", {
          x: x1, y: RESID.top, width: bw, height: RESID.h, fill: fill,
          opacity: 0.7, "data-region": i, style: "cursor:pointer",
        }));
      }
      // region rail (bottom of main) — neutral; line-list species is unreliable
      rg.appendChild(el("rect", {
        x: x1, y: MAIN.top + MAIN.h - 3, width: bw, height: 3,
        fill: "var(--muted)", opacity: r.excluded ? 0.3 : 0.9,
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
      // selection glow (the hover outline lives in the dynamic layer)
      if (isSel) {
        rg.appendChild(el("rect", {
          x: x1 - 2, y: MAIN.top - 2, width: x2 - x1 + 4,
          height: fullBottom - MAIN.top + 4, rx: 3, fill: "none",
          stroke: "var(--accent)", "stroke-width": 2, opacity: 0.85,
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
      // (line-list species label intentionally omitted — identifications unreliable)
      g.appendChild(rg);
    }
    return g;
  }

  function renderVald() {
    var g = el("g", { class: "vald-overlay", "pointer-events": "none" });
    if (!valdVisible || !vald || !vald.wavelengths) return g;
    var w = vald.wavelengths;
    var labelStepPx = 36;
    var lastLabelPx = -Infinity;
    var topY = MAIN.top + 4;
    var botY = MAIN.top + MAIN.h;
    for (var i = lowerBound(w, view.min); i < w.length; i++) {
      var lam = w[i];
      if (lam > view.max) break;
      if (vald.depths[i] < valdDepthMin) continue;
      var x = xScale(lam);
      var col = elementColor(vald.elements[i]);
      var opacity = Math.min(1, 0.35 + 0.65 * vald.depths[i]);
      g.appendChild(el("line", {
        class: "vald-line",
        x1: x, x2: x, y1: topY, y2: botY,
        stroke: col, "stroke-width": 1, "stroke-dasharray": "3 3",
        opacity: opacity,
      }));
      if (x - lastLabelPx >= labelStepPx) {
        g.appendChild(el("text", {
          class: "vald-label", x: x + 2, y: topY + 9,
          fill: col, opacity: opacity,
        }, vald.elements[i] + " " + romanize(vald.ions[i])));
        lastLabelPx = x;
      }
    }
    return g;
  }

  function renderAxes(tk, fluxTicks, residTicks, stk) {
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
    }, stk ? "normalized flux + offset" : "normalized flux"));
    // resid y-axis
    if (!stk) {
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
    }
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
      x1: 66, x2: 84, y1: 13, y2: 13,
      stroke: stk ? "hsl(110, 58%, 42%)" : "var(--accent)", "stroke-width": 1.6,
    }));
    lg.appendChild(el("text", {
      class: "spectrum-axis-label", x: 88, y: 16,
    }, stk ? "fit (Teff color)" : "fit"));
    if (!stk) {
      lg.appendChild(el("line", {
        x1: 118, x2: 136, y1: 13, y2: 13, stroke: "var(--ink-3)",
        "stroke-width": 1.2, "stroke-dasharray": "3 2",
      }));
      lg.appendChild(el("text", {
        class: "spectrum-axis-label", x: 140, y: 16,
      }, "resid"));
    }
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

  // Hover-only updates: refresh just the dynamic layer. A pending full
  // render supersedes this (render() ends with updateDynamic()).
  function scheduleDynamic() {
    if (rafPending || rafDynPending) return;
    rafDynPending = true;
    window.requestAnimationFrame(function () {
      rafDynPending = false;
      if (!rafPending) updateDynamic();
    });
  }

  // ── Pointer interaction ──────────────────────────────────────────────────
  // getBoundingClientRect is layout-forcing — cache it for the current
  // animation frame instead of reading it up to 3× per pointermove.
  function svgRect() {
    if (!rectCache) {
      rectCache = svgEl.getBoundingClientRect();
      window.requestAnimationFrame(function () { rectCache = null; });
    }
    return rectCache;
  }

  function svgCoords(e) {
    var rect = svgRect();
    var px = ((e.clientX - rect.left) / rect.width) * PLOT_W;
    var py = ((e.clientY - rect.top) / rect.height) * PLOT_H;
    return { px: px, py: py, lambda: xInvert(px),
             clientX: e.clientX, clientY: e.clientY };
  }

  function bindPointer() {
    svgEl.addEventListener("pointerdown", onDown);
    svgEl.addEventListener("pointermove", onMove);
    svgEl.addEventListener("pointerup", onUp);
    svgEl.addEventListener("pointercancel", onCancel);
    svgEl.addEventListener("pointerleave", onLeave);
    svgEl.addEventListener("wheel", onWheel, { passive: false });
    svgEl.addEventListener("dblclick", onDblClick);
  }

  function onDown(e) {
    if (e.button !== 0) return;
    // A second pointer must not clobber an active gesture.
    if (interaction && interaction.pointerId !== e.pointerId) return;
    var p = svgCoords(e);
    try { svgEl.setPointerCapture(e.pointerId); } catch (_) {}

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
    var it = interaction;
    // Ignore pointers that don't own the active gesture (multi-touch).
    if (it && e.pointerId !== it.pointerId) return;
    var p = svgCoords(e);
    if (!isFinite(p.lambda)) return; // zero-size svg → coords are NaN
    cursorPx = p.px;

    if (it && it.kind === "edge") {
      var lo = it.originalLo, hi = it.originalHi;
      if (it.edge === "lo") lo = Math.min(p.lambda, hi - MIN_REGION_W);
      else hi = Math.max(p.lambda, lo + MIN_REGION_W);
      stageEdgePreview(it.regionIdx, lo, hi);
      scheduleRender(); // band geometry changes → full render (view-culled)
      return;
    }
    if (it && it.kind === "draw") {
      it.preview = { x0: it.startLambda, x1: p.lambda };
      scheduleDynamic();
      return;
    }
    if (it && it.kind === "pan") {
      var dxPx = e.clientX - it.startClientX;
      var dxSvg = (dxPx / svgRect().width) * PLOT_W;
      if (!it.activated) {
        if (Math.abs(dxSvg) < DRAG_THRESHOLD) return;
        it.activated = true;
      }
      var span = it.viewMax - it.viewMin;
      var dLambda = -(dxSvg / innerW) * span;
      view = clampView(it.viewMin + dLambda, it.viewMax + dLambda);
      emitViewChange();
      scheduleRender();
      return;
    }

    // hover — only the lightweight dynamic layer + tooltip update; a full
    // rebuild is needed solely when the stacked-star emphasis changes.
    var starChanged = false;
    if (data && data.stacked) {
      var ns = nearestStar(p.lambda, p.py);
      starChanged = ns !== hoveredStar;
      hoveredStar = ns;
    }
    hoveredIdx = hitRegion(p.lambda);
    updateTooltip(p);
    if (starChanged) scheduleRender();
    else scheduleDynamic();
  }

  function onUp(e) {
    var it = interaction;
    if (it && e.pointerId !== it.pointerId) return; // stray pointer
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
      // clamp to the data domain — the pointer can be released off-plot
      lo = Math.max(lo, data.lambdaMin);
      hi = Math.min(hi, data.lambdaMax);
      interaction = null;
      if (isFinite(lo) && isFinite(hi) && hi - lo > 0.01) {
        openDrawPopover(lo, hi, e.clientX, e.clientY);
        scheduleDynamic(); // clear the preview rect
      } else {
        scheduleRender();
      }
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
    if (interaction && e.pointerId !== interaction.pointerId) return;
    try { svgEl.releasePointerCapture(e.pointerId); } catch (_) {}
    interaction = null;
    scheduleRender();
  }

  function onLeave() {
    if (interaction) return;
    cursorPx = null;
    hoveredIdx = null;
    var starChanged = hoveredStar != null;
    hoveredStar = null;
    hideTooltip();
    if (starChanged) scheduleRender();
    else scheduleDynamic();
  }

  // Toolbar promise: "double-click resets" → back to the full λ-range.
  function onDblClick(e) {
    if (!data || !view) return;
    e.preventDefault();
    interaction = null;
    view = clampView(data.lambdaMin, data.lambdaMax);
    emitViewChange();
    scheduleRender();
  }

  function onWheel(e) {
    if (e.deltaY === 0) return; // horizontal/idle wheel — not a zoom gesture
    e.preventDefault();
    var p = svgCoords(e);
    if (!isFinite(p.lambda)) return;
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

  function nearestStar(lambda, py) {
    if (!data || !data.stars || !data.stars.length) return null;
    var idx = nearestIndex(lambda), best = null, bestD = Infinity;
    for (var k = 0; k < data.stars.length; k++) {
      var s = data.stars[k];
      var v = s.flux[idx];
      var base = (v != null && isFinite(v)) ? v : 1.0;
      var d = Math.abs(yMain(base + s.offset) - py);
      if (d < bestD) { bestD = d; best = k; }
    }
    return best;
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
  var tipRafPending = false;
  var tipPoint = null;
  var lastTipHTML = "";

  // Format a possibly-null/NaN sample; gaps render as an en-dash.
  function fmtNum(v, digits, signed) {
    if (v == null || !isFinite(v)) return "–";
    var s = v.toFixed(digits);
    return signed && v >= 0 ? "+" + s : s;
  }

  // rAF-batched (latest-wins): raw pointermove can fire faster than the
  // display refresh, and innerHTML is only rewritten when content changed.
  function updateTooltip(p) {
    tipPoint = p;
    if (tipRafPending) return;
    tipRafPending = true;
    window.requestAnimationFrame(function () {
      tipRafPending = false;
      renderTooltip();
    });
  }

  function commitTooltip(tip, html, p) {
    if (html !== lastTipHTML) {
      tip.innerHTML = html;
      lastTipHTML = html;
    }
    tip.style.display = "block";
    tip.style.left = (p.clientX + 16) + "px";
    tip.style.top = (p.clientY + 16) + "px";
  }

  function renderTooltip() {
    var p = tipPoint;
    var tip = document.getElementById("cursor-tooltip");
    if (!tip || !data || !p) return;
    var cl = p.lambda;

    if (data.stacked) {
      var sIdx = hoveredStar != null ? hoveredStar : 0;
      var s = data.stars[sIdx];
      var di = nearestIndex(cl);
      var ov = s.flux[di], fv = s.fitFlux[di];
      var html =
        '<div class="tt-title"><span>' + s.slug + "</span><span>" +
        Math.round(s.teff) + " K</span></div>" +
        ttRow("cursor λ", fmtNum(cl, 3)) +
        ttRow("obs flux", fmtNum(ov, 4)) +
        ttRow("fit", fmtNum(fv, 4));

      if (hoveredIdx != null) {
        var r = effRegion(hoveredIdx), c2 = regionChi2(hoveredIdx);
        html += '<div class="tt-sep"></div>' +
          '<div class="tt-title"><span>Region #' + (hoveredIdx + 1) +
          '</span><span class="q-badge q-' + qualityTier(c2) + '">' +
          qualityLabel(c2) + "</span></div>" +
          ttRow("range", r.lower.toFixed(3) + " – " + r.upper.toFixed(3)) +
          ttRow("med χ²/N", c2 != null && isFinite(c2) ? c2.toFixed(3) : "—");
        var reg = data.regions && data.regions[hoveredIdx];
        if (reg && reg.perStar) {
          html += '<div class="tt-sep"></div>' +
            '<div class="tt-row"><span>star</span><span>χ²/N</span></div>';
          // hottest first → rows mirror the visual stacking (coolest at bottom)
          for (var k = data.stars.length - 1; k >= 0; k--) {
            var st = data.stars[k], ps = reg.perStar[k];
            var used = ps && ps.npix > 0;
            var cls = (used ? "" : " dim") + (k === sIdx ? " hl" : "");
            html += '<div class="tt-row' + cls + '"><span>' +
              (used ? "✓ " : "✗ ") + st.slug + "</span><span>" +
              (used && ps.chi2 != null ? ps.chi2.toFixed(2) : "—") +
              "</span></div>";
          }
        }
      }

      var vh = "";
      var nearS = nearbyVald(cl, 0.08, 4);
      if (nearS.length) {
        vh = '<div class="tt-sep"></div>' +
          '<div class="tt-row"><span>VALD nearby</span><span></span></div>';
        for (var q = 0; q < nearS.length; q++) {
          var nq = nearS[q].idx;
          vh += ttRow(
            vald.elements[nq] + " " + romanize(vald.ions[nq]) +
              " @ " + vald.wavelengths[nq].toFixed(3),
            "d=" + vald.depths[nq].toFixed(2)
          );
        }
      }
      commitTooltip(tip, html + vh, p);
      return;
    }

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
    var valdHtml = "";
    var near = nearbyVald(cl, 0.08, 4);
    if (near.length) {
      valdHtml = '<div class="tt-sep"></div>'
        + '<div class="tt-row"><span>VALD nearby</span><span></span></div>';
      for (var k = 0; k < near.length; k++) {
        var ni = near[k].idx;
        var lab = vald.elements[ni] + " " + romanize(vald.ions[ni]);
        var lamS = vald.wavelengths[ni].toFixed(3);
        var dpS = vald.depths[ni].toFixed(2);
        valdHtml += ttRow(lab + " @ " + lamS, "d=" + dpS);
      }
    }
    var html = head +
      ttRow("cursor λ", fmtNum(cl, 3)) +
      ttRow("obs flux", fmtNum(sampleAt("flux", cl), 4)) +
      ttRow("fit", fmtNum(sampleAt("fitFlux", cl), 4)) +
      ttRow("resid", fmtNum(resid, 4, true)) +
      valdHtml;
    commitTooltip(tip, html, p);
  }
  function ttRow(k, v) {
    return '<div class="tt-row"><span>' + k + "</span><span>" + v +
      "</span></div>";
  }
  function hideTooltip() {
    tipPoint = null;
    lastTipHTML = "";
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
  // Content fingerprint of a spectrum payload — object identity is not
  // reliable across Dash callback invocations (a fresh-but-equal reference
  // must NOT reset the user's zoom; a genuinely new payload must rescale).
  function payloadFp(d) {
    var fp = d.lambdaMin + "|" + d.lambdaMax + "|" +
      (d.wavelengths ? d.wavelengths.length : 0) +
      (d.fullRange ? "|F" : "") + (d.stacked ? "|S" : "");
    if (d.stacked && d.stars) {
      fp += "|" + d.stars.map(function (s) { return s.slug; }).join(",");
    } else if (d.flux && d.flux.length) {
      fp += "|" + d.flux[0] + "|" + d.flux[d.flux.length >> 1];
    }
    return fp;
  }

  function sync(specData, entries, pending, selected, drawActive, goto,
                valdPayload, visible, depthMin) {
    var firstData = false;
    var newData = false;
    if (specData && specData.wavelengths) {
      if (!data) firstData = true;
      var fp = payloadFp(specData);
      if (fp !== lastPayloadFp) { newData = true; lastPayloadFp = fp; }
      data = specData;
    }
    if (!data) return;
    if (newData) {
      // Re-fit the flux/residual y-scales whenever a new payload arrives
      // (e.g. switching to a single star's full-range spectrum).
      MAIN.h = data.stacked ? MAIN_H_STACKED : MAIN_H_NORMAL;
      var fmin = Infinity, fmax = -Infinity, rmax = 0;
      if (data.stacked) {
        data.stars.forEach(function (s) {
          for (var i = 0; i < s.flux.length; i++) {
            var o = s.flux[i], f = s.fitFlux[i];
            if (o != null && isFinite(o)) {
              fmin = Math.min(fmin, o + s.offset);
              fmax = Math.max(fmax, o + s.offset);
            }
            if (f != null && isFinite(f)) {
              fmin = Math.min(fmin, f + s.offset);
              fmax = Math.max(fmax, f + s.offset);
            }
          }
        });
      } else {
        // Skip null/NaN samples (payload gaps) — Math.min/max would
        // poison the scale with NaN (and coerce null to 0).
        for (var i = 0; i < data.flux.length; i++) {
          var o2 = data.flux[i], f2 = data.fitFlux[i], r2 = data.resid[i];
          if (o2 != null && isFinite(o2)) {
            if (o2 < fmin) fmin = o2;
            if (o2 > fmax) fmax = o2;
          }
          if (f2 != null && isFinite(f2)) {
            if (f2 < fmin) fmin = f2;
            if (f2 > fmax) fmax = f2;
          }
          if (r2 != null && isFinite(r2)) {
            var a2 = Math.abs(r2);
            if (a2 > rmax) rmax = a2;
          }
        }
      }
      if (!isFinite(fmin) || !isFinite(fmax)) { fmin = 0; fmax = 1; }
      var fpad = 0.04 * (fmax - fmin || 1);
      fluxRange = { min: fmin - fpad, max: fmax + fpad };
      residMax = Math.max(0.01, rmax * 1.15);
      // On first load, or when a single-star full-range payload arrives, reset
      // the x-domain to the payload bounds so the whole range is reachable. The
      // windowed mean view (no fullRange flag, not first load) keeps its view.
      if (!firstData && !data.fullRange && view) {
        // Keep the current window but re-clamp to the new payload bounds.
        view = clampView(view.min, view.max);
      } else {
        view = clampView(data.lambdaMin, data.lambdaMax);
      }
    }
    // Don't wipe the state a live gesture is previewing: the edge-drag
    // stages pendingChanges each frame and relies on selectedIdx/llEntries
    // staying put until the commit lands in the stores on pointer-up.
    var editing = interaction &&
      (interaction.kind === "edge" || interaction.kind === "draw");
    if (entries != null && !editing) llEntries = entries;
    if (pending != null && !editing) pendingChanges = pending || {};
    if (!editing) {
      selectedIdx = selected && selected.region_idx != null
        ? selected.region_idx : null;
    }
    drawMode = !!drawActive;
    if (valdPayload != null) vald = valdPayload;
    if (visible != null) valdVisible = !!visible;
    if (depthMin != null && isFinite(+depthMin)) valdDepthMin = +depthMin;
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
  var initAttempts = 0;
  function init() {
    if (!host()) {
      if (++initAttempts > 100) {
        console.warn(
          "wave-explorer spectrum: #spectrum-graph never appeared; giving up");
        return;
      }
      setTimeout(init, 100);
      return;
    }
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
