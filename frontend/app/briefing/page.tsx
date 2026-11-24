"use client";
import { useMutation, useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { Suspense } from "react";
import { AiFooter, AiStatus, ClaimList, FactsDisclosure } from "@/components/AiParts";
import { api } from "@/lib/api";

const card = "rounded border border-slate-200 p-3 dark:border-slate-800";

function View() {
  const latest = useQuery({ queryKey: ["briefing-latest"], queryFn: api.briefingLatest });
  const flags = useQuery({ queryKey: ["redflags-all"], queryFn: api.redFlagsAll });
  const gen = useMutation({ mutationFn: api.briefing });
  const d = gen.data ?? (latest.data?.available ? latest.data : null);
  const r = d?.report;
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-3"><h1 className="text-2xl font-semibold">Daily briefing</h1>
        <span className="rounded bg-violet-600 px-2 py-0.5 text-xs text-white">AI-generated from computed facts</span>
        <button onClick={() => gen.mutate()} disabled={gen.isPending} className="ml-auto rounded bg-indigo-600 px-3 py-1 text-sm text-white disabled:opacity-50" data-tour="brief-generate">{gen.isPending ? "Writing…" : "Write today's briefing"}</button></div>
      <section className={card} data-tour="brief-body">
        {gen.error && <p className="text-sm text-red-600" role="alert">{(gen.error as Error).message}</p>}
        {!d && !gen.isPending && <p className="text-sm text-slate-500">No briefing yet. Press the button, or switch on the scheduler (Data health page) to have one written after each market close. {latest.data && !latest.data.available ? "" : ""}</p>}
        {d && <AiStatus d={d} report={r} />}
        {r && d && (
          <div className="space-y-3">
            <div><p className="font-semibold">{r.headline}</p><p className="mt-1 text-sm">{r.market_summary}</p>{d.asof && <p className="mt-1 text-xs text-slate-500">Data as of {d.asof}.</p>}</div>
            <ClaimList title="Movers" items={r.movers} facts={d.facts} />
            <ClaimList title="Worth a look" items={r.watch_items} facts={d.facts} tone="warn" />
            <ClaimList title="Red flags" items={r.red_flags} facts={d.facts} tone="bad" />
            {r.data_notes.length > 0 && <ul className="list-disc pl-5 text-xs text-slate-500">{r.data_notes.map((n) => <li key={n}>{n}</li>)}</ul>}
          </div>)}
        {d && <FactsDisclosure facts={d.facts} missing={d.missing} />}
        {d && <AiFooter d={d} />}
      </section>
      <section className={card} data-tour="brief-flags">
        <h2 className="text-lg font-semibold">Red flags across the watchlist</h2>
        <p className="mb-1 text-xs text-slate-500">Rule-based, no AI needed. Click a stock for the details and the numbers behind each flag.</p>
        {flags.data && flags.data.length === 0 && <p className="text-sm text-slate-500">Watchlist is empty.</p>}
        <table className="w-full text-sm"><thead className="text-left text-xs text-slate-500"><tr><th>Stock</th><th>High</th><th>Medium</th><th>Most severe</th></tr></thead>
          <tbody>{flags.data?.map((f) => (
            <tr key={f.symbol} className="border-t border-slate-200 dark:border-slate-800"><td className="py-1"><Link href={`/s/${f.symbol}/analyst`} className="font-medium text-indigo-600 hover:underline dark:text-indigo-300">{f.symbol}</Link></td>
              <td className={f.high ? "font-semibold text-red-600" : "text-slate-400"}>{f.high}</td><td className={f.medium ? "text-amber-600" : "text-slate-400"}>{f.medium}</td><td className="text-xs">{f.top ?? ""}</td></tr>))}</tbody></table>
      </section>
      <p className="text-xs text-slate-500">Educational tool, not investment advice.</p>
    </div>
  );
}

export default function Page() { return <Suspense fallback={<div className="skeleton h-96" />}><View /></Suspense>; }
