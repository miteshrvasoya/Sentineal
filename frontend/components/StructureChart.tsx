"use client";
import { ColorType, CrosshairMode, LineStyle, createChart, type SeriesMarker, type Time } from "lightweight-charts";
import { useEffect, useRef } from "react";
import type { Bar, Patterns, Structure } from "@/lib/api";
import { BoxesPrimitive, ProfilePrimitive, type Box } from "@/lib/primitives";
import { toTime } from "@/lib/time";

export const LAYERS = [
  { id: "swings", label: "Swings (HH/HL/LH/LL)" }, { id: "events", label: "BOS / CHoCH" }, { id: "sweeps", label: "Liquidity sweeps" },
  { id: "fvg", label: "Fair value gaps" }, { id: "ob", label: "Order blocks" }, { id: "sr", label: "Support/resistance" },
  { id: "range", label: "Premium / discount" }, { id: "fib", label: "Fibonacci" }, { id: "pivots", label: "Pivots" },
  { id: "profile", label: "Volume profile" }, { id: "patterns", label: "Candle patterns" },
] as const;
export const DEFAULT_LAYERS = ["swings", "events", "fvg", "ob", "sr", "profile"];

type Props = { bars: Bar[]; interval: string; s: Structure; patterns?: Patterns; layers: string[]; dark: boolean };

export default function StructureChart({ bars, interval, s, patterns, layers, dark }: Props) {
  const el = useRef<HTMLDivElement>(null);
  const key = layers.join(",");

  useEffect(() => {
    if (!el.current || bars.length === 0) return;
    const on = (id: string) => layers.includes(id);
    const daily = interval === "1d";
    const tm = (t: number) => toTime(t, daily);
    const grid = dark ? "#1e293b" : "#e2e8f0";
    const chart = createChart(el.current, {
      autoSize: true, height: 620,
      layout: { background: { type: ColorType.Solid, color: "transparent" }, textColor: dark ? "#cbd5e1" : "#334155" },
      grid: { vertLines: { color: grid }, horzLines: { color: grid } },
      crosshair: { mode: CrosshairMode.Normal },
      timeScale: { timeVisible: !daily, secondsVisible: false, borderColor: grid },
      rightPriceScale: { borderColor: grid, minimumWidth: 70 },
    });
    const candles = chart.addCandlestickSeries({
      upColor: "#16a34a", downColor: "#dc2626", wickUpColor: "#16a34a", wickDownColor: "#dc2626", borderVisible: false,
    });
    candles.setData(bars.map((b) => ({ time: tm(b.t), open: b.o, high: b.h, low: b.l, close: b.c })));
    const known = new Set(bars.map((b) => b.t));
    const first = tm(bars[0].t);
    const line = (price: number, color: string, title: string, dash = LineStyle.Dashed) =>
      candles.createPriceLine({ price, color, lineWidth: 1, lineStyle: dash, axisLabelVisible: true, title });

    const boxes: Box[] = [];
    const markers: SeriesMarker<Time>[] = [];

    if (on("swings"))
      for (const w of s.swings) {
        if (!w.label || !known.has(w.t)) continue;
        const hi = w.kind === "high";
        markers.push({ time: tm(w.t), position: hi ? "aboveBar" : "belowBar", shape: hi ? "arrowDown" : "arrowUp",
          color: w.label.startsWith("H") && hi ? "#16a34a" : w.label === "HL" ? "#16a34a" : "#dc2626", text: w.label });
      }
    for (const e of s.events) {
        const sweep0 = e.kind.startsWith("sweep");
        if (sweep0 ? !on("sweeps") : !on("events")) continue;
        if (!known.has(e.i_t)) continue;
        const bull = e.dir === "bull", sweep = e.kind.startsWith("sweep");
        markers.push({ time: tm(e.i_t), position: bull ? "belowBar" : "aboveBar", shape: sweep ? "circle" : bull ? "arrowUp" : "arrowDown",
          color: sweep ? "#f59e0b" : e.kind === "CHoCH" ? "#a855f7" : bull ? "#0ea5e9" : "#f43f5e",
          text: sweep ? "sweep" : e.kind });
    }
    if (on("patterns") && patterns)
      for (const r of patterns.recent) {
        if (!known.has(r.t)) continue;
        markers.push({ time: tm(r.t), position: r.direction === "bear" ? "aboveBar" : "belowBar", shape: "square",
          color: "#64748b", text: r.pattern.replace(/_/g, " ") });
      }
    markers.sort((a, b) => (a.time as number | string) > (b.time as number | string) ? 1 : (a.time as number | string) < (b.time as number | string) ? -1 : 0);
    candles.setMarkers(markers);

    if (on("fvg"))
      for (const g of s.fvg.filter((g) => g.resolved_t === null).slice(-8))
        boxes.push({ t1: tm(g.i_t), t2: null, low: g.low, high: g.high, label: "FVG",
          fill: g.dir === "bull" ? "#22c55e33" : "#ef444433", stroke: g.dir === "bull" ? "#16a34a" : "#dc2626" });
    if (on("ob"))
      for (const o of s.order_blocks.filter((o) => o.resolved_t === null).slice(-8))
        boxes.push({ t1: tm(o.i_t), t2: null, low: o.low, high: o.high, label: `OB (${o.event})`,
          fill: o.dir === "bull" ? "#3b82f633" : "#f9731633", stroke: o.dir === "bull" ? "#2563eb" : "#ea580c" });
    if (on("sr"))
      for (const z of s.sr_zones)
        boxes.push({ t1: first, t2: null, low: z.low, high: z.high, label: `${z.type} x${z.touches}`,
          fill: z.type === "support" ? "#16a34a22" : z.type === "resistance" ? "#dc262622" : "#94a3b822",
          stroke: z.type === "support" ? "#16a34a" : z.type === "resistance" ? "#dc2626" : "#94a3b8" });
    if (on("range") && s.dealing_range) {
      const d = s.dealing_range, t1 = tm(bars[Math.max(0, bars.length - 100)].t);
      boxes.push({ t1, t2: null, low: d.equilibrium, high: d.high, fill: "#ef444414", label: "premium" });
      boxes.push({ t1, t2: null, low: d.low, high: d.equilibrium, fill: "#22c55e14", label: "discount" });
      line(d.equilibrium, "#64748b", "EQ");
    }
    if (on("fib") && s.fibonacci) {
      for (const [r, v] of Object.entries(s.fibonacci.retracements)) line(v, "#d946ef", `fib ${r}`);
      for (const [r, v] of Object.entries(s.fibonacci.extensions)) line(v, "#a21caf", `ext ${r}`, LineStyle.Dotted);
    }
    if (on("pivots")) {
      const d = s.pivots.daily?.classic;
      if (d) for (const [k, v] of Object.entries(d)) line(v, k === "P" ? "#eab308" : k.startsWith("R") ? "#f87171" : "#4ade80", k, LineStyle.Dotted);
    }
    if (boxes.length) candles.attachPrimitive(new BoxesPrimitive(boxes));
    if (on("profile") && s.volume_profile) {
      const v = s.volume_profile;
      candles.attachPrimitive(new ProfilePrimitive({ bins: v.bins, poc: v.poc, vah: v.vah, val: v.val }));
      line(v.poc, "#f59e0b", "POC", LineStyle.Solid);
      line(v.vah, "#6366f1", "VAH"); line(v.val, "#6366f1", "VAL");
    }
    chart.timeScale().fitContent();
    return () => chart.remove();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [bars, interval, s, patterns, key, dark]);

  return <div ref={el} className="h-[620px] w-full rounded border border-slate-200 dark:border-slate-800" data-testid="structure-chart" />;
}
