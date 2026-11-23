"use client";
import { ColorType, CrosshairMode, createChart, type IChartApi, type Time, type UTCTimestamp } from "lightweight-charts";
import { useEffect, useRef, useState } from "react";
import type { Bar } from "@/lib/api";

const IST_OFFSET = 19800; // lightweight-charts renders UTC; shift so axes show IST.

function useIsDark() {
  const [dark, setDark] = useState(false);
  useEffect(() => {
    const read = () => setDark(document.documentElement.classList.contains("dark"));
    read();
    const mo = new MutationObserver(read);
    mo.observe(document.documentElement, { attributes: true, attributeFilter: ["class"] });
    return () => mo.disconnect();
  }, []);
  return dark;
}

export default function CandleChart({ bars, interval }: { bars: Bar[]; interval: string }) {
  const el = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const [tip, setTip] = useState<string>("");
  const dark = useIsDark();

  useEffect(() => {
    if (!el.current) return;
    const text = dark ? "#cbd5e1" : "#334155";
    const grid = dark ? "#1e293b" : "#e2e8f0";
    const chart = createChart(el.current, {
      height: 520,
      autoSize: true,
      layout: { background: { type: ColorType.Solid, color: "transparent" }, textColor: text },
      grid: { vertLines: { color: grid }, horzLines: { color: grid } },
      crosshair: { mode: CrosshairMode.Normal },
      timeScale: { timeVisible: interval !== "1d", secondsVisible: false, borderColor: grid },
      rightPriceScale: { borderColor: grid },
    });
    chartRef.current = chart;
    const candles = chart.addCandlestickSeries({
      upColor: "#16a34a", downColor: "#dc2626", wickUpColor: "#16a34a", wickDownColor: "#dc2626", borderVisible: false,
    });
    const vol = chart.addHistogramSeries({ priceFormat: { type: "volume" }, priceScaleId: "vol" });
    candles.priceScale().applyOptions({ scaleMargins: { top: 0.05, bottom: 0.25 } });
    chart.priceScale("vol").applyOptions({ scaleMargins: { top: 0.8, bottom: 0 } });

    const daily = interval === "1d";
    // Daily bars use an IST calendar-date string (business-day time); intraday uses shifted epoch seconds.
    const time = (t: number): Time =>
      daily ? (new Date((t + IST_OFFSET) * 1000).toISOString().slice(0, 10) as Time) : ((t + IST_OFFSET) as UTCTimestamp);
    // Daily bars are keyed by IST calendar date so there are no half-day offsets.
    const data = bars.map((b) => ({ time: time(b.t), open: b.o, high: b.h, low: b.l, close: b.c }));
    candles.setData(data);
    vol.setData(bars.map((b) => ({ time: time(b.t), value: b.v, color: b.c >= b.o ? "#16a34a66" : "#dc262666" })));
    chart.timeScale().fitContent();

    const byTime = new Map(bars.map((b) => [String(time(b.t)), b]));
    chart.subscribeCrosshairMove((p) => {
      const b = p.time ? byTime.get(String(p.time)) : undefined;
      setTip(b ? `O ${b.o.toFixed(2)}  H ${b.h.toFixed(2)}  L ${b.l.toFixed(2)}  C ${b.c.toFixed(2)}  Vol ${Math.round(b.v).toLocaleString("en-IN")}` : "");
    });
    return () => { chart.remove(); chartRef.current = null; };
  }, [bars, interval, dark]);

  return (
    <div className="relative rounded border border-slate-200 p-1 dark:border-slate-800">
      <div className="pointer-events-none absolute left-3 top-2 z-10 text-xs tabular-nums text-slate-600 dark:text-slate-300">{tip}</div>
      <div ref={el} className="h-[520px] w-full" data-testid="candle-chart" />
    </div>
  );
}
