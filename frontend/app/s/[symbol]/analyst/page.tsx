"use client";
import { useMutation, useQuery } from "@tanstack/react-query";
import { useParams } from "next/navigation";
import { Suspense, useState } from "react";
import { AiFooter, AiStatus, ClaimList, Evidence, FactsDisclosure } from "@/components/AiParts";
import RedFlagList from "@/components/RedFlagList";
import SymbolTabs from "@/components/SymbolTabs";
import { api } from "@/lib/api";

const card = "rounded border border-slate-200 p-3 dark:border-slate-800";
const EXAMPLE = JSON.stringify({ n_trades: 18, total_return: 0.42, sharpe: 1.6, max_drawdown: -0.31, years: 2, costs_included: false, oos_fraction: 0, n_params_tuned: 6, top5_trade_share: 0.7 }, null, 2);
const stanceColor = (s: string) => (s === "leaning positive" ? "bg-green-600" : s === "leaning negative" ? "bg-red-600" : "bg-slate-500");

function Flags({ symbol }: { symbol: string }) {
  const q = useQuery({ queryKey: ["redflags", symbol], queryFn: () => api.redFlags(symbol), retry: false });
  return (
    <section className={card} data-tour="red-flags">
      <h2 className="text-lg font-semibold">Red flags</h2>
      {q.isLoading && <div className="skeleton h-12" />}
      {q.error && <p className="text-sm text-slate-500">{(q.error as Error).message}</p>}
      {q.data && <RedFlagList d={q.data} />}
    </section>
  );
}

function Analyst({ symbol }: { symbol: string }) {
  const m = useMutation({ mutationFn: () => api.aiAnalyst(symbol) });
  const d = m.data, r = d?.report;
  return (
    <section className={card} data-tour="ai-analyst">
      <div className="flex flex-wrap items-center gap-2"><h2 className="text-lg font-semibold">AI analyst</h2>
        <span className="rounded bg-violet-600 px-2 py-0.5 text-xs text-white">AI-generated, may be wrong, not investment advice</span>
        <button onClick={() => m.mutate()} disabled={m.isPending} className="ml-auto rounded bg-indigo-600 px-3 py-1 text-sm text-white disabled:opacity-50">{m.isPending ? "Writing…" : d ? "Regenerate" : "Write the report"}</button></div>
      <p className="my-1 text-xs text-slate-500">Summarises the computed facts (price, risk, scorecard, fundamentals, news, model verdicts) in plain language. It cannot see anything else.</p>
      {m.error && <p className="text-sm text-red-600" role="alert">{(m.error as Error).message}</p>}
      {d && <AiStatus d={d} report={r} />}
      {r && d && (
        <div className="mt-2 space-y-3">
          <div><span className={`rounded px-2 py-0.5 text-xs text-white ${stanceColor(r.stance)}`} title="The weight of the evidence in the facts, not a recommendation">{r.stance}</span>
            <span className="ml-2 font-medium">{r.headline}</span><p className="mt-1 text-sm">{r.plain_summary}</p></div>
          <div className="grid gap-4 md:grid-cols-2">
            <ClaimList title="Points in favour" items={r.in_favour} facts={d.facts} tone="good" />
            <ClaimList title="Points against" items={r.against} facts={d.facts} tone="bad" />
          </div>
          <ClaimList title="Where the signals disagree" items={r.conflicts} facts={d.facts} tone="warn" />
          {r.data_gaps.length > 0 && <div><h3 className="mb-1 text-sm font-semibold">What is missing</h3><ul className="list-disc pl-5 text-sm">{r.data_gaps.map((g) => <li key={g}>{g}</li>)}</ul></div>}
        </div>)}
      {d && <FactsDisclosure facts={d.facts} missing={d.missing} />}
      {d && <AiFooter d={d} />}
    </section>
  );
}

function Move({ symbol }: { symbol: string }) {
  const [start, setStart] = useState(""), [end, setEnd] = useState("");
  const m = useMutation({ mutationFn: () => api.aiExplainMove(symbol, start || undefined, end || undefined) });
  const d = m.data, r = d?.report;
  const art = (id: string) => d?.articles.find((a) => a.id === id);
  return (
    <section className={card} data-tour="ai-move">
      <div className="flex flex-wrap items-center gap-2"><h2 className="text-lg font-semibold">Why did it move?</h2>
        <label className="text-xs">from <input type="date" value={start} onChange={(e) => setStart(e.target.value)} className="rounded border border-slate-300 bg-white px-1 dark:border-slate-700 dark:bg-slate-900" /></label>
        <label className="text-xs">to <input type="date" value={end} onChange={(e) => setEnd(e.target.value)} className="rounded border border-slate-300 bg-white px-1 dark:border-slate-700 dark:bg-slate-900" /></label>
        <button onClick={() => m.mutate()} disabled={m.isPending} className="ml-auto rounded bg-indigo-600 px-3 py-1 text-sm text-white disabled:opacity-50">{m.isPending ? "Looking…" : "Explain the move"}</button></div>
      <p className="my-1 text-xs text-slate-500">Leave the dates empty for the last five trading days. It pairs the price move with stored news and the index, and can only show association, never proof of cause.</p>
      {m.error && <p className="text-sm text-red-600" role="alert">{(m.error as Error).message}</p>}
      {d && <p className="text-xs text-slate-500">Period {d.start} to {d.end}: stock {typeof d.facts["move.stock_return"] === "number" ? `${((d.facts["move.stock_return"] as number) * 100).toFixed(2)}%` : "n/a"}
        {typeof d.facts["move.index_return"] === "number" ? `, index ${((d.facts["move.index_return"] as number) * 100).toFixed(2)}%` : ", index comparison unavailable"}.</p>}
      {d && <AiStatus d={d} report={r} />}
      {r && d && (
        <div className="mt-2 space-y-3 text-sm">
          <p>{r.plain_summary}</p>
          <ClaimList title="Market context" items={[r.market_context]} facts={d.facts} />
          {r.candidates.length > 0 && <div><h3 className="mb-1 text-sm font-semibold">Possible explanations</h3><ul className="space-y-1.5">{r.candidates.map((c, i) => (
            <li key={i} className="border-l-2 border-indigo-500 pl-2">{c.text} <span className={`rounded px-1 text-[10px] ${c.strength === "plausible" ? "bg-green-100 text-green-800 dark:bg-green-950 dark:text-green-300" : "bg-slate-200 dark:bg-slate-800"}`}>{c.strength}</span>
              <Evidence ids={c.evidence} facts={d.facts} />
              {c.article_ids.map((id) => { const a = art(id); return a ? <a key={id} href={a.url} target="_blank" rel="noreferrer" className="ml-1 text-xs text-indigo-600 underline dark:text-indigo-300">{a.source}: {a.title.slice(0, 50)}</a> : null; })}</li>))}</ul></div>}
          <p className="text-slate-600 dark:text-slate-400"><b>Unexplained:</b> {r.unexplained}</p>
        </div>)}
      {d && d.articles.length > 0 && <details className="mt-2 text-xs"><summary className="cursor-pointer text-slate-500">News the AI could see ({d.articles.length})</summary>
        <ul className="mt-1 list-disc pl-5">{d.articles.map((a) => <li key={a.id}>{a.title} <span className="text-slate-500">({a.source})</span>{a.injection_flags && a.injection_flags.length > 0 && <span className="ml-1 rounded bg-amber-500 px-1 text-[10px] text-white" title={a.injection_flags.join(", ")}>contains instruction-like text, fenced as data</span>}</li>)}</ul></details>}
      {d && <FactsDisclosure facts={d.facts} missing={d.missing} />}
      {d && <AiFooter d={d} />}
    </section>
  );
}

function Reviewer() {
  const [strategy, setStrategy] = useState("moving-average crossover");
  const [text, setText] = useState(EXAMPLE);
  const [bad, setBad] = useState<string | null>(null);
  const m = useMutation({ mutationFn: () => { let obj: Record<string, unknown>; try { obj = JSON.parse(text); setBad(null); } catch (e) { setBad(String(e)); throw e; } return api.aiBacktestReview(strategy, obj); } });
  const d = m.data, r = d?.report;
  return (
    <section className={card} data-tour="ai-review">
      <div className="flex flex-wrap items-center gap-2"><h2 className="text-lg font-semibold">Backtest reviewer</h2>
        <button onClick={() => m.mutate()} disabled={m.isPending} className="ml-auto rounded bg-indigo-600 px-3 py-1 text-sm text-white disabled:opacity-50">{m.isPending ? "Reviewing…" : "Review"}</button></div>
      <p className="my-1 text-xs text-slate-500">A sceptical second pair of eyes for a backtest result. The red flags are automatic checks and always run, even with no LLM. Paste a result summary below (the Phase 9 backtester will fill this in for you). Try the example: it is deliberately bad.</p>
      <input value={strategy} onChange={(e) => setStrategy(e.target.value)} maxLength={80} aria-label="Strategy name" className="mb-1 w-full rounded border border-slate-300 bg-white px-2 py-1 text-sm dark:border-slate-700 dark:bg-slate-900" />
      <textarea value={text} onChange={(e) => setText(e.target.value)} rows={7} aria-label="Backtest metrics as JSON" className="w-full rounded border border-slate-300 bg-white p-2 font-mono text-xs dark:border-slate-700 dark:bg-slate-900" />
      {bad && <p className="text-sm text-red-600" role="alert">That is not valid JSON: {bad}</p>}
      {m.error && !bad && <p className="text-sm text-red-600" role="alert">{(m.error as Error).message}</p>}
      {d && d.red_flags.length > 0 && <div className="mt-2"><h3 className="mb-1 text-sm font-semibold">Automatic red flags</h3><ul className="space-y-1">{d.red_flags.map((f) => <li key={f.id} className="border-l-2 border-red-600 pl-2 text-sm">{f.message}</li>)}</ul></div>}
      {d && d.red_flags.length === 0 && <p className="mt-2 text-sm text-green-700 dark:text-green-400">No automatic red flags. That does not make the result reliable.</p>}
      {d && <div className="mt-2"><AiStatus d={d} report={r} /></div>}
      {r && d && (
        <div className="mt-2 space-y-3 text-sm">
          <p><span className={`rounded px-2 py-0.5 text-xs text-white ${r.verdict === "unreliable" ? "bg-red-600" : r.verdict === "weak evidence" ? "bg-amber-500" : "bg-slate-500"}`}>{r.verdict}</span> {r.plain_summary}</p>
          <ClaimList title="Concerns" items={r.concerns} facts={d.facts} tone="bad" />
          <ClaimList title="Strengths" items={r.strengths} facts={d.facts} tone="good" />
          {r.what_to_check_next.length > 0 && <div><h3 className="mb-1 text-sm font-semibold">What to check next</h3><ul className="list-disc pl-5">{r.what_to_check_next.map((x) => <li key={x}>{x}</li>)}</ul></div>}
        </div>)}
      {d && <AiFooter d={d} />}
    </section>
  );
}

function View() {
  const symbol = decodeURIComponent(String(useParams().symbol)).toUpperCase();
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-3"><h1 className="text-2xl font-semibold">{symbol}</h1>
        <span className="rounded bg-violet-600 px-2 py-0.5 text-xs text-white">AI layer: it explains computed facts, it does not invent them</span></div>
      <SymbolTabs />
      <Flags symbol={symbol} />
      <Analyst symbol={symbol} />
      <Move symbol={symbol} />
      <Reviewer />
      <p className="text-xs text-slate-500">Educational tool, not investment advice. AI output is checked for advice, invented numbers and unknown citations; failures are withheld.</p>
    </div>
  );
}

export default function Page() { return <Suspense fallback={<div className="skeleton h-96" />}><View /></Suspense>; }
