"use client";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";
import LeadLagChart from "@/components/LeadLagChart";
import SentimentChart from "@/components/SentimentChart";
import SymbolTabs from "@/components/SymbolTabs";
import { api, type Article, type Enriched } from "@/lib/api";

const MAT = { high: "bg-red-600 text-white", medium: "bg-amber-500 text-white", low: "bg-slate-300 text-slate-800 dark:bg-slate-700 dark:text-slate-100" } as const;
const AIBADGE = "AI-generated, may be wrong, not investment advice";
const chip = { positive: "bg-green-600 text-white", negative: "bg-red-600 text-white", neutral: "bg-slate-300 text-slate-800 dark:bg-slate-700 dark:text-slate-100" };

function Gauge({ v }: { v: number | null }) {
  if (v === null) return <span className="text-xs text-slate-500">no market data yet</span>;
  const pct = ((Math.max(-1, Math.min(1, v)) + 1) / 2) * 100;
  return (
    <div className="w-56">
      <div className="relative h-2 rounded bg-gradient-to-r from-red-500 via-slate-300 to-green-500">
        <div className="absolute -top-1 h-4 w-1 rounded bg-slate-900 dark:bg-white" style={{ left: `${pct}%` }} />
      </div>
      <div className="mt-1 flex justify-between text-[10px] text-slate-500"><span>negative</span><span>{v.toFixed(2)}</span><span>positive</span></div>
    </div>
  );
}

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
  const [days, setDays] = useState(90);
  const [highOnly, setHighOnly] = useState(false);
  const dark = useDark();
  const qc = useQueryClient();
  const news = useQuery({ queryKey: ["news", symbol, days], queryFn: () => api.news(symbol, days) });
  const sent = useQuery({ queryKey: ["sent", symbol, days], queryFn: () => api.sentiment(symbol, days), retry: false });
  const market = useQuery({ queryKey: ["msent"], queryFn: () => api.marketSentiment(30) });
  const prices = useQuery({ queryKey: ["prices", symbol, "1d", true], queryFn: () => api.prices(symbol, "1d", true) });
  const enriched = useQuery({ queryKey: ["enriched", symbol, days], queryFn: () => api.newsEnriched(symbol, days), retry: false });
  const [matOnly, setMatOnly] = useState(false);
  const enrich = useMutation({
    mutationFn: () => api.enrich(symbol),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["enriched"] }); qc.invalidateQueries({ queryKey: ["llmstatus"] }); },
  });
  const emap = new Map<string, Enriched>((enriched.data?.articles ?? []).map((a) => [a.id, a]));
  const refresh = useMutation({
    mutationFn: () => api.refreshNews(symbol, Math.min(days, 90)),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["news"] }); qc.invalidateQueries({ queryKey: ["sent"] }); qc.invalidateQueries({ queryKey: ["msent"] }); },
  });
  const arts: Article[] = (news.data?.articles ?? [])
    .filter((a) => !highOnly || Math.abs(a.score) >= 0.5)
    .filter((a) => !matOnly || emap.get(a.id)?.materiality === "high");
  const s = sent.data;
  const model = news.data?.model;

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-3">
        <h1 className="text-2xl font-semibold">{symbol}</h1>
        {model && <span className={`rounded px-2 py-0.5 text-xs ${model === "finbert" ? "bg-green-600 text-white" : "bg-amber-500 text-white"}`}>
          scored by {model === "finbert" ? "FinBERT" : "VADER fallback (less accurate on financial text)"}</span>}
        <div className="ml-auto flex items-center gap-2 text-sm">
          <label>window <select value={days} onChange={(e) => setDays(Number(e.target.value))} className="rounded border border-slate-300 bg-white px-1 dark:border-slate-700 dark:bg-slate-900">
            {[14, 30, 90, 180].map((d) => <option key={d}>{d}</option>)}</select> days</label>
          <button data-tour="fetch-news" onClick={() => refresh.mutate()} disabled={refresh.isPending} className="rounded bg-indigo-600 px-3 py-1 text-white disabled:opacity-50">
            {refresh.isPending ? "Fetching…" : "Fetch latest news"}</button>
          <button data-tour="ai-enrich" onClick={() => enrich.mutate()} disabled={enrich.isPending} title="Ask the configured LLM to classify the stored articles"
            className="rounded border border-indigo-600 px-3 py-1 text-indigo-600 disabled:opacity-50 dark:text-indigo-300">{enrich.isPending ? "Analysing…" : "AI-enrich"}</button>
        </div>
      </div>
      <SymbolTabs />

      {refresh.data && (
        <div role="status" className="rounded border border-slate-300 p-2 text-sm dark:border-slate-700">
          Fetched {refresh.data.fetched}: {refresh.data.new} new, {refresh.data.duplicates} duplicates, {refresh.data.scored} scored.
          {Object.entries(refresh.data.errors).map(([k, v]) => <div key={k} className="text-amber-600">{k}: {v}</div>)}
        </div>
      )}
      {refresh.error && <div role="alert" className="rounded border border-red-400 bg-red-50 p-2 text-sm text-red-800 dark:bg-red-950 dark:text-red-200">{(refresh.error as Error).message}</div>}
      {enrich.data && !enrich.data.available && (
        <div role="status" className="rounded border border-slate-300 p-2 text-sm dark:border-slate-700"><b>LLM unavailable.</b> {enrich.data.reason} Everything else still works with FinBERT/VADER.</div>
      )}
      {enrich.data?.available && (
        <div role="status" className="rounded border border-slate-300 p-2 text-sm dark:border-slate-700">
          AI analysis: {enrich.data.enrichment?.processed} articles classified ({enrich.data.enrichment?.flagged} flagged, {enrich.data.enrichment?.summaries_removed} summaries removed by guardrails),
          {" "}{enrich.data.sentiment?.scored} LLM sentiment scores{enrich.data.enrichment?.model ? ` via ${enrich.data.enrichment.model}` : ""}.
          {(enrich.data.enrichment?.stopped || enrich.data.sentiment?.stopped) && <div className="text-amber-600">Stopped: {enrich.data.enrichment?.stopped ?? enrich.data.sentiment?.stopped}</div>}
        </div>
      )}
      {enrich.error && <div role="alert" className="rounded border border-red-400 bg-red-50 p-2 text-sm text-red-800 dark:bg-red-950 dark:text-red-200">{(enrich.error as Error).message}</div>}
      {news.error && <div role="alert" className="rounded border border-red-400 bg-red-50 p-2 text-sm text-red-800 dark:bg-red-950 dark:text-red-200">{(news.error as Error).message}</div>}
      {news.data && news.data.count === 0 && (
        <p className="rounded border border-slate-300 p-4 text-sm dark:border-slate-700">No stored articles for {symbol} in this window. Click <b>Fetch latest news</b>. Without API keys it uses Google News RSS and GDELT; if both are unreachable from your network you will see the provider errors above.</p>
      )}

      <div className="flex flex-wrap items-center gap-6 rounded border border-slate-200 p-3 dark:border-slate-800">
        <div data-tour="market-gauge"><h3 className="mb-1 text-sm font-semibold">Market-wide sentiment (30d)</h3><Gauge v={market.data?.latest ?? null} /></div>
        {s?.latest && <div className="text-sm tabular-nums"><h3 className="mb-1 font-semibold">Latest day</h3>
          <p>mean {s.latest.mean_sent?.toFixed(2) ?? "–"} · recency-weighted {s.latest.recency_weighted?.toFixed(2) ?? "–"} · {s.latest.n_articles} articles · pos/neg {s.latest.pos_ratio?.toFixed(2) ?? "–"}</p>
          <p className="text-xs text-slate-500">volume z {s.latest.volume_z?.toFixed(1) ?? "–"}{s.latest.volume_spike ? " (spike)" : ""} · momentum {s.latest.sent_mom?.toFixed(2) ?? "–"}{s.latest.divergence ? ` · divergence ${s.latest.divergence > 0 ? "(price up, sentiment falling)" : "(price down, sentiment rising)"}` : ""}</p></div>}
      </div>

      {enriched.data && (
        <section data-tour="agreement" className="rounded border border-slate-200 p-3 dark:border-slate-800">
          <div className="flex flex-wrap items-center gap-3"><h2 className="text-lg font-semibold">FinBERT vs LLM second opinion</h2>
            <span className="rounded bg-violet-600 px-2 py-0.5 text-xs text-white">{AIBADGE}</span></div>
          {enriched.data.agreement.n === 0 ? (
            <p className="mt-1 text-sm text-slate-500">{enriched.data.llm_available ? "No LLM scores yet. Click AI-enrich." : "LLM unavailable: add an API key to .env to enable this. The rest of the page does not need it."}</p>
          ) : (
            <>
              <p className="mt-1 text-sm">Label agreement <b>{((enriched.data.agreement.label_agreement ?? 0) * 100).toFixed(0)}%</b> and sign agreement <b>{((enriched.data.agreement.sign_agreement ?? 0) * 100).toFixed(0)}%</b> over {enriched.data.agreement.n} articles (reference: {enriched.data.reference_model}).</p>
              {enriched.data.agreement.disagreements.length > 0 && (
                <details className="mt-1 text-sm"><summary className="cursor-pointer">Biggest disagreements</summary>
                  <ul className="mt-1 space-y-1">{enriched.data.agreement.disagreements.slice(0, 8).map((d) => (
                    <li key={d.article_id}><span className="tabular-nums text-xs text-slate-500">{enriched.data.reference_model} {d.reference.toFixed(2)} · LLM {d.llm.toFixed(2)}</span> {d.title}</li>))}</ul></details>
              )}
            </>
          )}
          {enriched.data.forward_start && <p className="mt-1 text-xs text-slate-500">LLM data collection began {new Date(enriched.data.forward_start * 1000).toLocaleString("en-IN", { timeZone: "Asia/Kolkata" })} IST. LLM output on articles published earlier is <b>not valid for backtesting</b> (the model may already know how those stories played out).</p>}
        </section>
      )}

      {s && prices.data && (
        <section><h2 className="mb-1 text-lg font-semibold">Sentiment vs price</h2>
          <SentimentChart bars={prices.data.bars} daily={s.daily} dark={dark} />
          <p className="text-xs text-slate-500">Line: price. Bars: daily mean sentiment. Amber line: recency-weighted score (24h half-life). Circles: news-volume spikes.</p></section>
      )}
      {s && (
        <section className="grid gap-6 md:grid-cols-2">
          <div data-tour="leadlag"><h2 className="mb-1 text-lg font-semibold">Does sentiment lead price?</h2><LeadLagChart rows={s.lead_lag} />
            <ul className="mt-2 list-disc pl-5 text-xs text-slate-500">{s.notes.map((n) => <li key={n}>{n}</li>)}</ul></div>
          <div data-tour="top-terms"><h2 className="mb-1 text-lg font-semibold">Top terms</h2>
            <div className="flex flex-wrap gap-1.5">{s.top_terms.map(([w, n]) => <span key={w} className="rounded bg-slate-200 px-2 py-0.5 dark:bg-slate-800" style={{ fontSize: `${11 + Math.min(10, n)}px` }}>{w}</span>)}</div>
            {s.spikes.length > 0 && <><h3 className="mt-3 text-sm font-semibold">News-volume spikes</h3>
              <ul className="text-sm">{s.spikes.slice(-6).map((d) => <li key={d.date}>{d.date}: {d.n_articles} articles (z {d.volume_z?.toFixed(1)})</li>)}</ul></>}</div>
        </section>
      )}
      {sent.error && news.data && news.data.count > 0 && <p className="text-sm text-amber-600">Sentiment series unavailable: {(sent.error as Error).message}</p>}

      {arts.length > 0 && (
        <section data-tour="feed">
          <div className="mb-2 flex items-center gap-3"><h2 className="text-lg font-semibold">Headlines ({arts.length})</h2>
            <span className="ml-auto flex items-center gap-4 text-sm">
              <label data-tour="materiality-filter" className="flex items-center gap-1"><input type="checkbox" checked={matOnly} onChange={(e) => setMatOnly(e.target.checked)} /> high materiality only (AI)</label>
              <label className="flex items-center gap-1"><input type="checkbox" checked={highOnly} onChange={(e) => setHighOnly(e.target.checked)} /> strong sentiment only (|score| ≥ 0.5)</label></span></div>
          <ul className="divide-y divide-slate-200 dark:divide-slate-800">
            {arts.map((a) => (
              <li key={a.id} className="flex gap-3 py-2">
                <span className={`mt-0.5 h-fit shrink-0 rounded px-1.5 py-0.5 text-xs tabular-nums ${chip[a.label]}`} title={`pos ${a.pos} / neg ${a.neg} / neu ${a.neu}`}>{a.score > 0 ? "+" : ""}{a.score.toFixed(2)}</span>
                <div className="min-w-0"><a href={a.url} target="_blank" rel="noopener noreferrer" className="font-medium hover:underline">{a.title}</a>
                  {(() => { const e = emap.get(a.id); return e && e.event_type ? (
                    <p className="mt-0.5 flex flex-wrap items-center gap-1.5 text-xs">
                      <span className="rounded bg-slate-200 px-1.5 py-0.5 dark:bg-slate-800">{e.event_type.replace(/_/g, " ")}</span>
                      {e.materiality && <span className={`rounded px-1.5 py-0.5 ${MAT[e.materiality]}`}>{e.materiality} materiality</span>}
                      {e.horizon && <span className="text-slate-500">{e.horizon}</span>}
                      {e.is_new_information === false && <span className="text-slate-500">rehash</span>}
                      {e.llm_score !== null && <span className={`rounded px-1.5 py-0.5 tabular-nums ${e.llm_label === e.ref_label ? "border border-green-600 text-green-700 dark:text-green-400" : "border border-amber-500 text-amber-600"}`} title={`LLM ${e.llm_model}; ${e.llm_label === e.ref_label ? "agrees" : "disagrees"} with ${enriched.data?.reference_model}`}>LLM {e.llm_score > 0 ? "+" : ""}{e.llm_score.toFixed(2)}</span>}
                      {e.flags.includes("injection_suspected") && <span className="rounded bg-red-600 px-1.5 py-0.5 text-white" title="This article contains text that looks like instructions to an AI. It was treated purely as data.">suspicious text</span>}
                      {!e.valid_for_backtest && <span className="text-slate-400" title="LLM output generated after the fact: not valid for backtesting">not for backtests</span>}
                    </p>) : null; })()}
                  {emap.get(a.id)?.summary && <p className="mt-0.5 text-sm text-slate-700 dark:text-slate-300">{emap.get(a.id)?.summary} <span className="text-[10px] text-violet-600" title={AIBADGE}>AI</span></p>}
                  <p className="text-xs text-slate-500">{a.source || a.provider} · {new Date(a.published * 1000).toLocaleString("en-IN", { timeZone: "Asia/Kolkata" })} IST · {a.tickers.join(", ")}{a.provider_score !== null ? ` · provider score ${a.provider_score.toFixed(2)}` : ""}</p></div>
              </li>
            ))}
          </ul>
        </section>
      )}
      <p className="text-xs text-slate-500">Sentiment is scored automatically and can be wrong, especially on sarcasm, rumours and non-financial wording. Educational tool, not investment advice.</p>
    </div>
  );
}

export default function Page() { return <Suspense fallback={<div className="skeleton h-96" />}><View /></Suspense>; }
