"use client";
import {
  ColorType, CrosshairMode, LineStyle, createChart,
  type IChartApi, type ISeriesApi, type LineData, type Time, type UTCTimestamp,
} from "lightweight-charts";
import { useEffect, useMemo, useRef, useState } from "react";
import type { Bar, Indicators } from "@/lib/api";
import { OVERLAYS, PANES } from "@/lib/overlays";

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

type Props = { bars: Bar[]; interval: string; ind?: Indicators; overlayIds: string[]; paneIds: string[] };

export default function CandleChart({ bars, interval, ind, overlayIds, paneIds }: Props) {
  const mainEl = useRef<HTMLDivElement>(null);
  const paneEls = useRef<Record<string, HTMLDivElement | null>>({});
  const [tip, setTip] = useState("");
  const dark = useIsDark();
  const paneKey = paneIds.join(",");

  // Index indicator rows by bar time so series align with candles even if lengths differ.
  const idx = useMemo(() => {
    const m = new Map<number, number>();
    ind?.t.forEach((t, i) => m.set(t, i));
    return m;
  }, [ind]);

  useEffect(() => {
    if (!mainEl.current) return;
    const text = dark ? "#cbd5e1" : "#334155";
    const grid = dark ? "#1e293b" : "#e2e8f0";
    const daily = interval === "1d";
    const time = (t: number): Time =>
      daily ? (new Date((t + IST_OFFSET) * 1000).toISOString().slice(0, 10) as Time) : ((t + IST_OFFSET) as UTCTimestamp);
    const base = {
      autoSize: true,
      layout: { background: { type: ColorType.Solid, color: "transparent" }, textColor: text },
      grid: { vertLines: { color: grid }, horzLines: { color: grid } },
      crosshair: { mode: CrosshairMode.Normal },
      timeScale: { timeVisible: !daily, secondsVisible: false, borderColor: grid },
      rightPriceScale: { borderColor: grid, minimumWidth: 80 },
    } as const;

    const charts: IChartApi[] = [];
    const main = createChart(mainEl.current, { ...base, height: 460 });
    charts.push(main);
    const candles = main.addCandlestickSeries({
      upColor: "#16a34a", downColor: "#dc2626", wickUpColor: "#16a34a", wickDownColor: "#dc2626", borderVisible: false,
    });
    candles.priceScale().applyOptions({ scaleMargins: { top: 0.05, bottom: 0.25 } });
    candles.setData(bars.map((b) => ({ time: time(b.t), open: b.o, high: b.h, low: b.l, close: b.c })));
    const vol = main.addHistogramSeries({ priceFormat: { type: "volume" }, priceScaleId: "vol", lastValueVisible: false });
    main.priceScale("vol").applyOptions({ scaleMargins: { top: 0.8, bottom: 0 } });
    vol.setData(bars.map((b) => ({ time: time(b.t), value: b.v, color: b.c >= b.o ? "#16a34a66" : "#dc262666" })));

    // Overlays
    const tipSeries: { label: string; get: (t: number) => number | null }[] = [];
    const lineData = (key: string, keep?: (i: number) => boolean): LineData[] => {
      const arr = ind?.series[key];
      if (!arr) return [];
      const out: LineData[] = [];
      for (const b of bars) {
        const i = idx.get(b.t);
        const v = i === undefined ? null : arr[i];
        if (v !== null && v !== undefined && (!keep || keep(i!))) out.push({ time: time(b.t), value: v });
      }
      return out;
    };
    for (const o of OVERLAYS.filter((o) => overlayIds.includes(o.id))) {
      for (const l of o.lines) {
        const style = { lineWidth: 1 as const, lineStyle: l.dashed ? LineStyle.Dashed : LineStyle.Solid, lastValueVisible: false, priceLineVisible: false, crosshairMarkerVisible: false };
        if (l.splitDir) {
          const dir = ind?.series[l.splitDir];
          for (const [d, color] of [[1, "#16a34a"], [-1, "#dc2626"]] as const) {
            const s = main.addLineSeries({ ...style, color, lineWidth: 2 });
            s.setData(lineData(l.key, (i) => dir?.[i] === d));
          }
        } else {
          const s: ISeriesApi<"Line"> = main.addLineSeries({ ...style, color: l.color });
          s.setData(lineData(l.key));
          tipSeries.push({ label: l.key, get: (t) => { const i = idx.get(t); return i === undefined ? null : ind?.series[l.key]?.[i] ?? null; } });
        }
      }
    }

    // Sub-panes
    for (const p of PANES.filter((p) => paneIds.includes(p.id))) {
      const el = paneEls.current[p.id];
      if (!el) continue;
      const c = createChart(el, { ...base, height: 140, timeScale: { ...base.timeScale, visible: false } });
      charts.push(c);
      for (const l of p.lines) {
        const s = l.hist
          ? c.addHistogramSeries({ color: l.color + "99", lastValueVisible: false, priceLineVisible: false })
          : c.addLineSeries({ color: l.color, lineWidth: 1, priceLineVisible: false, lastValueVisible: true });
        s.setData(lineData(l.key));
        tipSeries.push({ label: l.key, get: (t) => { const i = idx.get(t); return i === undefined ? null : ind?.series[l.key]?.[i] ?? null; } });
        if (!l.hist && p.levels) for (const lv of p.levels) s.createPriceLine({ price: lv, color: grid, lineStyle: LineStyle.Dashed, lineWidth: 1, axisLabelVisible: false, title: "" });
      }
    }

    // Keep every chart on the same visible range.
    let syncing = false;
    for (const c of charts) {
      c.timeScale().subscribeVisibleLogicalRangeChange((r) => {
        if (!r || syncing) return;
        syncing = true;
        for (const o of charts) if (o !== c) o.timeScale().setVisibleLogicalRange(r);
        syncing = false;
      });
    }
    main.timeScale().fitContent();

    const byTime = new Map(bars.map((b) => [String(time(b.t)), b]));
    main.subscribeCrosshairMove((p) => {
      const b = p.time ? byTime.get(String(p.time)) : undefined;
      if (!b) return setTip("");
      const extra = tipSeries.map((s) => { const v = s.get(b.t); return v == null ? "" : `${s.label} ${v.toFixed(2)}`; }).filter(Boolean).join("  ");
      setTip(`O ${b.o.toFixed(2)}  H ${b.h.toFixed(2)}  L ${b.l.toFixed(2)}  C ${b.c.toFixed(2)}  Vol ${Math.round(b.v).toLocaleString("en-IN")}  ${extra}`);
    });
    return () => charts.forEach((c) => c.remove());
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [bars, interval, dark, ind, idx, overlayIds.join(","), paneKey]);

  return (
    <div className="rounded border border-slate-200 p-1 dark:border-slate-800">
      <div className="relative">
        <div className="pointer-events-none absolute left-3 top-2 z-10 max-w-[90%] text-xs tabular-nums text-slate-600 dark:text-slate-300">{tip}</div>
        <div ref={mainEl} className="h-[460px] w-full" data-testid="candle-chart" />
      </div>
      {PANES.filter((p) => paneIds.includes(p.id)).map((p) => (
        <div key={p.id} className="relative mt-1 border-t border-slate-200 dark:border-slate-800">
          <span className="pointer-events-none absolute left-2 top-1 z-10 text-xs font-medium text-slate-500">{p.label}</span>
          <div ref={(el) => { paneEls.current[p.id] = el; }} className="h-[140px] w-full" />
        </div>
      ))}
    </div>
  );
}
