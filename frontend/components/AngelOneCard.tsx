"use client";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { api } from "@/lib/api";
import { today } from "@/lib/format";

const ago = (t: number | null) => {
  if (!t) return "never";
  const m = Math.round((Date.now() / 1000 - t) / 60);
  return m < 1 ? "just now" : m < 60 ? `${m} min ago` : m < 1440 ? `${Math.round(m / 60)} h ago` : `${Math.round(m / 1440)} days ago`;
};

/** Connect Angel One (read-only), import holdings, and save imported holdings into your own records with a purchase date. */
export default function AngelOneCard({ onlyCount = 0, compact = false }: { onlyCount?: number; compact?: boolean }) {
  const qc = useQueryClient();
  const st = useQuery({ queryKey: ["broker"], queryFn: api.brokerStatus, retry: false });
  const [date, setDate] = useState(today());
  const refreshAll = () => ["broker", "portfolio", "pfhist", "pftx", "watchsummary", "dstatus", "holdreview", "ideas"].forEach((k) => qc.invalidateQueries({ queryKey: [k] }));
  const sync = useMutation({ mutationFn: api.brokerSync, onSuccess: refreshAll });
  const adopt = useMutation({ mutationFn: () => api.brokerAdopt(date), onSuccess: refreshAll });
  const d = st.data;
  const r = sync.data;
  return (
    <section data-tour="angel-card" className="rounded-lg border border-slate-200 p-4 dark:border-slate-800">
      <div className="flex flex-wrap items-center gap-2">
        <h2 className={compact ? "text-base font-semibold" : "text-xl font-semibold"}>Angel One</h2>
        <span className="rounded bg-slate-200 px-1.5 py-0.5 text-[10px] dark:bg-slate-700">read-only: can never place orders</span>
        {d && <span className={`text-sm ${d.configured ? "text-green-700 dark:text-green-400" : "text-amber-600"}`}>{d.configured ? "Connected" : "Not connected yet"}</span>}
        {d?.configured && <span className="text-xs text-slate-500">{d.holdings} holdings, last synced {ago(d.last_sync)}</span>}
        <button onClick={() => sync.mutate()} disabled={sync.isPending} className="ml-auto rounded bg-indigo-600 px-3 py-1 text-sm text-white disabled:opacity-50">{sync.isPending ? "Syncing…" : "Sync my holdings"}</button>
      </div>
      {st.error && <p className="mt-1 text-sm text-slate-500">{(st.error as Error).message}</p>}
      {d && !d.configured && (
        <details className="mt-2 text-sm" open={!compact}><summary className="cursor-pointer text-slate-600 dark:text-slate-400">How to connect (about 10 minutes, one time)</summary>
          <ol className="mt-1 list-decimal space-y-1 pl-5">{d.steps.map((x) => <li key={x}>{x}</li>)}</ol>
          {d.missing.length > 0 && <p className="mt-1 text-xs text-amber-600">Still missing in .env: {d.missing.join(", ")}</p>}
          <p className="mt-1 text-xs text-slate-500">Your credentials stay in the .env file on your computer. Once connected, Angel One also becomes the first source for prices, with Yahoo Finance as the backup.</p></details>)}
      {r && !r.ok && <p role="alert" className="mt-2 text-sm text-red-600">{r.message}</p>}
      {r?.ok && (
        <p role="status" className="mt-2 text-sm text-green-700 dark:text-green-400">Imported {r.count} holdings.
          {r.added && r.added.length > 0 && ` New: ${r.added.join(", ")}.`}{r.removed && r.removed.length > 0 && ` No longer held: ${r.removed.join(", ")}.`}{r.changed && r.changed.length > 0 && ` Changed: ${r.changed.join(", ")}.`}
          {r.data && (r.data.price_problems.length > 0) && <span className="text-amber-600"> Could not fetch prices for {r.data.price_problems.join(", ")}.</span>}</p>)}
      {onlyCount > 0 && (
        <div className="mt-3 rounded border border-sky-300 bg-sky-50 p-3 text-sm dark:border-sky-800 dark:bg-sky-950/40">
          <p><b>{onlyCount} holding{onlyCount > 1 ? "s" : ""}</b> came from Angel One without a purchase date, so {onlyCount > 1 ? "they are" : "it is"} left out of your yearly return and the growth chart. If you know roughly when you bought, save {onlyCount > 1 ? "them" : "it"} in your own records:</p>
          <div className="mt-2 flex flex-wrap items-center gap-2"><label>Approximate purchase date <input type="date" max={today()} value={date} onChange={(e) => setDate(e.target.value)} className="ml-1 rounded border border-slate-300 bg-white px-2 py-0.5 dark:border-slate-700 dark:bg-slate-900" /></label>
            <button onClick={() => adopt.mutate()} disabled={adopt.isPending} className="rounded border border-slate-400 px-3 py-1 dark:border-slate-600">Save in my records</button></div>
          {adopt.error && <p role="alert" className="mt-1 text-red-600">{(adopt.error as Error).message}</p>}
          {adopt.data && <p className="mt-1 text-green-700 dark:text-green-400">Saved {adopt.data.added} purchases. You can edit them under &quot;Everything you have entered&quot;.</p>}</div>)}
    </section>
  );
}
