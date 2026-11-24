"use client";
import { ColorType, createChart, type SeriesMarker, type Time } from "lightweight-charts";
import { useEffect, useRef } from "react";
import type { Bar, SentDay } from "@/lib/api";
import { toTime } from "@/lib/time";

/** Price (line) with daily sentiment bars and the recency-weighted score on their own scale. */
export default function SentimentChart({ bars, daily, dark }: { bars: Bar[]; daily: SentDay[]; dark: boolean }) {
  const el = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!el.current || bars.length === 0) return;
    const grid = dark ? "#1e293b" : "#e2e8f0";
    const chart = createChart(el.current, {
      autoSize: true, height: 340,
      layout: { background: { type: ColorType.Solid, color: "transparent" }, textColor: dark ? "#cbd5e1" : "#334155" },
      grid: { vertLines: { color: grid }, horzLines: { color: grid } },
      timeScale: { borderColor: grid }, rightPriceScale: { borderColor: grid, minimumWidth: 70 },
      leftPriceScale: { visible: false },
    });
    const first = daily[0]?.date ?? "";
    const px = chart.addLineSeries({ color: "#6366f1", lineWidth: 2, priceLineVisible: false });
    px.setData(bars.map((b) => ({ time: toTime(b.t, true), value: b.c })).filter((p) => String(p.time) >= first));
    const hist = chart.addHistogramSeries({ priceScaleId: "left", lastValueVisible: false, priceLineVisible: false });
    chart.priceScale("left").applyOptions({ scaleMargins: { top: 0.65, bottom: 0 } });
    hist.setData(daily.filter((d) => d.mean_sent !== null).map((d) => ({
      time: d.date as Time, value: d.mean_sent as number, color: (d.mean_sent as number) >= 0 ? "#16a34aaa" : "#dc2626aa" })));
    const rw = chart.addLineSeries({ priceScaleId: "left", color: "#f59e0b", lineWidth: 1, priceLineVisible: false, lastValueVisible: false });
    rw.setData(daily.filter((d) => d.recency_weighted !== null).map((d) => ({ time: d.date as Time, value: d.recency_weighted as number })));
    const have = new Set(bars.map((b) => String(toTime(b.t, true))));
    const m: SeriesMarker<Time>[] = daily.filter((d) => d.volume_spike && have.has(d.date))
      .map((d) => ({ time: d.date as Time, position: "aboveBar", shape: "circle", color: "#f59e0b", text: `${d.n_articles} news` }));
    px.setMarkers(m);
    chart.timeScale().fitContent();
    return () => chart.remove();
  }, [bars, daily, dark]);
  return <div ref={el} className="h-[340px] w-full rounded border border-slate-200 dark:border-slate-800" data-testid="sentiment-chart" data-tour="sentiment-chart" />;
}
