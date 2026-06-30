// site/demo/theme.mjs
export const C = {
  bg: "#f8f5ec", surf: "#fdfcf7", border2: "#e6dfcb",
  text: "#1a1814", muted: "#75705f", dim: "#9c9684",
  cyan: "#b3553b", amber: "#b88829", green: "#4f7a4d",
  red: "#9c3d2e", orange: "#c87338",
};
const GOOD = 5.0, FAIR = 15.0, BAD = 30.0;
const finite = (v) => v != null && Number.isFinite(+v);

export function chi2Color(v) {
  if (!finite(v)) return C.muted;
  if (v < GOOD) return C.green;
  if (v < FAIR) return C.amber;
  if (v < BAD) return C.orange;
  return C.red;
}
export function chi2Label(v) {
  if (!finite(v)) return "—";
  if (v < GOOD) return "GOOD";
  if (v < FAIR) return "FAIR";
  if (v < BAD) return "POOR";
  return "BAD";
}
export function chi2Tier(v) {
  if (!finite(v)) return "miss";
  if (v < GOOD) return "good";
  if (v < FAIR) return "fair";
  if (v < BAD) return "poor";
  return "bad";
}
export function chi2Pct(v) {
  if (!finite(v)) return 0;
  return Math.min(100, Math.trunc((v / BAD) * 100));
}
export function fmt(v, digits = 4, signed = false) {
  if (!finite(v)) return "—";
  const s = (+v).toFixed(digits);
  return signed && +v >= 0 ? "+" + s : s;
}
