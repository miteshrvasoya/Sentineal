// Number formatting for rupees and percentages, in the Indian style.

export const inr = (v: number | null | undefined, d = 0): string =>
  v === null || v === undefined || !Number.isFinite(v) ? "n/a" : `${v < 0 ? "-" : ""}₹${Math.abs(v).toLocaleString("en-IN", { minimumFractionDigits: d, maximumFractionDigits: d })}`;

/** ₹1.2 Cr, ₹3.4 L, ₹56,000: easier to read for big amounts. */
export function inrShort(v: number | null | undefined): string {
  if (v === null || v === undefined || !Number.isFinite(v)) return "n/a";
  const a = Math.abs(v), s = v < 0 ? "-" : "";
  if (a >= 1e7) return `${s}₹${(a / 1e7).toFixed(2)} Cr`;
  if (a >= 1e5) return `${s}₹${(a / 1e5).toFixed(2)} L`;
  return `${s}₹${Math.round(a).toLocaleString("en-IN")}`;
}

export const pctS = (v: number | null | undefined, d = 1): string =>
  v === null || v === undefined || !Number.isFinite(v) ? "n/a" : `${v >= 0 ? "+" : ""}${(v * 100).toFixed(d)}%`;

export const pct0 = (v: number | null | undefined, d = 0): string =>
  v === null || v === undefined || !Number.isFinite(v) ? "n/a" : `${(v * 100).toFixed(d)}%`;

export const tone = (v: number | null | undefined): string =>
  v === null || v === undefined || v === 0 ? "" : v > 0 ? "text-green-700 dark:text-green-400" : "text-red-600 dark:text-red-400";

export const today = (): string => new Date().toLocaleDateString("en-CA");   // YYYY-MM-DD in local time
