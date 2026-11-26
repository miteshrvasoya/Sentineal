"use client";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
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

function Scheduler() {
  const qc = useQueryClient();
  const st = useQuery({ queryKey: ["sched"], queryFn: api.schedStatus, refetchInterval: 10_000 });
  const run = useMutation({ mutationFn: (job: string) => api.schedRun(job), onSuccess: () => setTimeout(() => qc.invalidateQueries({ queryKey: ["sched"] }), 800) });
  return (
    <section data-tour="scheduler">
      <h2 className="mb-2 text-xl font-semibold">Scheduler</h2>
      {st.data && <p className={`mb-2 text-sm ${st.data.enabled ? "text-green-700 dark:text-green-400" : "text-amber-600"}`}>{st.data.enabled ? "On: jobs run automatically while the backend is running." : "Off. Set SCHEDULER_ENABLED=true in .env and restart to run jobs automatically. You can still run any job by hand below."}</p>}
      <table className="w-full text-sm"><thead className="text-left text-slate-500"><tr><th>Job</th><th>When</th><th>Last run</th><th>Result</th><th></th></tr></thead>
        <tbody>{st.data?.jobs.map((j) => (
          <tr key={j.name} className="border-t border-slate-200 align-top dark:border-slate-800">
            <td className="py-1"><div className="font-medium">{j.title}</div><div className="text-xs text-slate-500">{j.description}</div></td>
            <td className="text-xs">{j.when}{j.enabled ? "" : " (switch on in .env)"}</td>
            <td className="text-xs">{j.running ? "running…" : j.last_run ? ts(j.last_run.started) : "never"}</td>
            <td className={`text-xs ${j.last_run?.status === "failed" ? "text-red-600" : ""}`} title={j.last_run?.error ?? JSON.stringify(j.last_run?.result ?? "")}>{j.last_run ? (j.last_run.status === "failed" ? `failed: ${j.last_run.error}` : `ok, ${j.last_run.duration_s ?? 0}s`) : ""}</td>
            <td><button onClick={() => run.mutate(j.name)} disabled={j.running || run.isPending} className="rounded border border-slate-300 px-2 py-0.5 text-xs disabled:opacity-50 dark:border-slate-700">Run now</button></td></tr>))}</tbody></table>
      {run.error && <p className="text-sm text-red-600" role="alert">{(run.error as Error).message}</p>}
      <p className="mt-1 text-xs text-slate-500">{st.data?.note}</p>
    </section>
  );
}

function SafetyEval() {
  const m = useMutation({ mutationFn: api.safetyEval });
  const d = m.data;
  return (
    <section data-tour="safety-eval">
      <h2 className="mb-2 text-xl font-semibold">AI safety evaluation</h2>
      <p className="mb-2 text-sm text-slate-600 dark:text-slate-400">Fires {12} prompt-injection attacks (on the chat box and on news headlines) and {10} ordinary questions at your configured LLM, and reports what got through. It uses tokens, so it counts against the daily budget. Run it again after changing a model or prompt.</p>
      <button onClick={() => m.mutate()} disabled={m.isPending} className="rounded bg-indigo-600 px-3 py-1 text-sm text-white disabled:opacity-50">{m.isPending ? "Running (can take a minute)…" : "Run the safety evaluation"}</button>
      {m.error && <p className="mt-2 text-sm text-slate-600 dark:text-slate-400" role="alert">{(m.error as Error).message}</p>}
      {d && (
        <div className="mt-3 space-y-2 text-sm">
          <p><b>Injection attacks:</b> {d.injection.safe} of {d.injection.n} safe ({d.injection.blocked_by_guardrail} blocked by a guardrail, {d.injection.resisted_by_model} resisted by the model itself), <b className={d.injection.violations ? "text-red-600" : "text-green-700 dark:text-green-400"}>{d.injection.violations} got through</b>.</p>
          {d.injection.rows.filter((r) => r.result === "VIOLATION").map((r) => <p key={r.id} className="text-xs text-red-600">{r.id} ({r.kind}): {r.violations?.join(", ")}</p>)}
          <p><b>Agent questions:</b> right tool first {d.agent.tool_choice_accuracy === null ? "n/a" : `${Math.round(d.agent.tool_choice_accuracy * 100)}%`}, answered {d.agent.answer_rate === null ? "n/a" : `${Math.round(d.agent.answer_rate * 100)}%`}, withheld by guardrails {d.agent.withheld_rate === null ? "n/a" : `${Math.round(d.agent.withheld_rate * 100)}%`}, cited {d.agent.cited_rate === null ? "n/a" : `${Math.round(d.agent.cited_rate * 100)}%`}.</p>
          {(d.injection.stopped || d.agent.stopped) && <p className="text-xs text-amber-600">Stopped early: {d.injection.stopped ?? d.agent.stopped}</p>}
          <p className="text-xs text-slate-500">{d.injection.note} A small fixed set cannot prove safety; it catches regressions.</p>
        </div>)}
    </section>
  );
}

function OpenRouterPanel() {
  const llm = useQuery({ queryKey: ["llmstatus"], queryFn: api.llmStatus });
  const [check, setCheck] = useState(false);
  const or = useQuery({ queryKey: ["ormodels"], queryFn: api.orModels, enabled: check, retry: false });
  const on = llm.data?.providers?.openrouter;
  return (
    <section data-tour="openrouter">
      <h2 className="mb-2 text-xl font-semibold">AI helper (free with OpenRouter)</h2>
      <p className={`mb-2 text-sm ${on ? "text-green-700 dark:text-green-400" : "text-amber-600"}`}>{on ? "OpenRouter is connected. The AI explanations are switched on." : "Not connected yet. Everything works without AI; it only adds plain-English explanations."}</p>
      {!on && (
        <ol className="mb-2 list-decimal space-y-1 pl-5 text-sm">
          <li>Make a free account at <a className="text-indigo-600 underline dark:text-indigo-300" href="https://openrouter.ai/keys" target="_blank" rel="noreferrer">openrouter.ai/keys</a> and create a key.</li>
          <li>In OpenRouter&apos;s privacy settings, allow free models (they are only available if you allow it).</li>
          <li>Put the key in the <code>.env</code> file as <code>OPENROUTER_API_KEY=your-key</code> and restart the backend.</li>
        </ol>)}
      <p className="text-xs text-slate-500">Free models allow roughly 20 requests a minute and 50 a day, which is plenty for explaining a few stocks. Free providers may keep the text you send (only prices, numbers and news headlines, never your holdings or name). The app tries several free models in order, so if one disappears the next is used.</p>
      <button onClick={() => setCheck(true)} className="mt-2 rounded border border-slate-300 px-3 py-1 text-sm dark:border-slate-700">Which free model is best right now?</button>
      {or.isFetching && <p className="mt-1 text-sm text-slate-500">Checking OpenRouter…</p>}
      {or.data && !or.data.ok && <p className="mt-1 text-sm text-amber-600">{or.data.error} Built-in order: {or.data.defaults?.join(", ")}</p>}
      {or.data?.ok && (
        <div className="mt-2 text-sm">
          {or.data.recommended && <p>Best match for this app: <b>{or.data.recommended}</b>. To use it, add <code>OPENROUTER_MODEL={or.data.recommended}</code> to <code>.env</code>. For a real test with your key, run <code>make openrouter-check</code>.</p>}
          <ol className="mt-1 list-decimal space-y-0.5 pl-5 text-xs">{or.data.ranked.map((m) => <li key={m.id}><b>{m.id}</b> (score {m.score}): {m.reasons.slice(0, 3).join("; ")}</li>)}</ol></div>)}
    </section>
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
      <OpenRouterPanel />
      <Scheduler />
      <SafetyEval />
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
