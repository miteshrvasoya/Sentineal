"use client";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useState } from "react";
import { AiFooter, AiStatus, ClaimList, FactsDisclosure } from "@/components/AiParts";
import { ScoreBar } from "@/components/IdeaCard";
import RedFlagList from "@/components/RedFlagList";
import SvgLine from "@/components/SvgLine";
import SymbolTabs from "@/components/SymbolTabs";
import Term from "@/components/Term";
import { api, type Idea } from "@/lib/api";
import { inr, pct0, pctS, tone } from "@/lib/format";
import { useMode } from "@/lib/mode";

const card = "rounded-lg border border-slate-200 p-4 dark:border-slate-800";
const RANGES = [["3M", 63], ["6M", 126], ["1Y", 252], ["5Y", 1260]] as const;
const chip = { "Looks strong": "bg-green-600", Mixed: "bg-amber-500", "Looks weak": "bg-red-600", "Not enough data": "bg-slate-400" } as Record<string, string>;

function Verdict({ title, sub, i, tour }: { title: string; sub: string; i: Idea; tour: string }) {
  return (
    <section data-tour={tour} className={card}>
      <div className="flex flex-wrap items-center gap-2"><h3 className="font-semibold">{title}</h3><span className="text-xs text-slate-500">{sub}</span></div>
      <div className="mt-2 flex flex-wrap items-center gap-3"><span className={`rounded px-2 py-0.5 text-sm font-medium text-white ${chip[i.label] ?? chip["Not enough data"]}`}>{i.label}</span><ScoreBar score={i.score} /><span className="text-xs text-slate-500">{i.checks}</span></div>
      {i.why.length > 0 && <ul className="mt-2 space-y-1 text-sm">{i.why.slice(0, 4).map((w) => <li key={w} className="flex gap-1.5"><span className="text-green-600" aria-hidden>✓</span>{w}</li>)}</ul>}
      {i.watch_out.length > 0 && <ul className="mt-2 space-y-1 text-sm">{i.watch_out.slice(0, 4).map((w) => <li key={w} className="flex gap-1.5"><span className="text-amber-600" aria-hidden>⚠</span>{w}</li>)}</ul>}
      {i.change_my_mind.length > 0 && <p className="mt-2 text-xs text-slate-500">{i.change_my_mind[0]}</p>}
    </section>
  );
}

export default function SimpleStock({ symbol }: { symbol: string }) {
  const qc = useQueryClient();
  const { setMode } = useMode();
  const [range, setRange] = useState<number>(252);
  const info = useQuery({ queryKey: ["sym", symbol], queryFn: async () => (await api.search(symbol)).find((s) => s.symbol === symbol) ?? null });
  const quote = useQuery({ queryKey: ["quote", symbol], queryFn: () => api.quote(symbol), refetchInterval: 60_000, retry: false });
  const prices = useQuery({ queryKey: ["prices", symbol, "1d", true], queryFn: () => api.prices(symbol, "1d", true) });
  const view = useQuery({ queryKey: ["stockview", symbol], queryFn: () => api.stockView(symbol), retry: false });
  const flags = useQuery({ queryKey: ["redflags", symbol], queryFn: () => api.redFlags(symbol), retry: false });
  const watched = useQuery({ queryKey: ["watchlist"], queryFn: api.watchlist });
  const isWatched = !!watched.data?.includes(symbol);
  const toggle = useMutation({ mutationFn: () => (isWatched ? api.watchRemove(symbol) : api.watchAdd(symbol)), onSuccess: () => { qc.invalidateQueries({ queryKey: ["watchlist"] }); qc.invalidateQueries({ queryKey: ["watchsummary"] }); } });
  const ai = useMutation({ mutationFn: () => api.aiAnalyst(symbol) });

  const bars = prices.data?.bars ?? [];
  const sel = bars.slice(-range);
  const chg = sel.length > 1 ? sel[sel.length - 1].c / sel[0].c - 1 : null;
  const q = quote.data;
  const last = q?.last ?? (bars.length ? bars[bars.length - 1].c : null);
  const n = view.data?.short.numbers ?? {};
  const ar = ai.data, rep = ar?.report;
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-baseline gap-x-4 gap-y-1">
        <h1 className="text-2xl font-semibold">{symbol}</h1>
        {info.data && <span className="text-slate-500">{info.data.name}{info.data.sector ? ` · ${info.data.sector}` : ""}</span>}
        {last !== null && <span className="flex items-baseline gap-2 tabular-nums"><span className="text-2xl">{inr(last, 2)}</span>
          {q && <span className={tone(q.change)}>{q.change >= 0 ? "+" : ""}{q.change.toFixed(2)} ({q.change_pct.toFixed(2)}%) today</span>}</span>}
        <span data-tour="stock-actions" className="ml-auto flex flex-wrap gap-2 text-sm">
          <button onClick={() => toggle.mutate()} disabled={toggle.isPending} className="rounded border border-slate-300 px-3 py-1 dark:border-slate-700">{isWatched ? "✓ Watching" : "☆ Watch"}</button>
          <Link href={`/?add=${symbol}`} className="rounded bg-indigo-600 px-3 py-1 text-white">I own this</Link>
        </span>
      </div>
      <SymbolTabs />
      {prices.error && <p role="alert" className="rounded border border-red-400 bg-red-50 p-3 text-sm text-red-800 dark:bg-red-950 dark:text-red-200"><b>Could not load prices for {symbol}.</b> {(prices.error as Error).message} Check the symbol is right and that you are online.</p>}
      {prices.isLoading && <div className="skeleton h-48" />}
      {sel.length > 1 && (
        <section data-tour="stock-chart" className={card}>
          <div className="mb-1 flex flex-wrap items-center gap-2"><h2 className="font-semibold">Price history</h2>
            <span className={`text-sm tabular-nums ${tone(chg)}`}>{pctS(chg)} over this period</span>
            <span className="ml-auto flex gap-1 text-xs">{RANGES.map(([l, n2]) => <button key={l} onClick={() => setRange(n2)} aria-pressed={range === n2} className={`rounded px-2 py-0.5 ${range === n2 ? "bg-indigo-600 text-white" : "bg-slate-200 dark:bg-slate-800"}`}>{l}</button>)}</span></div>
          <SvgLine dates={sel.map((b) => new Date(b.t * 1000).toISOString().slice(0, 10))} values={sel.map((b) => b.c)} area zero={false} height={200} fmt={(v) => inr(v)} label="Price history" />
          <p className="text-xs text-slate-500">Closing price each day, adjusted for splits and dividends. Past prices say little about future ones.</p>
        </section>)}

      {view.data && (
        <div className="grid gap-4 md:grid-cols-2">
          <Verdict title="Short-term look" sub="weeks to a few months" i={view.data.short} tour="stock-short" />
          <Verdict title="Long-term look" sub="several years" i={view.data.long} tour="stock-long" />
        </div>)}
      {view.error && <p className={`${card} text-sm text-slate-600 dark:text-slate-400`}>{(view.error as Error).message}</p>}
      {view.data && <p className="text-xs text-slate-500">Compared with {view.data.compared_with} stocks. {view.data.short.ranked ? "" : "Short-term strength ranks need enough price history. "}These are rule-based observations, not recommendations. {view.data.long.label === "Not enough data" && <Link className="text-indigo-600 underline dark:text-indigo-300" href="/discover">Load company financials on the Find stocks page</Link>} </p>}

      {(n.pe != null || n.roe != null || n.debt_equity != null || n.dividend_yield != null) && (
        <section data-tour="stock-numbers" className={card}>
          <h2 className="mb-2 font-semibold">The company in four numbers</h2>
          <ul className="grid gap-2 text-sm sm:grid-cols-2">
            {n.pe != null && <li><b><Term k="pe">P/E {n.pe.toFixed(1)}</Term></b>: you pay ₹{n.pe.toFixed(0)} for every ₹1 of its yearly profit.</li>}
            {n.roe != null && <li><b><Term k="roe">Return on equity {pct0(n.roe)}</Term></b>: every ₹100 of shareholders&apos; money earns about ₹{(n.roe * 100).toFixed(0)} a year.</li>}
            {n.debt_equity != null && <li><b><Term k="debt">Debt {n.debt_equity.toFixed(2)}</Term></b>: it has borrowed ₹{(n.debt_equity * 100).toFixed(0)} for every ₹100 of its own money.</li>}
            {n.dividend_yield != null && <li><b><Term k="dividend">Dividend {pct0(n.dividend_yield, 1)}</Term></b>: ₹{(n.dividend_yield * 100).toFixed(1)} paid out yearly per ₹100 invested at today&apos;s price.</li>}
          </ul>
          <p className="mt-2 text-xs text-slate-500">More detail on the <b>Company health</b> tab.</p>
        </section>)}

      <section data-tour="stock-flags" className={card}>
        <h2 className="mb-2 font-semibold">Warning signs</h2>
        {flags.isLoading && <div className="skeleton h-10" />}
        {flags.error && <p className="text-sm text-slate-500">{(flags.error as Error).message}</p>}
        {flags.data && <RedFlagList d={flags.data} />}
      </section>

      <section data-tour="stock-ai" className={card}>
        <div className="flex flex-wrap items-center gap-2"><h2 className="font-semibold">Explain it in simple words</h2><span className="rounded bg-violet-600 px-1.5 py-0.5 text-[10px] text-white">AI-generated</span>
          <button onClick={() => ai.mutate()} disabled={ai.isPending} className="ml-auto rounded bg-indigo-600 px-3 py-1 text-sm text-white disabled:opacity-50">{ai.isPending ? "Writing…" : ar ? "Write again" : "Explain this stock"}</button></div>
        {ai.error && <p role="alert" className="mt-1 text-sm text-red-600">{(ai.error as Error).message}</p>}
        {ar && <div className="mt-2"><AiStatus d={ar} report={rep} /></div>}
        {rep && ar && <div className="mt-2 space-y-2 text-sm"><p className="font-medium">{rep.headline}</p><p>{rep.plain_summary}</p>
          <ClaimList title="Good signs" items={rep.in_favour} facts={ar.facts} tone="good" /><ClaimList title="Things to watch" items={rep.against} facts={ar.facts} tone="bad" /></div>}
        {ar && rep && <FactsDisclosure facts={ar.facts} missing={ar.missing} />}
        {ar && <AiFooter d={ar} />}
        {!ar && <p className="mt-1 text-xs text-slate-500">An AI reads the numbers above and explains them. It needs a free OpenRouter key (see Settings). Everything else here works without one.</p>}
      </section>
      <p className="text-xs text-slate-500">Want candlestick charts, indicators and forecasting models?{" "}
        <button onClick={() => setMode("advanced")} className="text-indigo-600 underline dark:text-indigo-300">Switch to Advanced view</button>. Educational tool, not investment advice.</p>
    </div>
  );
}
