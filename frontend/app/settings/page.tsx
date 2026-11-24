"use client";
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { api, type LlmUsage } from "@/lib/api";

const ts = (t: number | null) => (t ? new Date(t * 1000).toLocaleString("en-IN", { timeZone: "Asia/Kolkata" }) : "never");
const sev = { error: "text-red-600", warn: "text-amber-600", info: "text-slate-500" } as const;

function Bar({ v, max, label }: { v: number; max: number; label: string }) {
  const pct = Math.min(100, max > 0 ? (v / max) * 100 : 0);
  return (
    <div className="text-sm">
      <div className="flex justify-between"><span>{label}</span><span className="tabular-nums text-slate-500">{pct.toFixed(0)}%</span></div>
      <div className="h-2 rounded bg-slate-200 dark:bg-slate-800">
        <div className={`h-2 rounded ${pct >= 100 ? "bg-red-600" : pct > 80 ? "bg-amber-500" : "bg-indigo-600"}`} style={{ width: `${pct}%` }} />
      </div>
    </div>
  );
}

function UsageChart({ rows }: { rows: LlmUsage["rows"] }) {
  const byDay = new Map<string, number>();
  rows.forEach((r) => byDay.set(r.day, (byDay.get(r.day) ?? 0) + r.tokens_in + r.tokens_out));
  const days = Array.from(byDay.entries()).sort(([a], [b]) => (a < b ? -1 : 1)).slice(-14);
  const max = Math.max(1, ...days.map(([, v]) => v));
  if (days.length === 0) return <p className="text-sm text-slate-500">No LLM calls yet.</p>;
  return (
    <svg width={days.length * 40} height={110} viewBox={`0 0 ${days.length * 40} 110`} role="img" aria-label="LLM tokens per day">
      {days.map(([d, v], i) => (
        <g key={d}>
          <rect x={i * 40 + 6} width={28} y={90 - (v / max) * 80} height={(v / max) * 80} fill="#6366f1"><title>{`${d}: ${v.toLocaleString()} tokens`}</title></rect>
          <text x={i * 40 + 20} y={104} fontSize="8" textAnchor="middle" fill="currentColor">{d.slice(5)}</text>
        </g>
      ))}
    </svg>
  );
}

export default function Settings() {
  const llm = useQuery({ queryKey: ["llmstatus"], queryFn: api.llmStatus, refetchInterval: 20_000 });
  const usage = useQuery({ queryKey: ["llmusage"], queryFn: api.llmUsage, refetchInterval: 20_000 });
  const prov = useQuery({ queryKey: ["providers"], queryFn: api.providers, refetchInterval: 15_000 });
  const [sym, setSym] = useState("RELIANCE");
  const [go, setGo] = useState("RELIANCE");
  const dq = useQuery({ queryKey: ["dq", go], queryFn: () => api.quality(go) });
  return (
    <div className="space-y-8">
      <section data-tour="providers">
        <h1 className="mb-2 text-xl font-semibold">Providers</h1>
        {prov.error && <p role="alert" className="text-sm text-red-500">{(prov.error as Error).message}</p>}
        <table className="w-full text-sm">
          <thead className="text-left text-slate-500"><tr><th>Name</th><th>Status</th><th>Rate limit</th><th>Calls today</th><th>Last success</th><th>Last error</th></tr></thead>
          <tbody>{prov.data?.map((p) => (
            <tr key={p.name} className="border-t border-slate-200 dark:border-slate-800">
              <td className="py-1 font-medium">{p.name}</td>
              <td>{p.configured ? "configured" : "no credentials"}</td><td>{p.rate_limit}</td><td>{p.calls_today}</td>
              <td>{ts(p.last_success)}</td><td title={p.last_error_msg}>{ts(p.last_error)}</td>
            </tr>))}</tbody>
        </table>
        <p className="mt-2 text-xs text-slate-500">API keys are never displayed. Set them in <code>.env</code>.</p>
      </section>
      <section data-tour="llm-panel">
        <div className="mb-2 flex items-center gap-3">
          <h1 className="text-xl font-semibold">LLM (AI analysis)</h1>
          {llm.data && (
            <span className={`rounded px-2 py-0.5 text-xs text-white ${llm.data.available ? "bg-green-600" : "bg-slate-500"}`}>
              {llm.data.available ? "available" : "LLM unavailable: no key configured"}
            </span>
          )}
        </div>
        {llm.error && <p role="alert" className="text-sm text-red-500">{(llm.error as Error).message}</p>}
        {llm.data && (
          <div className="space-y-4">
            <p className="text-xs text-slate-500">{llm.data.badge}. The app works fully without any LLM; AI panels simply show as unavailable.</p>
            <div className="flex flex-wrap gap-2 text-sm">
              {Object.entries(llm.data.providers).map(([n, ok]) => (
                <span key={n} className={`rounded border px-2 py-0.5 ${ok ? "border-green-600 text-green-700 dark:text-green-400" : "border-slate-300 text-slate-500 dark:border-slate-700"}`}>{n}: {ok ? "key set" : "no key"}</span>
              ))}
            </div>
            <div className="grid max-w-xl gap-2" data-tour="llm-budget">
              <Bar v={llm.data.budget.tokens} max={llm.data.budget.token_budget} label={`Today's tokens: ${llm.data.budget.tokens.toLocaleString()} of ${llm.data.budget.token_budget.toLocaleString()}`} />
              <Bar v={llm.data.budget.usd} max={llm.data.budget.usd_budget} label={`Today's estimated spend: $${llm.data.budget.usd.toFixed(4)} of $${llm.data.budget.usd_budget.toFixed(2)}`} />
              {llm.data.budget.exhausted && (
                <p role="alert" className="text-sm text-red-600">Daily budget reached: LLM calls are stopped until tomorrow (IST). Raise LLM_DAILY_TOKEN_BUDGET or LLM_DAILY_USD_BUDGET in .env to change this.</p>
              )}
              <p className="text-xs text-slate-500">Spend is an estimate from the prices in config/llm.yaml, not your provider invoice.</p>
            </div>
            <div className="overflow-x-auto" data-tour="llm-routing">
              <table className="w-full text-sm">
                <thead className="text-left text-slate-500"><tr><th>Task</th><th>Routing (first configured provider wins, then falls back)</th></tr></thead>
                <tbody>
                  {Object.entries(llm.data.tasks).map(([t, c]) => (
                    <tr key={t} className="border-t border-slate-200 align-top dark:border-slate-800">
                      <td className="py-1 font-medium">{t}</td>
                      <td>
                        {c.chain.map((e) => (
                          <span key={e.provider + e.model} className={`mr-2 inline-block ${e.configured ? "" : "text-slate-400 line-through"}`}>{e.provider}/{e.model}</span>
                        ))}
                        <span className="text-xs text-slate-500">temp {c.temperature}, max {c.max_tokens} tokens</span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <p className="mt-1 text-xs text-slate-500">Edit config/llm.yaml to route tasks to other models: a cheap or free model for bulk extraction, a stronger one for reasoning.</p>
            </div>
            <div>
              <h2 className="mb-1 text-sm font-semibold">Tokens per day</h2>
              {usage.data && <UsageChart rows={usage.data.rows} />}
            </div>
          </div>
        )}
      </section>
      <section data-tour="data-quality">
        <h1 className="mb-2 text-xl font-semibold">Data quality</h1>
        <form className="mb-3 flex gap-2" onSubmit={(e) => { e.preventDefault(); setGo(sym.trim().toUpperCase()); }}>
          <input value={sym} onChange={(e) => setSym(e.target.value)} aria-label="Symbol" className="rounded border border-slate-300 bg-white px-2 py-1 text-sm dark:border-slate-700 dark:bg-slate-900" />
          <button className="rounded bg-indigo-600 px-3 py-1 text-sm text-white">Check</button>
        </form>
        {dq.isLoading && <div className="skeleton h-24" />}
        {dq.error && <p role="alert" className="text-sm text-red-500">{(dq.error as Error).message}</p>}
        {dq.data && (
          <div className="space-y-2 text-sm">
            <p>{dq.data.bars} bars · {dq.data.first?.slice(0, 10)} → {dq.data.last?.slice(0, 10)} · sources: {dq.data.sources?.join(", ") || "n/a"}</p>
            <p className="text-slate-500">{Object.entries(dq.data.checks).map(([k, v]) => `${k}: ${v}`).join(" · ")}</p>
            {dq.data.issues.length === 0 && <p className="text-green-600">No issues found.</p>}
            <ul className="space-y-1">{dq.data.issues.map((i, n) => (
              <li key={n} className={sev[i.severity]}><b>{i.kind}</b>: {i.detail}{i.dates && <span className="text-slate-500"> ({i.dates.slice(0, 8).join(", ")}{i.dates.length > 8 ? "…" : ""})</span>}</li>))}</ul>
          </div>
        )}
      </section>
    </div>
  );
}
