// tests/demo_compute.test.mjs
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import {
  customRegionChi2, residualMetrics,
} from "../site/demo/compute.mjs";

const meta = JSON.parse(readFileSync(new URL("../site/payload/meta.json", import.meta.url)));
const exp = JSON.parse(readFileSync(new URL("./fixtures/compute_expected.json", import.meta.url)));
const close = (a, b, eps = 1e-6) => {
  const aMissing = a == null || Number.isNaN(a);
  const bMissing = b == null || Number.isNaN(b);
  if (aMissing || bMissing) return aMissing && bMissing;
  return Math.abs(a - b) <= eps * (1 + Math.abs(b));
};

test("customRegionChi2 matches Python for every region window", () => {
  for (const w of exp.windows) {
    const got = customRegionChi2(meta.fitpix, w.lo, w.hi);
    assert.ok(close(got.median_chi2, w.chi2.median_chi2), `median @${w.lo}`);
    assert.ok(close(got.p16_chi2, w.chi2.p16_chi2), `p16 @${w.lo}`);
    assert.ok(close(got.p84_chi2, w.chi2.p84_chi2), `p84 @${w.lo}`);
    assert.equal(got.n_stars, w.chi2.n_stars, `n_stars @${w.lo}`);
    assert.equal(got.med_npix, w.chi2.med_npix, `med_npix @${w.lo}`);
  }
});

test("residualMetrics matches Python for every region window", () => {
  for (const w of exp.windows) {
    const got = residualMetrics(meta.common_w, meta.mean_resid, meta.std_resid, w.lo, w.hi);
    for (const k of ["mean_resid", "mean_abs_resid", "p95_abs_resid", "mean_norm_resid"]) {
      assert.ok(close(got[k], w.resid[k]), `${k} @${w.lo}`);
    }
    assert.equal(got.n_grid, w.resid.n_grid, `n_grid @${w.lo}`);
  }
});
