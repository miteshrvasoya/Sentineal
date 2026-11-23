"use client";
import { useQuery } from "@tanstack/react-query";
import { useParams, useRouter, useSearchParams } from "next/navigation";
import { Suspense } from "react";
import CandleChart from "@/components/CandleChart";
import { api } from "@/lib/api";

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
        <div className="ml-auto flex items-center gap-1">
          {INTERVALS.map((i) => (
            <button key={i} onClick={() => set("i", i)}
              className={`rounded px-2 py-1 text-sm ${i === interval ? "bg-indigo-600 text-white" : "bg-slate-200 dark:bg-slate-800"}`}>{i}</button>
          ))}
          <label className="ml-3 flex items-center gap-1 text-sm">
            <input type="checkbox" checked={adjusted} onChange={(e) => set("adj", e.target.checked ? "1" : "0")} /> adjusted
          </label>
        </div>
      </div>

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
          <CandleChart bars={prices.data.bars} interval={interval} />
          <p className="text-xs text-slate-500">
            {prices.data.count} bars · source: {prices.data.source} · {prices.data.adjusted ? "split/dividend adjusted" : "raw"}
            {prices.data.downsampled && " · showing most recent bars only"}
          </p>
        </>
      )}
    </div>
  );
}

export default function Page() {
  return <Suspense fallback={<div className="skeleton h-[520px]" />}><SymbolView /></Suspense>;
}
