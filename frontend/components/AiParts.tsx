"use client";
import type { AiBase, Claim } from "@/lib/api";

/** Citation chip: shows the fact id; hover shows the value the AI was given for it. */
export function Evidence({ ids, facts }: { ids: string[]; facts: AiBase["facts"] }) {
  return (
    <span className="ml-1 inline-flex flex-wrap gap-1 align-middle">
      {ids.map((id) => {
        const known = id in facts;
        return <span key={id} title={known ? `${id} = ${String(facts[id])}` : "Article (see list below)"}
          className={`rounded px-1 text-[10px] ${known ? "bg-slate-200 text-slate-700 dark:bg-slate-800 dark:text-slate-300" : "bg-indigo-100 text-indigo-700 dark:bg-indigo-950 dark:text-indigo-300"}`}>{id}</span>;
      })}
    </span>
  );
}

export function ClaimList({ title, items, facts, tone }: { title: string; items: Claim[]; facts: AiBase["facts"]; tone?: "good" | "bad" | "warn" }) {
  if (!items.length) return null;
  const bar = tone === "good" ? "border-green-600" : tone === "bad" ? "border-red-600" : tone === "warn" ? "border-amber-500" : "border-slate-400";
  return (
    <div>
      <h3 className="mb-1 text-sm font-semibold">{title}</h3>
      <ul className="space-y-1.5">{items.map((c, i) => <li key={i} className={`border-l-2 pl-2 text-sm ${bar}`}>{c.text}<Evidence ids={c.evidence} facts={facts} /></li>)}</ul>
    </div>
  );
}

export function FactsDisclosure({ facts, missing }: { facts: AiBase["facts"]; missing: string[] }) {
  const rows = Object.entries(facts);
  return (
    <details className="mt-2 text-xs" data-tour="ai-facts">
      <summary className="cursor-pointer text-slate-500">The facts the AI was given ({rows.length})</summary>
      <p className="my-1 text-slate-500">These numbers were computed by the software. The AI may only talk about them, and every claim above cites the ids below. Anything it says that is not here is rejected.</p>
      {missing.length > 0 && <p className="mb-1 text-amber-600">No data for: {missing.join(", ")}</p>}
      <div className="grid max-h-56 grid-cols-1 gap-x-4 overflow-y-auto sm:grid-cols-2">{rows.map(([k, v]) => <div key={k} className="flex justify-between gap-2 border-b border-slate-100 dark:border-slate-800"><span className="truncate font-mono">{k}</span><span className="tabular-nums">{String(v)}</span></div>)}</div>
    </details>
  );
}

/** Banner for the states where there is nothing to show: no LLM, withheld output, error. Returns null when a report is shown. */
export function AiStatus({ d, report }: { d: AiBase; report: unknown }) {
  if (!d.available) return <p className="rounded border border-dashed border-slate-300 p-2 text-sm text-slate-600 dark:border-slate-700 dark:text-slate-400" role="status">{d.reason}</p>;
  if (d.error) return <p className="rounded border border-amber-500 p-2 text-sm text-amber-700 dark:text-amber-400" role="alert">{d.error}</p>;
  if (d.withheld || !report) return (
    <div className="rounded border border-amber-500 p-2 text-sm text-amber-700 dark:text-amber-400" role="alert">
      The AI answer was withheld because it broke a safety rule even after a retry: {(d.problems ?? []).join("; ") || "unknown problem"}. Nothing unverified is shown. Try again, or read the facts below.</div>);
  return null;
}

export function AiFooter({ d }: { d: AiBase }) {
  if (!d.available) return null;
  return <p className="mt-2 text-[11px] text-slate-500">{d.badge}. {d.model ? `Model ${d.provider}/${d.model}${d.cached ? " (cached)" : ""}${d.repaired ? ", corrected after a safety check" : ""}. ` : ""}Prompt {d.prompt ?? "n/a"}. Not stored as a feature and never used in backtests.</p>;
}
