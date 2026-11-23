// Declarative catalogue of chart overlays (price pane) and sub-panes. `sets` = backend indicator sets needed.
export type Line = { key: string; color: string; dashed?: boolean; splitDir?: string };
export type Overlay = { id: string; label: string; sets: string[]; lines: Line[] };
export type Pane = {
  id: string; label: string; sets: string[];
  lines: { key: string; color: string; hist?: boolean }[]; levels?: number[];
};

export const OVERLAYS: Overlay[] = [
  { id: "ema", label: "EMA 20/50/200", sets: ["trend"], lines: [
    { key: "ema_20", color: "#f59e0b" }, { key: "ema_50", color: "#3b82f6" }, { key: "ema_200", color: "#a855f7" }] },
  { id: "sma", label: "SMA 20/50", sets: ["trend"], lines: [{ key: "sma_20", color: "#f97316" }, { key: "sma_50", color: "#06b6d4" }] },
  { id: "bb", label: "Bollinger", sets: ["volatility"], lines: [
    { key: "bb_upper", color: "#64748b" }, { key: "bb_mid", color: "#64748b", dashed: true }, { key: "bb_lower", color: "#64748b" }] },
  { id: "supertrend", label: "Supertrend", sets: ["trend"], lines: [
    { key: "supertrend", color: "#16a34a", splitDir: "supertrend_dir" }] },
  { id: "ichimoku", label: "Ichimoku", sets: ["trend"], lines: [
    { key: "ichi_tenkan", color: "#ef4444" }, { key: "ichi_kijun", color: "#2563eb" },
    { key: "ichi_span_a", color: "#22c55e88" }, { key: "ichi_span_b", color: "#ef444488" }] },
  { id: "donchian", label: "Donchian 20", sets: ["trend"], lines: [
    { key: "donchian_upper", color: "#0ea5e9" }, { key: "donchian_lower", color: "#0ea5e9" }] },
  { id: "keltner", label: "Keltner", sets: ["volatility"], lines: [
    { key: "kc_upper", color: "#d946ef", dashed: true }, { key: "kc_lower", color: "#d946ef", dashed: true }] },
  { id: "vwap", label: "VWAP", sets: ["volume"], lines: [
    { key: "vwap_20", color: "#eab308" }, { key: "vwap_session", color: "#eab308" }] },
];

export const PANES: Pane[] = [
  { id: "rsi", label: "RSI", sets: ["momentum"], lines: [{ key: "rsi", color: "#8b5cf6" }], levels: [30, 70] },
  { id: "macd", label: "MACD", sets: ["trend"], lines: [
    { key: "macd_hist", color: "#94a3b8", hist: true }, { key: "macd", color: "#2563eb" }, { key: "macd_signal", color: "#f97316" }] },
  { id: "adx", label: "ADX / DI", sets: ["trend"], lines: [
    { key: "adx", color: "#111827" }, { key: "plus_di", color: "#16a34a" }, { key: "minus_di", color: "#dc2626" }], levels: [25] },
  { id: "obv", label: "OBV", sets: ["volume"], lines: [{ key: "obv", color: "#0ea5e9" }] },
  { id: "cmf", label: "CMF", sets: ["volume"], lines: [{ key: "cmf", color: "#14b8a6", hist: true }], levels: [0] },
  { id: "mfi", label: "MFI", sets: ["volume"], lines: [{ key: "mfi", color: "#f59e0b" }], levels: [20, 80] },
  { id: "atr", label: "ATR %", sets: ["volatility"], lines: [{ key: "atr_pct", color: "#ec4899" }] },
  { id: "rv", label: "Realized vol", sets: ["volatility"], lines: [
    { key: "rv_cc", color: "#6366f1" }, { key: "rv_yz", color: "#f43f5e" }] },
];

export type Layout = { overlays: string[]; panes: string[] };
export const DEFAULT_LAYOUT: Layout = { overlays: ["ema"], panes: ["rsi"] };
