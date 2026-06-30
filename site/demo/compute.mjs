// site/demo/compute.mjs
// Ports of data_processing.py:433-491,532-565 — χ²/residual recompute in the browser.
const finite = (v) => v != null && Number.isFinite(+v);

export function percentile(sorted, q) {       // numpy 'linear' on ascending array
  const n = sorted.length;
  if (n === 0) return NaN;
  if (n === 1) return sorted[0];
  const rank = (q / 100) * (n - 1);
  const lo = Math.floor(rank), hi = Math.ceil(rank);
  if (lo === hi) return sorted[lo];
  return sorted[lo] + (sorted[hi] - sorted[lo]) * (rank - lo);
}
export function median(arr) {
  return percentile([...arr].sort((a, b) => a - b), 50);
}

export function regionChi2ForStar(star, lo, hi) {
  const { w, ff, fm, err } = star;
  let sum = 0, n = 0;
  for (let i = 0; i < w.length; i++) {
    if (w[i] >= lo && w[i] <= hi) {
      const z = (ff[i] - fm[i]) / err[i];
      sum += z * z; n++;
    }
  }
  return n ? { chi2: sum / n, n } : { chi2: NaN, n: 0 };
}

export function customRegionChi2(fitpix, lo, hi) {
  const per = [], npix = [];
  if (hi > lo) {
    for (const slug in fitpix) {
      const { chi2, n } = regionChi2ForStar(fitpix[slug], lo, hi);
      if (finite(chi2)) { per.push(chi2); npix.push(n); }
    }
  }
  if (!per.length) {
    return { median_chi2: NaN, p16_chi2: NaN, p84_chi2: NaN, n_stars: 0, med_npix: 0, per_star_chi2: [] };
  }
  const s = [...per].sort((a, b) => a - b);
  return {
    median_chi2: percentile(s, 50),
    p16_chi2: percentile(s, 16),
    p84_chi2: percentile(s, 84),
    n_stars: per.length,
    med_npix: Math.trunc(median(npix)),
    per_star_chi2: per,
  };
}

function nanmean(arr) {
  let s = 0, n = 0;
  for (const v of arr) if (finite(v)) { s += v; n++; }
  return n ? s / n : NaN;
}
function nanpercentile(arr, q) {
  const ok = arr.filter(finite).sort((a, b) => a - b);
  return ok.length ? percentile(ok, q) : NaN;
}

export function residualMetrics(commonW, meanResid, stdResid, lo, hi) {
  const rv = [], sv = [];
  for (let i = 0; i < commonW.length; i++) {
    if (commonW[i] >= lo && commonW[i] <= hi) { rv.push(meanResid[i]); sv.push(stdResid[i]); }
  }
  // keep grid points where mean_resid is finite (matches Python's `ok` mask)
  const r = [], s = [];
  for (let i = 0; i < rv.length; i++) if (finite(rv[i])) { r.push(rv[i]); s.push(sv[i]); }
  if (r.length < 2) {
    return { n_grid: 0, mean_resid: NaN, mean_abs_resid: NaN, p95_abs_resid: NaN, mean_norm_resid: NaN };
  }
  const absr = r.map(Math.abs);
  const norm = r.map((v, i) => (finite(s[i]) && s[i] > 0 ? Math.abs(v) / s[i] : NaN));
  return {
    n_grid: r.length,
    mean_resid: nanmean(r),
    mean_abs_resid: nanmean(absr),
    p95_abs_resid: nanpercentile(absr, 95),
    mean_norm_resid: nanmean(norm),
  };
}
