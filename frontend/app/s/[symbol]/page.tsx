"use client";
import { useQuery } from "@tanstack/react-query";
import { useParams, useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";
import CandleChart from "@/components/CandleChart";
import ScorecardPanel from "@/components/ScorecardPanel";
import SymbolTabs from "@/components/SymbolTabs";
import { api } from "@/lib/api";
import { DEFAULT_LAYOUT, OVERLAYS, PANES, type Layout } from "@/lib/overlays";

const INTERVALS = ["1m", "5m", "15m", "1h", "1d"] as const;

function SymbolView() {
  const symbol = decodeURIComponent(String(useParams().symbol)).toUpperCase();
  const router = useRouter();
  const sp = useSearchParams();
  const interval = INTERVALS.includes(sp.get("i") as never) ? (sp.get("i") as string) : "1d";
  const adjusted = sp.get("adj") !== "0";

  const set = (k: string, v: string) => {
    const p = new URLSearchParams(sp.toString());
    p.set(k, v);
    router.replace(`?${p.toString()}`);
  };

  const prices = useQuery({ queryKey: ["prices", symbol, interval, adjusted], queryFn: () => api.prices(symbol, interval, adjusted) });
  const quote = useQuery({ queryKey: ["quote", symbol], queryFn: () => api.quote(symbol), refetchInterval: 60_000 });
  const q = quote.data;

  // Indicator layout: auto-restored from localStorage; "Save/Load" keeps one named slot.
  const [layout, setLayout] = useState<Layout>(DEFAULT_LAYOUT);
  useEffect(() => {
    try { const v = localStorage.getItem("ql-layout-current"); if (v) setLayout(JSON.parse(v)); } catch { /* ignore */ }
  }, []);
  const update = (l: Layout) => { setLayout(l); try { localStorage.setItem("ql-layout-current", JSON.stringify(l)); } catch { /* ignore */ } };
  const toggle = (k: keyof Layout, id: string) =>
    update({ ...layout, [k]: layout[k].includes(id) ? layout[k].filter((x) => x !== id) : [...layout[k], id] });
  const slot = (act: "save" | "load") => {
    try {
      if (act === "save") localStorage.setItem("ql-layout-saved", JSON.stringify(layout));
      else { const v = localStorage.getItem("ql-layout-saved"); if (v) update(JSON.parse(v)); }
    } catch { /* ignore */ }
  };
  const sets = Array.from(new Set([
    ...OVERLAYS.filter((o) => layout.overlays.includes(o.id)).flatMap((o) => o.sets),
    ...PANES.filter((p) => layout.panes.includes(p.id)).flatMap((p) => p.sets),
  ]));
  const nBars = prices.data?.bars.length ?? 0;
  const ind = useQuery({
    queryKey: ["ind", symbol, interval, adjusted, sets.join(","), nBars],
    queryFn: () => api.indicators(symbol, interval, adjusted, sets, nBars),
    enabled: sets.length > 0 && nBars > 0,
  });

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-baseline gap-4">
        <h1 className="text-2xl font-semibold">{symbol}</h1>
        {q && (
          <div className="flex items-baseline gap-2 tabular-nums">
            <span className="text-xl">{q.last.toFixed(2)}</span>
            <span className={q.change >= 0 ? "text-up" : "text-down"}>
              {q.change >= 0 ? "+" : ""}{q.change.toFixed(2)} ({q.change_pct.toFixed(2)}%)
            </span>
          </div>
        )}
        <div className="ml-auto flex items-center gap-1" data-tour="timeframes">
          {INTERVALS.map((i) => (
            <button key={i} onClick={() => set("i", i)}
              className={`rounded px-2 py-1 text-sm ${i === interval ? "bg-indigo-600 text-white" : "bg-slate-200 dark:bg-slate-800"}`}>{i}</button>
          ))}
          <label className="ml-3 flex items-center gap-1 text-sm" data-tour="adjusted">
            <input type="checkbox" checked={adjusted} onChange={(e) => set("adj", e.target.checked ? "1" : "0")} /> adjusted
          </label>
        </div>
      </div>

      <SymbolTabs />
      {prices.isLoading && <div className="skeleton h-[520px] w-full" />}
      {prices.error && (
        <div role="alert" className="rounded border border-red-400 bg-red-50 p-4 text-sm text-red-800 dark:bg-red-950 dark:text-red-200">
          <b>Could not load prices for {symbol}.</b> {(prices.error as Error).message}
        </div>
      )}
      {prices.data && (
        <>
          {prices.data.warnings.map((w) => (
            <div key={w} className="rounded border border-amber-400 bg-amber-50 p-2 text-sm text-amber-900 dark:bg-amber-950 dark:text-amber-200">{w}</div>
          ))}
          <div className="flex flex-wrap items-center gap-1 text-xs" data-tour="overlay-chips">
            <span className="text-slate-500">Overlays</span>
            {OVERLAYS.map((o) => (
              <button key={o.id} onClick={() => toggle("overlays", o.id)} aria-pressed={layout.overlays.includes(o.id)}
                className={`rounded px-2 py-0.5 ${layout.overlays.includes(o.id) ? "bg-indigo-600 text-white" : "bg-slate-200 dark:bg-slate-800"}`}>{o.label}</button>
            ))}
            <span className="ml-3 text-slate-500">Panes</span>
            {PANES.map((p) => (
              <button key={p.id} onClick={() => toggle("panes", p.id)} aria-pressed={layout.panes.includes(p.id)}
                className={`rounded px-2 py-0.5 ${layout.panes.includes(p.id) ? "bg-indigo-600 text-white" : "bg-slate-200 dark:bg-slate-800"}`}>{p.label}</button>
            ))}
            <span className="ml-auto flex gap-1" data-tour="layout-buttons">
              <button onClick={() => slot("save")} className="rounded bg-slate-200 px-2 py-0.5 dark:bg-slate-800">Save layout</button>
              <button onClick={() => slot("load")} className="rounded bg-slate-200 px-2 py-0.5 dark:bg-slate-800">Load</button>
              <button onClick={() => update({ overlays: [], panes: [] })} className="rounded bg-slate-200 px-2 py-0.5 dark:bg-slate-800">Clear</button>
            </span>
          </div>
          {ind.error && <div role="alert" className="rounded border border-amber-400 bg-amber-50 p-2 text-sm text-amber-900 dark:bg-amber-950 dark:text-amber-200">Indicators unavailable: {(ind.error as Error).message}</div>}
          <CandleChart bars={prices.data.bars} interval={interval} ind={ind.data} overlayIds={layout.overlays} paneIds={layout.panes} />
          <p className="text-xs text-slate-500">
            {prices.data.count} bars · source: {prices.data.source} · {prices.data.adjusted ? "split/dividend adjusted" : "raw"}
            {prices.data.downsampled && " · showing most recent bars only"}
          </p>
        </>
      )}
      <ScorecardPanel symbol={symbol} />
    </div>
  );
}

export default function Page() {
  return <Suspense fallback={<div className="skeleton h-[520px]" />}><SymbolView /></Suspense>;
}
