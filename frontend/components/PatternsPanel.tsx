"use client";
import { useState } from "react";
import type { Patterns } from "@/lib/api";

const badge = (v?: string) =>
  v?.startsWith("edge") ? "bg-green-600 text-white" : v === "insufficient sample" ? "bg-amber-500 text-white" : "bg-slate-300 text-slate-800 dark:bg-slate-700 dark:text-slate-100";

export default function PatternsPanel({ p }: { p: Patterns }) {
  const [h, setH] = useState("5d");
  return (
    <section className="space-y-2">
      <div className="flex items-center gap-2">
        <h2 className="text-lg font-semibold">Candlestick patterns: does this stock show an edge?</h2>
        <span className="ml-auto text-xs text-slate-500">forward horizon</span>
        {["1d", "5d", "10d"].map((x) => (
          <button key={x} onClick={() => setH(x)} className={`rounded px-2 py-0.5 text-xs ${x === h ? "bg-indigo-600 text-white" : "bg-slate-200 dark:bg-slate-800"}`}>{x}</button>
        ))}
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-sm tabular-nums">
          <thead className="text-left text-slate-500"><tr><th>Pattern</th><th>Bias</th><th>Seen</th><th>n ({h})</th><th>Hit rate</th><th>Base rate</th><th>Avg dir. return</th><th>p (corrected)</th><th>Verdict</th></tr></thead>
          <tbody>
            {p.stats.map((r) => {
              const x = r.horizons[h];
              return (
                <tr key={r.pattern} className="border-t border-slate-200 dark:border-slate-800">
                  <td className="py-1">{r.pattern.replace(/_/g, " ")}</td><td>{r.direction}</td><td>{r.occurrences}</td><td>{x?.n ?? 0}</td>
                  <td>{x?.hit_rate !== undefined ? `${(x.hit_rate * 100).toFixed(0)}%` : "–"}</td>
                  <td>{x?.baseline_hit_rate !== undefined ? `${(x.baseline_hit_rate * 100).toFixed(0)}%` : "–"}</td>
                  <td>{x?.avg_dir_return_pct !== undefined ? `${x.avg_dir_return_pct.toFixed(2)}%` : x?.avg_return_pct !== undefined ? `${x.avg_return_pct.toFixed(2)}% (raw)` : "–"}</td>
                  <td>{x?.p_value_bonferroni ?? "–"}</td>
                  <td>{x?.verdict ? <span className={`rounded px-1.5 py-0.5 text-xs ${badge(x.verdict)}`}>{x.verdict}</span> : <span className="text-xs text-slate-500">neutral pattern</span>}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <ul className="list-disc pl-5 text-xs text-slate-500">{p.notes.map((n) => <li key={n}>{n}</li>)}</ul>
    </section>
  );
}
