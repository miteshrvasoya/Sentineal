"use client";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Suspense, useEffect, useState } from "react";
import IdeaCard from "@/components/IdeaCard";
import Term from "@/components/Term";
import { api } from "@/lib/api";

const card = "rounded-lg border border-slate-200 p-4 dark:border-slate-800";
const input = "rounded border border-slate-300 bg-white px-2 py-1 text-sm dark:border-slate-700 dark:bg-slate-900";

function Loader() {
  const qc = useQueryClient();
  const st = useQuery({ queryKey: ["dstatus"], queryFn: api.discoverStatus });
  const [jid, setJid] = useState<string | null>(null);
  const start = useMutation({ mutationFn: api.discoverLoad, onSuccess: (j) => setJid(j.id) });
  const job = useQuery({ queryKey: ["dload", jid], queryFn: () => api.job(jid as string), enabled: !!jid, refetchInterval: (q) => (q.state.data && ["done", "failed"].includes(q.state.data.status) ? false : 1500) });
  const running = !!jid && job.data && !["done", "failed"].includes(job.data.status);
  useEffect(() => {
    if (job.data && ["done", "failed"].includes(job.data.status)) { ["dstatus", "ideas"].forEach((k) => qc.invalidateQueries({ queryKey: [k] })); }
  }, [job.data?.status]); // eslint-disable-line react-hooks/exhaustive-deps
  if (!st.data) return null;
  const s = st.data;
  return (
    <section data-tour="disc-load" className={`${card} ${s.enough_to_compare ? "" : "border-amber-400 bg-amber-50 dark:bg-amber-950/30"}`}>
      <div className="flex flex-wrap items-center gap-3">
        <p className="text-sm">Comparing <b>{s.stored_total}</b> stock{s.stored_total === 1 ? "" : "s"}. {s.loaded}/{s.popular} well-known companies loaded, {s.with_company_numbers} with company financials.</p>
        <button onClick={() => start.mutate()} disabled={!!running || start.isPending} className="ml-auto rounded bg-indigo-600 px-3 py-1 text-sm text-white disabled:opacity-50">
          {running ? `Loading… ${Math.round((job.data?.progress ?? 0) * 100)}%` : s.loaded >= s.popular ? "Refresh these stocks" : "Load more stocks"}</button>
      </div>
      {!s.enough_to_compare && <p className="mt-1 text-sm">{s.hint}</p>}
      {job.data?.status === "done" && <p className="mt-1 text-sm text-green-700 dark:text-green-400">Done. {String((job.data.result as { loaded?: number } | null)?.loaded ?? 0)} stocks loaded.</p>}
      {job.data?.status === "failed" && <p role="alert" className="mt-1 text-sm text-red-600">Loading failed: {job.data.error}. Check your internet connection and try again.</p>}
      {start.error && <p role="alert" className="mt-1 text-sm text-red-600">{(start.error as Error).message}</p>}
      {running && <p className="mt-1 text-xs text-slate-500">This takes a few minutes (it fetches about 5 years of prices and the financial statements for each company). You can keep using the app.</p>}
    </section>
  );
}

function View() {
  const qc = useQueryClient();
  const [horizon, setHorizon] = useState<"short" | "long">("short");
  const [risk, setRisk] = useState("any");
  const [sector, setSector] = useState("");
  const q = useQuery({ queryKey: ["ideas", horizon, risk, sector], queryFn: () => api.ideas(horizon, risk, sector), retry: false });
  const watched = useQuery({ queryKey: ["watchlist"], queryFn: api.watchlist });
  const watch = useMutation({ mutationFn: (s: string) => api.watchAdd(s), onSuccess: () => { qc.invalidateQueries({ queryKey: ["watchlist"] }); qc.invalidateQueries({ queryKey: ["watchsummary"] }); } });
  const tab = (h: "short" | "long", title: string, sub: string) => (
    <button onClick={() => setHorizon(h)} aria-pressed={horizon === h} className={`flex-1 rounded-lg border p-3 text-left ${horizon === h ? "border-indigo-600 bg-indigo-50 dark:bg-indigo-950" : "border-slate-200 dark:border-slate-800"}`}>
      <div className="font-semibold">{title}</div><div className="text-xs text-slate-500">{sub}</div></button>
  );
  return (
    <div className="space-y-4">
      <div><h1 className="text-2xl font-semibold">Find stocks to research</h1>
        <p className="text-sm text-slate-600 dark:text-slate-400">Ideas ranked by simple, visible rules and explained in plain words. They are starting points for your own homework, not advice to buy.</p></div>
      <Loader />
      <div data-tour="disc-horizon" className="flex flex-col gap-2 sm:flex-row">
        {tab("short", "Short term", "A few weeks to a few months. Looks at recent strength and trend. Bumpier and harder to predict.")}
        {tab("long", "Long term", "Several years. Looks at the company itself: profits, debt, growth, price. Needs company financials loaded.")}
      </div>
      <div className="flex flex-wrap items-center gap-3 text-sm">
        <label>Ups and downs I can handle <select value={risk} onChange={(e) => setRisk(e.target.value)} className={input}><option value="any">Any</option><option value="medium">Medium or lower</option><option value="low">Only calmer stocks</option></select></label>
        <label>Industry <select value={sector} onChange={(e) => setSector(e.target.value)} className={input}><option value="">All</option>{q.data?.sectors.map((s) => <option key={s}>{s}</option>)}</select></label>
      </div>
      <section data-tour="disc-ideas" className="space-y-3">
        {q.isLoading && <div className="skeleton h-40" />}
        {q.error && <p className={`${card} text-sm`}>{(q.error as Error).message}</p>}
        {q.data && q.data.ideas.length === 0 && (
          <div className={`${card} text-sm`}><b>Nothing to rank yet.</b>{" "}
            {horizon === "long" ? <>Long-term ideas need each company&apos;s financial numbers. Press <b>Load more stocks</b> above (it fetches them), then come back.{q.data.unranked > 0 && ` ${q.data.unranked} stock(s) were left out because too many of the checks had no data.`}</> : <>No stock has enough price history for this view, or your filters are too narrow.</>}</div>)}
        {q.data?.ideas.map((i) => <IdeaCard key={i.symbol} i={i} onWatch={(s) => watch.mutate(s)} watching={watched.data?.includes(i.symbol)} />)}
        {q.data && q.data.ideas.length > 0 && <p className="text-xs text-slate-500">Ranked {q.data.ideas.length} of {q.data.considered} stocks that qualified out of {q.data.universe} loaded. {q.data.disclaimer}</p>}
      </section>
      <details className={`${card} text-sm`} data-tour="disc-how">
        <summary className="cursor-pointer font-semibold">How to read these ideas</summary>
        <ul className="mt-2 list-disc space-y-1 pl-5">
          <li><b>The label and score</b> come from a checklist you can see: each ✓ is a check the stock passed, each ⚠ is something to look into. Missing data is skipped, never guessed, and the card says how many checks it was based on.</li>
          <li><b>Short term</b> mostly follows <Term k="rank">momentum</Term>: stocks that have been doing better than others tend to keep doing so for a while, until they do not. It is a tilt in the odds, not a prediction.</li>
          <li><b>Long term</b> looks at business quality: profitable, not drowning in <Term k="debt">debt</Term>, growing, and not absurdly expensive (<Term k="pe">P/E</Term>). It cannot see new competition, bad management or changes in the industry.</li>
          <li><b>Ups and downs</b> is how violently the price moves (<Term k="volatility">volatility</Term>). Ask yourself honestly whether you could watch it drop 30% without selling in a panic.</li>
          <li>Warning signs (heavy debt, losses, a deep fall, news problems) lower a stock&apos;s score and are listed under ⚠.</li>
        </ul>
        <p className="mt-2 rounded bg-slate-100 p-2 dark:bg-slate-800"><b>New to this?</b> Many beginners start with a low-cost <Term k="index">index fund</Term> bought through a <Term k="sip">SIP</Term> instead of picking individual stocks, because it spreads risk across many companies automatically. Whether that suits you is your decision; this tool only shows the information.</p>
      </details>
    </div>
  );
}

export default function Page() { return <Suspense fallback={<div className="skeleton h-96" />}><View /></Suspense>; }
