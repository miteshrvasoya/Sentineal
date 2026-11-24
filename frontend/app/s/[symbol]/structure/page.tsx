"use client";
import { useQuery } from "@tanstack/react-query";
import { useParams, useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";
import PatternsPanel from "@/components/PatternsPanel";
import StructureChart, { DEFAULT_LAYERS, LAYERS } from "@/components/StructureChart";
import SymbolTabs from "@/components/SymbolTabs";
import { api } from "@/lib/api";

const INTERVALS = ["15m", "1h", "1d"] as const;
const LEGEND: [string, string][] = [
  ["Swing high / low", "A local peak or trough. It needs k bars on each side, so it only becomes known k bars later; the chart marks it where it formed, but it was not tradable knowledge until then."],
  ["HH / HL / LH / LL", "Higher high, higher low, lower high, lower low versus the previous swing of the same kind. HH+HL is an uptrend, LH+LL a downtrend, a mix is a range."],
  ["BOS (break of structure)", "A close beyond the last swing in the direction of the current trend: the trend continues."],
  ["CHoCH (change of character)", "A close beyond the last swing against the current trend. An early sign the trend may be changing, and often a false alarm."],
  ["Liquidity sweep", "A wick pokes past a swing high/low but the bar closes back inside: stops above or below were 'taken' without acceptance beyond the level."],
  ["Fair value gap (FVG)", "A 3-candle gap where the middle candle's range is not overlapped by the neighbours. Shown only while unfilled (the 8 most recent). The idea is that price often revisits it; the evidence is mixed."],
  ["Order block (OB)", "The last opposite-colour candle before the move that broke structure. Shown only until a close goes through it (the 8 most recent)."],
  ["Premium / discount", "Within the latest swing range, above the 50% equilibrium is 'premium' (expensive), below is 'discount'."],
  ["Support / resistance zones", "Clusters of past swing prices (DBSCAN, width tied to ATR). More touches = a more-tested zone, not a stronger one."],
  ["Fibonacci", "Retracement and extension levels of the latest confirmed swing leg."],
  ["Pivots", "Classic daily pivot levels computed from the last completed period."],
  ["Volume profile", "Volume traded at each price over the window. POC = most traded price; value area (VAH/VAL) holds ~70% of volume."],
];

function useDark() {
  const [d, setD] = useState(false);
  useEffect(() => {
    const read = () => setD(document.documentElement.classList.contains("dark"));
    read();
    const mo = new MutationObserver(read);
    mo.observe(document.documentElement, { attributes: true, attributeFilter: ["class"] });
    return () => mo.disconnect();
  }, []);
  return d;
}

function View() {
  const symbol = decodeURIComponent(String(useParams().symbol)).toUpperCase();
  const router = useRouter();
  const sp = useSearchParams();
  const interval = (INTERVALS as readonly string[]).includes(sp.get("i") ?? "") ? (sp.get("i") as string) : "1d";
  const adjusted = sp.get("adj") !== "0";
  const [k, setK] = useState(5);
  const [layers, setLayers] = useState<string[]>(DEFAULT_LAYERS);
  const dark = useDark();
  const setI = (v: string) => { const p = new URLSearchParams(sp.toString()); p.set("i", v); router.replace(`?${p.toString()}`); };

  const prices = useQuery({ queryKey: ["prices", symbol, interval, adjusted], queryFn: () => api.prices(symbol, interval, adjusted) });
  const st = useQuery({ queryKey: ["structure", symbol, interval, adjusted, k], queryFn: () => api.structure(symbol, interval, adjusted, k), enabled: !!prices.data });
  const pat = useQuery({ queryKey: ["patterns", symbol, interval, adjusted], queryFn: () => api.patterns(symbol, interval, adjusted), enabled: !!prices.data });

  const toggle = (id: string) => setLayers((l) => (l.includes(id) ? l.filter((x) => x !== id) : [...l, id]));
  const err = prices.error ?? st.error;
  // The analysis covers the last N bars; chart only those so overlays line up.
  const bars = prices.data && st.data ? prices.data.bars.slice(-st.data.bars) : [];
  const s = st.data;

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-3">
        <h1 className="text-2xl font-semibold">{symbol}</h1>
        {s && <span className="rounded bg-slate-200 px-2 py-0.5 text-xs dark:bg-slate-800">trend: <b>{s.trend}</b></span>}
        {s?.dealing_range && <span className="rounded bg-slate-200 px-2 py-0.5 text-xs dark:bg-slate-800">{s.dealing_range.zone} ({s.dealing_range.position_pct}% of range)</span>}
        <div className="ml-auto flex items-center gap-1 text-sm">
          {INTERVALS.map((i) => <button key={i} onClick={() => setI(i)} className={`rounded px-2 py-1 ${i === interval ? "bg-indigo-600 text-white" : "bg-slate-200 dark:bg-slate-800"}`}>{i}</button>)}
          <label className="ml-3 flex items-center gap-1">swing k
            <select value={k} onChange={(e) => setK(Number(e.target.value))} className="rounded border border-slate-300 bg-white px-1 dark:border-slate-700 dark:bg-slate-900">
              {[2, 3, 5, 8, 10].map((x) => <option key={x}>{x}</option>)}
            </select></label>
        </div>
      </div>
      <SymbolTabs />
      {(prices.isLoading || st.isLoading) && <div className="skeleton h-[620px]" />}
      {err && <div role="alert" className="rounded border border-red-400 bg-red-50 p-4 text-sm text-red-800 dark:bg-red-950 dark:text-red-200"><b>Could not load structure for {symbol}.</b> {(err as Error).message}</div>}
      {s && prices.data && (
        <>
          <div className="flex flex-wrap gap-1 text-xs">
            {LAYERS.map((l) => (
              <button key={l.id} aria-pressed={layers.includes(l.id)} onClick={() => toggle(l.id)}
                className={`rounded px-2 py-0.5 ${layers.includes(l.id) ? "bg-indigo-600 text-white" : "bg-slate-200 dark:bg-slate-800"}`}>{l.label}</button>
            ))}
          </div>
          <StructureChart bars={bars} interval={interval} s={s} patterns={pat.data} layers={layers} dark={dark} />
          <div className="grid gap-3 text-sm md:grid-cols-3">
            {s.volume_profile && (
              <div className="rounded border border-slate-200 p-3 dark:border-slate-800"><h3 className="font-semibold">Volume profile ({s.volume_profile.window} bars)</h3>
                <p>POC {s.volume_profile.poc.toFixed(2)} · VAH {s.volume_profile.vah.toFixed(2)} · VAL {s.volume_profile.val.toFixed(2)}</p>
                <p className="text-xs text-slate-500">HVN: {s.volume_profile.hvn.map((x) => x.toFixed(0)).join(", ") || "none"} · LVN: {s.volume_profile.lvn.map((x) => x.toFixed(0)).join(", ") || "none"}</p></div>
            )}
            <div className="rounded border border-slate-200 p-3 dark:border-slate-800"><h3 className="font-semibold">Wyckoff-style read <span className="text-xs font-normal text-slate-500">(heuristic)</span></h3>
              <p>{s.wyckoff.label.replace(/_/g, " ")}</p><p className="text-xs text-slate-500">{s.wyckoff.evidence.join(" · ")}</p></div>
            <div className="rounded border border-slate-200 p-3 dark:border-slate-800"><h3 className="font-semibold">Daily pivots (classic)</h3>
              <p className="tabular-nums text-xs">{Object.entries(s.pivots.daily?.classic ?? {}).map(([n, v]) => `${n} ${v.toFixed(1)}`).join(" · ")}</p>
              <p className="text-xs text-slate-500">from {s.pivots.daily?.period}</p></div>
          </div>
        </>
      )}
      {pat.data && <PatternsPanel p={pat.data} />}
      {pat.error && <p role="alert" className="text-sm text-amber-600">Patterns unavailable: {(pat.error as Error).message}</p>}
      <details className="rounded border border-slate-200 p-3 text-sm dark:border-slate-800">
        <summary className="cursor-pointer font-semibold">What do these markings mean?</summary>
        <dl className="mt-2 space-y-2">{LEGEND.map(([t, d]) => <div key={t}><dt className="font-medium">{t}</dt><dd className="text-slate-600 dark:text-slate-400">{d}</dd></div>)}</dl>
        <p className="mt-3 text-xs text-slate-500">These are descriptive heuristics from a popular trading vocabulary. They label what price did; they are not forecasts.</p>
      </details>
    </div>
  );
}

export default function Page() { return <Suspense fallback={<div className="skeleton h-[620px]" />}><View /></Suspense>; }
