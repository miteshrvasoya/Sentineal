"use client";
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { api, type SubScore } from "@/lib/api";

const tone = (s: number | null) => (s === null ? "bg-slate-300 dark:bg-slate-700" : s >= 25 ? "bg-green-600" : s <= -25 ? "bg-red-600" : "bg-slate-400");
const voteChip = { 1: "bg-green-600 text-white", 0: "bg-slate-300 text-slate-800 dark:bg-slate-700 dark:text-slate-100", "-1": "bg-red-600 text-white" } as const;

/** A -100..+100 bar with the zero point in the middle. */
function Meter({ score }: { score: number | null }) {
  if (score === null) return <div className="h-2 flex-1 rounded bg-slate-200 dark:bg-slate-800" />;
  const w = Math.abs(score) / 2;                          // 0..50 (% of full width)
  return (
    <div className="relative h-2 flex-1 rounded bg-slate-200 dark:bg-slate-800" role="img" aria-label={`score ${score} on a scale from -100 to +100`}>
      <div className="absolute inset-y-0 left-1/2 w-px bg-slate-500" />
      <div className={`absolute inset-y-0 rounded ${tone(score)}`} style={score >= 0 ? { left: "50%", width: `${w}%` } : { right: "50%", width: `${w}%` }} />
    </div>
  );
}

function Row({ k, s }: { k: string; s: SubScore }) {
  const [open, setOpen] = useState(false);
  return (
    <li className="border-b border-slate-200 py-1.5 last:border-0 dark:border-slate-800">
      <button onClick={() => setOpen((o) => !o)} aria-expanded={open} aria-controls={`rules-${k}`} disabled={!s.available}
        className="flex w-full items-center gap-3 text-left text-sm disabled:cursor-default">
        <span className="w-40 shrink-0 font-medium">{s.label}</span>
        <Meter score={s.score} />
        <span className="w-14 text-right tabular-nums">{s.score === null ? "n/a" : s.score > 0 ? `+${s.score}` : s.score}</span>
        <span className="w-4 text-slate-400">{s.available ? (open ? "▾" : "▸") : ""}</span>
      </button>
      {!s.available && <p className="pl-1 text-xs text-slate-500">No data for this part yet, so it is left out of the total instead of being guessed.</p>}
      {open && (
        <ul id={`rules-${k}`} className="mt-2 space-y-1.5 pl-1">
          {s.rules.map((r) => (
            <li key={r.id} className="flex gap-2 text-xs">
              <span className={`mt-0.5 h-fit w-6 shrink-0 rounded text-center font-mono ${voteChip[String(r.vote) as keyof typeof voteChip]}`}>{r.vote > 0 ? "+1" : r.vote}</span>
              <span><b>{r.rule}</b>{r.value !== null && <span className="tabular-nums text-slate-500"> (value {typeof r.value === "number" ? r.value.toFixed(2) : r.value})</span>}
                <br /><span className="text-slate-500">{r.why}</span></span>
            </li>
          ))}
        </ul>
      )}
    </li>
  );
}

export default function ScorecardPanel({ symbol }: { symbol: string }) {
  const q = useQuery({ queryKey: ["scorecard", symbol], queryFn: () => api.scorecard(symbol), retry: false });
  return (
    <section data-tour="scorecard" className="rounded border border-slate-200 p-3 dark:border-slate-800" aria-label="Signal scorecard">
      <div className="mb-2 flex flex-wrap items-center gap-3">
        <h2 className="text-lg font-semibold">Signal scorecard</h2>
        {q.data?.composite !== undefined && q.data.composite !== null && (
          <span className={`rounded px-2 py-0.5 text-sm text-white ${tone(q.data.composite)}`}>{q.data.label} ({q.data.composite > 0 ? "+" : ""}{q.data.composite})</span>
        )}
        <span className="text-xs text-slate-500">transparent rules, click a row to see exactly why</span>
      </div>
      {q.isLoading && <div className="skeleton h-32" />}
      {q.error && <p className="text-sm text-slate-500">Scorecard unavailable: {(q.error as Error).message}</p>}
      {q.data && (
        <>
          <ul>{Object.entries(q.data.subscores).map(([k, s]) => <Row key={k} k={k} s={s} />)}</ul>
          <p className="mt-2 text-xs text-slate-500">{q.data.disclaimer} Volatility is a risk gauge (calmer scores higher), not a direction signal. As of {q.data.as_of}.</p>
        </>
      )}
    </section>
  );
}
