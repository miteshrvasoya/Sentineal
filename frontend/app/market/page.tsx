"use client";
import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { Suspense } from "react";
import { api } from "@/lib/api";
import { pct } from "@/lib/explain";

const card = "rounded border border-slate-200 p-3 dark:border-slate-800";
const sg = (v: number | null | undefined) => (v === null || v === undefined ? "n/a" : `${v >= 0 ? "+" : ""}${(v * 100).toFixed(1)}%`);

function Gauge({ label, v, tip }: { label: string; v: number | null; tip: string }) {
  const p = v === null ? 0 : Math.round(v * 100);
  return (
    <div title={tip} className="text-sm"><div className="flex justify-between"><span>{label}</span><span className="tabular-nums text-slate-500">{v === null ? "n/a" : `${p}%`}</span></div>
      <div className="h-2 rounded bg-slate-200 dark:bg-slate-800"><div className={`h-2 rounded ${p >= 60 ? "bg-green-600" : p <= 40 ? "bg-red-600" : "bg-slate-500"}`} style={{ width: `${p}%` }} /></div></div>
  );
}

function View() {
  const b = useQuery({ queryKey: ["breadth"], queryFn: api.breadth });
  const s = useQuery({ queryKey: ["sectors"], queryFn: api.sectors });
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-3"><h1 className="text-2xl font-semibold">Market breadth and sectors</h1>
        <span className="rounded bg-violet-600 px-2 py-0.5 text-xs text-white">Computed over the stocks stored here, not the whole market</span></div>
      <section className={card} data-tour="mkt-breadth">
        <h2 className="text-lg font-semibold">Breadth</h2>
        {b.isLoading && <div className="skeleton h-24" />}
        {b.error && <p className="text-sm text-slate-500">No stored stocks yet. Run make seed.</p>}
        {b.data && b.data.n > 0 && (<>
          <p className="mb-2 text-sm font-medium">{b.data.reading}</p>
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            <Gauge label="Above 50-day average" v={b.data.above_sma50} tip="Share of stocks whose price is above their 50-day average" />
            <Gauge label="Above 200-day average" v={b.data.above_sma200} tip="Share above their 200-day average (the long-term trend line)" />
            <Gauge label="Up over 5 days" v={b.data.positive_5d} tip="Share of stocks with a positive 5-day return" />
            <Gauge label="Up over 1 month" v={b.data.positive_21d} tip="Share of stocks with a positive 21-day return" />
            <Gauge label="Near 52-week high" v={b.data.near_52w_high} tip="Within 3% of the 52-week high" />
            <Gauge label="Near 52-week low" v={b.data.near_52w_low} tip="Within 5% of the 52-week low" />
          </div>
          <p className="mt-2 text-xs text-slate-500">Based on {b.data.n} stored stocks. Breadth asks &quot;how many stocks are participating?&quot;. An index can rise while most stocks fall, which breadth reveals. Median 5-day return: {pct(b.data.median_5d_return, 1)}.</p></>)}
      </section>
      <section className={card} data-tour="mkt-sectors">
        <h2 className="text-lg font-semibold">Sector rotation</h2>
        {s.data && (<>
          <div className="overflow-x-auto"><table className="w-full text-sm tabular-nums"><thead className="text-left text-xs text-slate-500"><tr><th>Sector</th><th>Stocks</th><th>5d</th><th>1m</th><th>3m</th><th>6m</th><th title="Rank by 1-month return">Rank 1m</th><th title="Rank by 6-month return">Rank 6m</th><th title="Rank 6m minus rank 1m. Positive: climbing, money moving in. Negative: fading.">Rotation</th></tr></thead>
            <tbody>{s.data.rows.map((r) => (
              <tr key={r.sector} className="border-t border-slate-200 dark:border-slate-800"><td className="py-1 font-medium">{r.sector}</td><td>{r.n}</td><td>{sg(r.ret_5d)}</td><td>{sg(r.ret_21d)}</td><td>{sg(r.ret_63d)}</td><td>{sg(r.ret_126d)}</td><td>{r.rank_21d}</td><td>{r.rank_126d}</td>
                <td className={r.rotation === null ? "" : r.rotation > 0 ? "text-green-700 dark:text-green-400" : r.rotation < 0 ? "text-red-600" : ""}>{r.rotation === null ? "" : r.rotation > 0 ? `▲ +${r.rotation}` : r.rotation < 0 ? `▼ ${r.rotation}` : "–"}</td></tr>))}</tbody></table></div>
          <p className="mt-2 text-xs text-slate-500">{s.data.note}</p></>)}
      </section>
      <p className="text-xs text-slate-500">Want a list of stocks instead? Try the <Link href="/screener" className="text-indigo-600 underline dark:text-indigo-300">Screener</Link>. Educational tool, not investment advice.</p>
    </div>
  );
}

export default function Page() { return <Suspense fallback={<div className="skeleton h-96" />}><View /></Suspense>; }
