"use client";
import Link from "next/link";
import { useState } from "react";
import { type Idea } from "@/lib/api";
import { inr, pct0, pctS } from "@/lib/format";
import Term from "./Term";

const chip = { "Looks strong": "bg-green-600 text-white", Mixed: "bg-amber-500 text-white", "Looks weak": "bg-red-600 text-white", "Not enough data": "bg-slate-400 text-white" } as Record<string, string>;
const riskTone = { Lower: "text-green-700 dark:text-green-400", Medium: "text-amber-600", Higher: "text-red-600", Unknown: "text-slate-500" } as Record<string, string>;

export function ScoreBar({ score }: { score: number | null }) {
  if (score === null) return null;
  return (
    <div className="flex items-center gap-2" title={`Score ${score} out of 100: how many of the checks below the stock passes`}>
      <div className="h-2 w-24 rounded bg-slate-200 dark:bg-slate-800"><div className={`h-2 rounded ${score >= 65 ? "bg-green-600" : score >= 45 ? "bg-amber-500" : "bg-red-600"}`} style={{ width: `${score}%` }} /></div>
      <span className="text-xs tabular-nums text-slate-500">{score}/100</span>
    </div>
  );
}

export default function IdeaCard({ i, name, onWatch, watching }: { i: Idea; name?: string; onWatch?: (s: string) => void; watching?: boolean }) {
  const [more, setMore] = useState(false);
  const n = i.numbers;
  return (
    <article className="rounded-lg border border-slate-200 p-4 dark:border-slate-800">
      <header className="flex flex-wrap items-center gap-2">
        <Link href={`/s/${i.symbol}`} className="text-lg font-semibold text-indigo-600 hover:underline dark:text-indigo-300">{i.symbol}</Link>
        {name && <span className="text-sm text-slate-500">{name}</span>}
        <span className={`rounded px-2 py-0.5 text-xs font-medium ${chip[i.label] ?? chip["Not enough data"]}`}>{i.label}</span>
        {i.owned && <span className="rounded bg-sky-100 px-1.5 py-0.5 text-xs text-sky-800 dark:bg-sky-950 dark:text-sky-300">You own this</span>}
        <ScoreBar score={i.score} />
        <span className="ml-auto text-xs">Ups and downs: <b className={riskTone[i.risk]}><Term k="volatility">{i.risk}</Term></b></span>
      </header>
      <p className="mt-0.5 text-xs text-slate-500">{i.sector || "Sector unknown"} · based on {i.checks}</p>
      {i.why.length > 0 && <ul className="mt-2 space-y-1 text-sm">{i.why.slice(0, more ? 8 : 3).map((w) => <li key={w} className="flex gap-1.5"><span className="text-green-600" aria-hidden>✓</span><span>{w}</span></li>)}</ul>}
      {i.watch_out.length > 0 && <ul className="mt-2 space-y-1 text-sm">{i.watch_out.slice(0, more ? 8 : 2).map((w) => <li key={w} className="flex gap-1.5"><span className="text-amber-600" aria-hidden>⚠</span><span>{w}</span></li>)}</ul>}
      {more && (
        <div className="mt-2 space-y-2 text-sm">
          {i.change_my_mind.length > 0 && <div><b>What would change this view</b><ul className="list-disc pl-5 text-slate-600 dark:text-slate-400">{i.change_my_mind.map((c) => <li key={c}>{c}</li>)}</ul></div>}
          <div className="grid grid-cols-2 gap-x-4 gap-y-0.5 text-xs sm:grid-cols-4">
            {n.price != null && <span>Price <b>{inr(n.price, 2)}</b></span>}
            {n.ret_126d != null && <span>6 months <b>{pctS(n.ret_126d)}</b></span>}
            {n.ret_252d != null && <span>1 year <b>{pctS(n.ret_252d)}</b></span>}
            {n.cagr_3y != null && <span>3 yrs / year <b>{pctS(n.cagr_3y)}</b></span>}
            {n.pe != null && <span><Term k="pe">P/E</Term> <b>{n.pe.toFixed(1)}</b></span>}
            {n.roe != null && <span><Term k="roe">ROE</Term> <b>{pct0(n.roe)}</b></span>}
            {n.debt_equity != null && <span><Term k="debt">Debt</Term> <b>{n.debt_equity.toFixed(2)}</b></span>}
            {n.dividend_yield != null && <span><Term k="dividend">Dividend</Term> <b>{pct0(n.dividend_yield, 1)}</b></span>}
          </div>
        </div>)}
      <footer className="mt-3 flex flex-wrap items-center gap-2 text-sm">
        <button onClick={() => setMore((m) => !m)} className="text-indigo-600 underline dark:text-indigo-300">{more ? "Show less" : "Show more"}</button>
        <Link href={`/s/${i.symbol}`} className="rounded border border-slate-300 px-2 py-0.5 dark:border-slate-700">Open</Link>
        {onWatch && <button onClick={() => onWatch(i.symbol)} disabled={watching} className="rounded border border-slate-300 px-2 py-0.5 disabled:opacity-60 dark:border-slate-700">{watching ? "Watching ✓" : "Watch"}</button>}
        <Link href={`/?add=${i.symbol}`} className="rounded border border-slate-300 px-2 py-0.5 dark:border-slate-700">I own this</Link>
      </footer>
    </article>
  );
}
