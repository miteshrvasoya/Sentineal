"use client";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useParams } from "next/navigation";
import { Fragment, Suspense, useEffect, useState } from "react";
import { AiFooter, AiStatus, ClaimList } from "@/components/AiParts";
import { BarList, CalibrationChart, ConeChart, FanChart, PdpChart, ProbBar, PushBars, RegimeStrip } from "@/components/ModelCharts";
import SvgLine from "@/components/SvgLine";
import SymbolTabs from "@/components/SymbolTabs";
import { api, type ConsensusRow, type EvalDetail, type ModelViewT, type SeasonRow } from "@/lib/api";
import { pct } from "@/lib/explain";

const card = "rounded border border-slate-200 p-3 dark:border-slate-800";
const DEFAULT_MODELS = ["arima", "garch", "mc_bootstrap", "hmm_regime"];
const HORIZON_LABEL: Record<number, string> = { 1: "1 day", 5: "1 week (5d)", 10: "2 weeks (10d)", 21: "1 month (21d)", 42: "2 months", 63: "3 months" };

function Verdict({ v, why }: { v: string | null; why?: string | null }) {
  if (!v) return <span className="text-xs text-slate-400">not evaluated</span>;
  const cls = v === "demonstrated edge" ? "bg-green-600 text-white" : v === "baseline" ? "bg-slate-500 text-white" : v === "insufficient sample" ? "bg-amber-500 text-white" : "bg-slate-300 text-slate-800 dark:bg-slate-700 dark:text-slate-100";
  return <span title={why ?? ""} className={`inline-block rounded px-1.5 py-0.5 text-xs ${cls}`}>{v}</span>;
}

const sgn = (v: number | null | undefined, d = 1) => (v === null || v === undefined ? "n/a" : `${v >= 0 ? "+" : ""}${(v * 100).toFixed(d)}%`);

function SeasonTable({ title, rows, p }: { title: string; rows: SeasonRow[]; p: number | null }) {
  const max = Math.max(0.0001, ...rows.map((r) => Math.abs(r.mean_pct ?? 0)));
  return (
    <div>
      <h4 className="mb-1 text-sm font-semibold">{title} <span className="font-normal text-slate-500">(groups differ at all? p = {p === null ? "n/a" : p.toFixed(3)})</span></h4>
      <table className="w-full text-xs tabular-nums"><tbody>{rows.map((r) => (
        <tr key={r.group} className="border-t border-slate-200 dark:border-slate-800">
          <td className="w-10 py-0.5">{r.group}</td>
          <td className="w-1/2"><div className="relative h-3"><div className="absolute inset-y-0 left-1/2 w-px bg-slate-400" />
            <div className={`absolute inset-y-0.5 ${(r.mean_pct ?? 0) >= 0 ? "bg-green-500" : "bg-red-500"} ${r.significant ? "" : "opacity-40"}`}
              style={(r.mean_pct ?? 0) >= 0 ? { left: "50%", width: `${(Math.abs(r.mean_pct ?? 0) / max) * 50}%` } : { right: "50%", width: `${(Math.abs(r.mean_pct ?? 0) / max) * 50}%` }} /></div></td>
          <td className="w-16 text-right">{r.mean_pct === null ? "n/a" : `${r.mean_pct.toFixed(3)}%`}</td>
          <td className="w-24 text-right text-slate-500">{r.p_bonferroni === null ? "" : `p(adj) ${r.p_bonferroni.toFixed(2)}`}</td>
          <td className="w-6 text-right">{r.significant ? "★" : ""}</td></tr>))}</tbody></table>
    </div>
  );
}

function Detail({ d }: { d: EvalDetail }) {
  const roll = d.rolling_accuracy, cum = d.cum_skill;
  return (
    <div className="grid gap-4 bg-slate-50 p-3 text-sm dark:bg-slate-900 md:grid-cols-3">
      <div data-tour="calibration">
        <h4 className="font-semibold">Calibration</h4>
        <CalibrationChart rows={d.calibration_up.rows} />
        <p className="text-xs text-slate-500">When the model said P(up) = x, how often was it up? On the dashed diagonal = honest probabilities. Average gap (ECE) {d.calibration_up.ece === null ? "n/a" : d.calibration_up.ece.toFixed(3)}.</p>
      </div>
      <div>
        <h4 className="font-semibold">Cumulative skill vs baseline</h4>
        {cum ? <SvgLine dates={cum.map((c) => c.date)} values={cum.map((c) => c.v)} color="#16a34a" height={120} label="Cumulative Brier advantage over the base-rate baseline" /> : <p className="text-xs text-slate-500">Baselines have no comparison line.</p>}
        <p className="text-xs text-slate-500">Rising = beating the baseline over time. Flat or falling = no skill, or skill that has decayed.</p>
        <h4 className="mt-2 font-semibold">Rolling accuracy</h4>
        <SvgLine dates={roll.map((c) => c.date)} values={roll.map((c) => c.v)} color="#6366f1" height={100} zero={false} fmt={(v) => `${(v * 100).toFixed(0)}%`} label="Rolling 3-class accuracy" />
      </div>
      <div>
        <h4 className="font-semibold">What it got right</h4>
        <table className="w-full text-xs tabular-nums"><thead><tr className="text-slate-500"><th className="text-left">actual \ called</th>{d.confusion.classes.map((c) => <th key={c}>{c}</th>)}</tr></thead>
          <tbody>{d.confusion.matrix.map((row, i) => <tr key={i}><td className="py-0.5">{d.confusion.classes[i]}</td>{row.map((v, j) => <td key={j} className={`text-center ${i === j ? "font-semibold" : ""}`}>{v}</td>)}</tr>)}</tbody></table>
        <ul className="mt-2 space-y-0.5 text-xs text-slate-600 dark:text-slate-400">
          <li>3-way accuracy {pct(d.confusion.accuracy3, 0)}; up/down hit rate {pct(d.directional.hit_rate, 0)} on {d.directional.n} calls (naive {pct(d.directional.naive_rate, 0)}).</li>
          <li>Brier {d.brier.toFixed(3)}{d.brier_skill !== undefined ? `, skill ${sgn(d.brier_skill)} vs baseline` : ""}; rank IC {d.rank_ic.ic === null ? "n/a" : d.rank_ic.ic.toFixed(2)}.</li>
          <li>90% range contained the outcome {pct(d.pinball.coverage_90, 0)} of the time (should be about 90%). MASE {d.point.mase === null ? "n/a" : d.point.mase.toFixed(3)} (below 1 beats &quot;no change&quot;).</li>
          {(d.failures ?? 0) > 0 && <li className="text-amber-600">{d.failures} forecast(s) failed or were implausible and were left out ({pct(d.failure_rate, 0)}). Above 5% a model cannot earn an edge verdict.</li>}
          <li>{d.verdict_reason}</li>
        </ul>
      </div>
    </div>
  );
}

function ModelRow({ r, v, baseline, open, toggle, exp }: { r: ConsensusRow; v?: ModelViewT; baseline?: boolean; open: boolean; toggle: () => void; exp: boolean }) {
  return (
    <>
      <tr className="cursor-pointer border-t border-slate-200 align-middle hover:bg-slate-50 dark:border-slate-800 dark:hover:bg-slate-900" onClick={toggle}>
        <td className="py-1.5 pr-2"><span className="font-medium">{r.name}</span>{exp && <span className="ml-1 rounded bg-violet-600 px-1 text-[10px] text-white">experimental</span>}
          {baseline && <span className="ml-1 text-[10px] text-slate-500">baseline</span>}
          {r.name === "ensemble" && <span className="ml-1 rounded bg-indigo-600 px-1 text-[10px] text-white">weighted blend</span>}</td>
        <td className="w-56 pr-3"><ProbBar up={r.p_up} flat={r.p_flat} down={r.p_down} /></td>
        <td className="pr-2 text-center"><span className={r.vote === "up" ? "text-up" : r.vote === "down" ? "text-down" : "text-slate-500"}>{r.vote}</span></td>
        <td className="pr-2 text-xs tabular-nums text-slate-600 dark:text-slate-400">{v ? `${sgn(v.quantiles["5"])} to ${sgn(v.quantiles["95"])}` : ""}</td>
        <td className="pr-2 text-xs tabular-nums">{r.hit_rate === null ? "n/a" : `${(r.hit_rate * 100).toFixed(0)}% vs ${r.naive_rate === null ? "?" : (r.naive_rate * 100).toFixed(0)}%`}</td>
        <td className="pr-2 text-xs tabular-nums">{r.brier_skill === null ? "" : sgn(r.brier_skill)}</td>
        <td><Verdict v={r.verdict} why={r.verdict_reason} /></td>
        <td className="pl-1 text-slate-400">{open ? "▾" : "▸"}</td>
      </tr>
      {open && v && (
        <tr><td colSpan={8} className="bg-slate-50 px-3 py-2 text-xs dark:bg-slate-900">
          <p className="mb-1 text-slate-600 dark:text-slate-400">{v.drivers.length ? "Key inputs: " : ""}{v.drivers.map((d) => `${d.name} = ${d.value}`).join(" · ")}</p>
          {v.notes.map((n) => <p key={n} className="text-slate-500">{n}</p>)}
          <p className="text-slate-500">Trained on {v.training_window.n} daily bars ({v.training_window.start} to {v.training_window.end}); version {v.version}; horizon {v.horizon} days; &quot;flat&quot; means a move under {(v.flat_band * 100).toFixed(2)}%.</p>
        </td></tr>
      )}
    </>
  );
}

function AblationPanel({ symbol, horizon }: { symbol: string; horizon: number }) {
  const q = useQuery({ queryKey: ["ablation", symbol, horizon], queryFn: () => api.ablation(symbol, horizon), retry: false });
  return (
    <section className={card} data-tour="ablation">
      <h2 className="text-lg font-semibold">Does news add anything to price? (ablation)</h2>
      {q.error && <p className="text-sm text-slate-500">Not run yet. Pick <b>lgbm</b>, <b>lgbm_sentiment</b> and <b>lgbm_combined</b> together with the walk-forward test (needs stored news for this stock). The three differ only in their inputs: price only, news only, price + news. <span className="text-xs">({(q.error as Error).message})</span></p>}
      {q.data && (
        <>
          <p className="mb-2 text-sm font-medium">{q.data.reading}</p>
          <table className="w-full text-sm tabular-nums"><thead className="text-left text-xs text-slate-500"><tr><th>Inputs</th><th>Model</th><th>Brier</th><th>Skill vs baseline</th><th>Verdict</th><th>Forecasts</th></tr></thead>
            <tbody>{q.data.rows.map((r) => <tr key={r.model} className="border-t border-slate-200 dark:border-slate-800"><td className="py-1">{r.label}</td><td>{r.model}</td><td>{r.brier.toFixed(4)}</td>
              <td>{r.brier_skill === null ? "" : sgn(r.brier_skill)}</td><td><Verdict v={r.verdict} /></td><td>{r.n_effective.toFixed(0)}{r.failures ? ` (${r.failures} failed)` : ""}</td></tr>)}</tbody></table>
          <p className="mt-2 text-xs text-slate-600 dark:text-slate-400">Paired test, price + news vs price only, on {q.data.paired.n} shared forecasts: average Brier gain {q.data.paired.brier_gain === null ? "n/a" : q.data.paired.brier_gain.toFixed(4)}, p = {q.data.paired.dm_p === null ? "n/a" : q.data.paired.dm_p.toFixed(3)}. News coverage: {q.data.news_coverage.days_with_news} days with articles over a {q.data.news_coverage.days_span}-day span.</p>
          <ul className="mt-1 list-disc pl-5 text-xs text-slate-500">{q.data.notes.map((n) => <li key={n}>{n}</li>)}</ul>
        </>
      )}
    </section>
  );
}

function ExplainModel({ symbol, horizon, model }: { symbol: string; horizon: number; model: string }) {
  const m = useMutation({ mutationFn: () => api.aiExplainModel(symbol, model, horizon) });
  const d = m.data, r = d?.report;
  return (
    <div className="mt-3 rounded border border-dashed border-slate-300 p-2 dark:border-slate-700" data-tour="ai-explain-model">
      <div className="flex flex-wrap items-center gap-2"><h3 className="text-sm font-semibold">Explain this model in words</h3>
        <span className="rounded bg-violet-600 px-1.5 py-0.5 text-[10px] text-white">AI-generated</span>
        <button onClick={() => m.mutate()} disabled={m.isPending} className="ml-auto rounded bg-indigo-600 px-2 py-0.5 text-xs text-white disabled:opacity-50">{m.isPending ? "Writing…" : "Explain"}</button></div>
      {m.error && <p className="text-sm text-red-600" role="alert">{(m.error as Error).message}</p>}
      {d && <div className="mt-1"><AiStatus d={d} report={r} /></div>}
      {r && d && <div className="mt-1 space-y-2 text-sm"><p className="font-medium">{r.verdict_in_words}</p><p>{r.plain_summary}</p>
        <ClaimList title="What it leaned on" items={r.drivers} facts={d.facts} /><ClaimList title="Cautions" items={r.cautions} facts={d.facts} tone="warn" /></div>}
      {d && <AiFooter d={d} />}
    </div>
  );
}

function View() {
  const symbol = decodeURIComponent(String(useParams().symbol)).toUpperCase();
  const qc = useQueryClient();
  const [horizon, setHorizon] = useState(5);
  const [picked, setPicked] = useState<string[]>(DEFAULT_MODELS);
  const [evaluate, setEvaluate] = useState(true);
  const [fast, setFast] = useState(false);
  const [ensemble, setEnsemble] = useState(true);
  const [interpName, setInterpName] = useState<string | null>(null);
  const [mode, setMode] = useState("expanding");
  const [levels, setLevels] = useState("");
  const [jobId, setJobId] = useState<string | null>(null);
  const [open, setOpen] = useState<string | null>(null);
  const [lbOpen, setLbOpen] = useState<string | null>(null);
  const [showSeason, setShowSeason] = useState(false);
  const [showPairs, setShowPairs] = useState(false);

  const cat = useQuery({ queryKey: ["modelcat"], queryFn: api.modelCatalog });
  const analysis = useQuery({ queryKey: ["analysis", symbol, horizon], queryFn: () => api.analysis(symbol, horizon), retry: false });
  const evalq = useQuery({ queryKey: ["evaluation", symbol, horizon], queryFn: () => api.evaluation(symbol, horizon), retry: false });
  const run = useMutation({
    mutationFn: () => api.runModels(symbol, { models: picked, horizon, evaluate, mode, fast,
      levels: levels.split(/[ ,]+/).map(Number).filter((n) => n > 0 && Number.isFinite(n)), ensemble }),
    onSuccess: (j) => setJobId(j.id),
  });
  const job = useQuery({ queryKey: ["job", jobId], queryFn: () => api.job(jobId as string), enabled: !!jobId,
    refetchInterval: (q) => (q.state.data && (q.state.data.status === "done" || q.state.data.status === "failed") ? false : 1000) });
  const jobDone = job.data?.status === "done";
  useEffect(() => { if (jobDone) { qc.invalidateQueries({ queryKey: ["analysis"] }); qc.invalidateQueries({ queryKey: ["evaluation"] }); qc.invalidateQueries({ queryKey: ["scorecard"] }); } }, [jobDone, qc]);
  const season = useQuery({ queryKey: ["season", symbol], queryFn: () => api.seasonality(symbol), enabled: showSeason, retry: false });
  const pairs = useQuery({ queryKey: ["pairs", symbol], queryFn: () => api.pairs(symbol), enabled: showPairs, retry: false });

  useEffect(() => {
    if (evalq.data && lbOpen === null) {
      const first = evalq.data.leaderboard.find((r) => !r.baseline);
      if (first) setLbOpen(first.model);
    }
  }, [evalq.data, lbOpen]);

  const running = run.isPending || (!!jobId && job.data && (job.data.status === "queued" || job.data.status === "running"));
  const a = analysis.data;
  const cons = a?.consensus;
  const fanView = a && (a.views.mc_bootstrap?.extras.fan ? a.views.mc_bootstrap : a.views.mc_gbm?.extras.fan ? a.views.mc_gbm : undefined);
  const coneViews = a ? ["garch", "gjr_garch", "egarch"].map((k) => a.views[k]).filter((v) => v?.extras.vol_cone) : [];
  const [coneName, setConeName] = useState<string | null>(null);
  const cone = coneViews.find((v) => v.name === coneName) ?? coneViews[0];
  const hmm = a?.views.hmm_regime;
  const toggle = (m: string) => setPicked((p) => (p.includes(m) ? p.filter((x) => x !== m) : [...p, m]));
  const modelInfo = (n: string) => cat.data?.models.find((m) => m.name === n);

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-3"><h1 className="text-2xl font-semibold">{symbol}</h1>
        <span className="rounded bg-violet-600 px-2 py-0.5 text-xs text-white">Forecast models are analysis tools, not predictions</span>
        <Link href={`/s/${encodeURIComponent(symbol)}/lab`} className="ml-auto text-sm font-medium text-indigo-600 hover:underline dark:text-indigo-300">Open the Model Lab →</Link></div>
      <SymbolTabs />

      <section className={card} data-tour="models-controls">
        <h2 className="mb-2 text-lg font-semibold">Run models</h2>
        <div className="grid gap-4 md:grid-cols-[1fr_auto]">
          <div>
            <p className="mb-1 text-xs text-slate-500">Pick models (the three baselines always run too: they are the yardstick every model must beat).</p>
            <div className="space-y-2" data-tour="model-groups">
              {["statistical", "machine learning", "deep (experimental)"].map((g) => (
                <div key={g}>
                  <h3 className="text-[11px] font-semibold uppercase tracking-wide text-slate-500">{g}</h3>
                  <div className="mt-0.5 flex flex-wrap gap-1.5">{cat.data?.models.filter((m) => m.group === g).map((m) => (
                    <label key={m.name} title={m.available ? m.description : `${m.description}\n\nUNAVAILABLE: ${m.unavailable_reason}`}
                      className={`rounded border px-2 py-1 text-sm ${!m.available ? "cursor-not-allowed border-dashed border-slate-300 text-slate-400 line-through dark:border-slate-700" : picked.includes(m.name) ? "cursor-pointer border-indigo-600 bg-indigo-50 dark:bg-indigo-950" : "cursor-pointer border-slate-300 dark:border-slate-700"}`}>
                      <input type="checkbox" className="mr-1" disabled={!m.available} checked={picked.includes(m.name) && m.available} onChange={() => toggle(m.name)} />{m.name}
                      {m.needs === "sentiment" && <span className="ml-1 text-[10px] text-amber-600 no-underline" title="Needs stored news for this stock">news</span>}
                      {m.needs === "pool" && <span className="ml-1 text-[10px] text-amber-600" title="Trains on other stored stocks too">pooled</span>}</label>))}</div>
                </div>))}
            </div>
            {cat.error && <p role="alert" className="text-sm text-red-500">{(cat.error as Error).message}</p>}
          </div>
          <div className="space-y-1.5 text-sm">
            <label className="flex items-center justify-between gap-2">Horizon
              <select value={horizon} onChange={(e) => setHorizon(Number(e.target.value))} className="rounded border border-slate-300 bg-white px-1 dark:border-slate-700 dark:bg-slate-900">
                {(cat.data?.horizons ?? [1, 5, 10, 21, 42, 63]).map((h) => <option key={h} value={h}>{HORIZON_LABEL[h] ?? `${h} days`}</option>)}</select></label>
            <label className="flex items-center justify-between gap-2">Test window
              <select value={mode} onChange={(e) => setMode(e.target.value)} className="rounded border border-slate-300 bg-white px-1 dark:border-slate-700 dark:bg-slate-900">
                <option value="expanding">expanding (all past data)</option><option value="rolling">rolling (last ~3 years)</option></select></label>
            <label className="flex items-center gap-1"><input type="checkbox" checked={evaluate} onChange={(e) => setEvaluate(e.target.checked)} /> walk-forward test (recommended)</label>
            <label className="flex items-center gap-1" title="Fewer simulations and refits: much faster, a little noisier"><input type="checkbox" checked={fast} onChange={(e) => setFast(e.target.checked)} /> quick mode</label>
            <label className="flex items-center gap-1" title="Blend the models you pick, weighted by how well each has done recently out of sample"><input type="checkbox" checked={ensemble} onChange={(e) => setEnsemble(e.target.checked)} /> ensemble of my picks</label>
          </div>
        </div>
        <label className="mt-2 block text-sm">Price levels to check (optional, comma separated)
          <input value={levels} onChange={(e) => setLevels(e.target.value)} placeholder="e.g. 3000, 2700" className="ml-2 w-56 rounded border border-slate-300 bg-white px-2 py-0.5 dark:border-slate-700 dark:bg-slate-900" />
          <span className="ml-2 text-xs text-slate-500">Monte Carlo reports the chance of touching each.</span></label>
        <div className="mt-3 flex flex-wrap items-center gap-3">
          <button data-tour="run-models" onClick={() => run.mutate()} disabled={!!running || picked.length === 0} className="rounded bg-indigo-600 px-4 py-1.5 text-sm font-medium text-white disabled:opacity-50">{running ? "Running…" : "Run models"}</button>
          {job.data && (
            <div className="min-w-[14rem] flex-1" role="status">
              <div className="h-2 rounded bg-slate-200 dark:bg-slate-800"><div className={`h-2 rounded ${job.data.status === "failed" ? "bg-red-600" : "bg-indigo-600"}`} style={{ width: `${Math.round(job.data.progress * 100)}%` }} /></div>
              <p className="mt-0.5 text-xs text-slate-500">{job.data.status === "done" ? `Done in ${job.data.result?.elapsed_s}s` : job.data.status === "failed" ? "Failed" : `${job.data.status}… ${Math.round(job.data.progress * 100)}%`}
                {job.data.result?.walk_forward && ` · ${job.data.result.walk_forward.forecasts} out-of-sample forecasts, refit every ${job.data.result.walk_forward.refit_every} days`}</p>
            </div>)}
        </div>
        {run.error && <p role="alert" className="mt-2 rounded bg-red-50 p-2 text-sm text-red-800 dark:bg-red-950 dark:text-red-200">{(run.error as Error).message}</p>}
        {job.data?.status === "failed" && <p role="alert" className="mt-2 rounded bg-red-50 p-2 text-sm text-red-800 dark:bg-red-950 dark:text-red-200">{job.data.error}</p>}
        {job.data?.result?.warnings.map((w) => <p key={w} className="mt-2 rounded bg-amber-50 p-2 text-xs text-amber-900 dark:bg-amber-950 dark:text-amber-200">{w}</p>)}
      </section>

      {analysis.error && !a && <div className={card}><p className="text-sm">No model runs stored for {symbol} at a {HORIZON_LABEL[horizon]} horizon yet. Choose models above and click <b>Run models</b>. This needs about 300 daily bars (run make seed).</p>
        <p className="mt-1 text-xs text-slate-500">{(analysis.error as Error).message}</p></div>}

      {a && cons && (
        <>
          <section className={card} data-tour="consensus">
            <div className="mb-2 flex flex-wrap items-center gap-2">
              <h2 className="text-lg font-semibold">Consensus panel</h2>
              {cons.disagreement && <span className={`rounded px-2 py-0.5 text-xs text-white ${cons.disagreement === "high" ? "bg-red-600" : cons.disagreement === "medium" ? "bg-amber-500" : "bg-green-600"}`}>disagreement: {cons.disagreement}</span>}
              {cons.conviction && <span className="rounded bg-slate-600 px-2 py-0.5 text-xs text-white">conviction: {cons.conviction}</span>}
              <span className="ml-auto text-xs text-slate-500">data to {a.asof} · {HORIZON_LABEL[a.horizon]}</span>
            </div>
            <p className="mb-2 text-sm font-medium">{cons.headline}</p>
            <p className="mb-2 text-xs text-slate-500">Votes: {Object.entries(cons.votes).map(([k, v]) => `${v} ${k}`).join(", ")} · {cons.n_edge} of {cons.n_models} models have a demonstrated edge.</p>
            <div className="overflow-x-auto" data-tour="model-table">
              <table className="w-full text-sm">
                <thead className="text-left text-xs text-slate-500"><tr><th>Model</th><th>Outlook (up / flat / down)</th><th>Vote</th><th>90% range</th><th title="Up/down calls that were right, vs always guessing the commoner direction">Hit rate vs naive</th><th title="Brier-score improvement over the base-rate baseline">Skill</th><th>Track record</th><th /></tr></thead>
                <tbody>
                  {cons.models.map((r) => <ModelRow key={r.name} r={r} v={a.views[r.name]} open={open === r.name} toggle={() => setOpen(open === r.name ? null : r.name)} exp={!!modelInfo(r.name)?.experimental} />)}
                  {cons.ensemble && <ModelRow key="ensemble" r={cons.ensemble} v={a.views.ensemble} open={open === "ensemble"} toggle={() => setOpen(open === "ensemble" ? null : "ensemble")} exp={false} />}
                  {cons.baselines.map((r) => <ModelRow key={r.name} r={r} v={a.views[r.name]} baseline open={open === r.name} toggle={() => setOpen(open === r.name ? null : r.name)} exp={false} />)}
                </tbody>
              </table>
            </div>
            {cons.how_to_read && <p className="mt-2 text-xs text-slate-500">{cons.how_to_read}</p>}
          </section>

          <div className="grid gap-4 lg:grid-cols-2">
            {fanView?.extras.fan && (
              <section className={card} data-tour="fan">
                <h2 className="text-lg font-semibold">Fan chart <span className="text-sm font-normal text-slate-500">({fanView.name}, {fanView.horizon} days)</span></h2>
                <FanChart fan={fanView.extras.fan} />
                <p className="text-xs text-slate-500">Thousands of simulated price paths. The dark band holds the middle 50% of them, the light band 90%. It is a picture of uncertainty, not a prediction of where price will go. Amber lines are the price levels you asked about, with the simulated chance of touching them.</p>
              </section>)}
            {cone?.extras.vol_cone && (
              <section className={card} data-tour="volcone">
                <div className="flex items-center gap-2"><h2 className="text-lg font-semibold">Volatility cone</h2>
                  {coneViews.length > 1 && <select value={cone.name} onChange={(e) => setConeName(e.target.value)} className="rounded border border-slate-300 bg-white px-1 text-xs dark:border-slate-700 dark:bg-slate-900" aria-label="Volatility model">{coneViews.map((v) => <option key={v.name}>{v.name}</option>)}</select>}</div>
                <ConeChart cone={cone.extras.vol_cone} />
                <p className="text-xs text-slate-500">Red line: the model&apos;s forecast of annualised volatility over each window. Grey bands: the range realised volatility has actually covered over ~3 years (median dashed). Blue squares: realised right now. A red line above the grey band means the model expects unusually rough conditions.</p>
              </section>)}
          </div>

          {hmm?.extras.regime_probs && hmm.extras.timeline && (
            <section className={card} data-tour="regime">
              <h2 className="text-lg font-semibold">Market regime (hidden Markov model)</h2>
              <p className="mb-2 text-sm">Right now: <b>{hmm.extras.current_regime}</b> — {Object.entries(hmm.extras.regime_probs).map(([k, v]) => `${k} ${(v * 100).toFixed(0)}%`).join(", ")}</p>
              <RegimeStrip regime={hmm.extras.timeline.regime} prob={hmm.extras.timeline.prob} dates={hmm.extras.timeline.dates} labels={hmm.extras.timeline.labels} />
              <div className="mt-2 overflow-x-auto"><table className="w-full text-xs tabular-nums"><thead className="text-left text-slate-500"><tr><th>Regime</th><th>Avg yearly return</th><th>Volatility</th><th>Share of days</th><th>Typical stay</th></tr></thead>
                <tbody>{hmm.extras.regime_table?.map((r) => <tr key={r.regime} className="border-t border-slate-200 dark:border-slate-800"><td className="py-0.5">{r.regime}</td><td>{sgn(r.mean_return_annual, 0)}</td><td>{pct(r.volatility_annual, 0)}</td><td>{pct(r.share_of_days, 0)}</td><td>{r.expected_duration_days.toFixed(0)} days</td></tr>)}</tbody></table></div>
              <p className="mt-1 text-xs text-slate-500">The model learns hidden states from this stock&apos;s own returns. Names are relative: the lowest-return state is called &quot;bear&quot; even if its average is positive. Colours use only information available at each date (no hindsight).</p>
            </section>)}
        </>
      )}

      {a && (() => {
        const ml = Object.values(a.views).filter((v) => v.extras.permutation_importance);
        const cur = ml.find((v) => v.name === interpName) ?? ml[0];
        if (!cur) return null;
        const ex = cur.extras;
        return (
          <section className={card} data-tour="interpret">
            <div className="mb-2 flex flex-wrap items-center gap-2"><h2 className="text-lg font-semibold">Why does the model say that?</h2>
              <select value={cur.name} onChange={(e) => setInterpName(e.target.value)} className="rounded border border-slate-300 bg-white px-1 text-xs dark:border-slate-700 dark:bg-slate-900" aria-label="Model to explain">{ml.map((v) => <option key={v.name}>{v.name}</option>)}</select>
              {ex.calibration && <span className="rounded bg-slate-200 px-2 py-0.5 text-xs dark:bg-slate-800" title="How much of the model's probabilities survive blending with the base rate. Chosen on held-out days; low = the model showed no reliable skill.">trust in model: {(ex.calibration.trust_in_model * 100).toFixed(0)}%</span>}</div>
            <div className="grid gap-5 md:grid-cols-2">
              <div><h3 className="mb-1 text-sm font-semibold">What pushed today&apos;s forecast</h3>
                {ex.shap_now ? <PushBars items={ex.shap_now.map((d) => ({ label: `${d.feature}${d.value === null ? "" : ` = ${d.value.toPrecision(3)}`}`, value: d.toward_up }))} />
                  : <ul className="list-disc pl-5 text-xs">{cur.drivers.map((d) => <li key={d.name}>{d.name}: {d.value}</li>)}</ul>}
                <p className="mt-1 text-[11px] text-slate-500">Green pushes toward UP, red toward DOWN (SHAP values: each feature&apos;s share of this one prediction).</p></div>
              <div><h3 className="mb-1 text-sm font-semibold">{ex.shap_global ? "What matters overall (mean |SHAP|)" : "What matters overall"}</h3>
                <BarList items={(ex.shap_global ? ex.shap_global.map((d) => ({ label: d.feature, value: d.mean_abs_shap })) : (ex.permutation_importance ?? []).map((d) => ({ label: d.feature, value: d.importance }))).slice(0, 10)} /></div>
              <div><h3 className="mb-1 text-sm font-semibold">Permutation importance (held-out days)</h3>
                <BarList color="#f59e0b" digits={4} items={(ex.permutation_importance ?? []).slice(0, 8).map((d) => ({ label: d.feature, value: d.importance }))} />
                <p className="mt-1 text-[11px] text-slate-500">How much worse the model gets on days it never trained on when one feature is shuffled. Near zero or negative: the feature is not really helping.</p></div>
              <div><h3 className="mb-1 text-sm font-semibold">Partial dependence of P(up)</h3>
                <div className="flex flex-wrap gap-3">{(ex.partial_dependence ?? []).map((d) => <PdpChart key={d.feature} feature={d.feature} grid={d.grid} p_up={d.p_up} />)}</div>
                <p className="mt-1 text-[11px] text-slate-500">Average predicted chance of UP as one feature moves across its usual range, others held as observed.</p></div>
            </div>
            <ExplainModel symbol={symbol} horizon={horizon} model={cur.name} />
            <p className="mt-2 text-xs text-slate-500">{ex.shap_note} These explain what the model learned, which is not the same as what drives the market: with weak signals the explanation can be a story about noise. Check the walk-forward verdict first.</p>
          </section>);
      })()}
      <AblationPanel symbol={symbol} horizon={horizon} />

      {evalq.data && (
        <section className={card} data-tour="leaderboard">
          <h2 className="text-lg font-semibold">Walk-forward evaluation vs baselines</h2>
          <p className="mb-2 text-xs text-slate-500">{evalq.data.period.forecasts} out-of-sample forecasts from {evalq.data.period.first} to {evalq.data.period.last} ({evalq.data.period.mode} window, one forecast every {evalq.data.period.stride} days so outcomes never overlap). Click a row for calibration, cumulative skill and the confusion matrix.</p>
          <div className="overflow-x-auto"><table className="w-full text-xs tabular-nums">
            <thead className="text-left text-slate-500"><tr><th>Model</th><th>Verdict</th><th title="Lower is better">Brier</th><th title="Improvement over the base-rate baseline">Skill</th><th>Hit rate</th><th>Naive</th><th title="Bonferroni-corrected across models tried">p (adj.)</th><th title="Calibration error: lower is better">ECE</th><th title="Below 1 beats no-change">MASE</th><th title="Should be about 90%">90% cover</th><th title="Rank information coefficient">IC</th><th>Forecasts</th></tr></thead>
            <tbody>{evalq.data.leaderboard.map((r) => (
              <Fragment key={r.model}>
                <tr className="cursor-pointer border-t border-slate-200 hover:bg-slate-50 dark:border-slate-800 dark:hover:bg-slate-900" onClick={() => setLbOpen(lbOpen === r.model ? null : r.model)}>
                  <td className="py-1 font-medium">{r.model}{r.baseline && <span className="ml-1 text-[10px] font-normal text-slate-500">baseline</span>}</td>
                  <td><Verdict v={r.verdict} why={evalq.data.details[r.model]?.verdict_reason} /></td><td>{r.brier.toFixed(4)}</td><td>{r.brier_skill === null ? "" : sgn(r.brier_skill)}</td>
                  <td>{pct(r.hit_rate, 0)}</td><td>{pct(r.naive_rate, 0)}</td><td>{r.p_adjusted === null ? "" : r.p_adjusted.toFixed(3)}</td><td>{r.ece === null ? "" : r.ece.toFixed(3)}</td>
                  <td>{r.mase === null ? "" : r.mase.toFixed(3)}</td><td>{pct(r.coverage_90, 0)}</td><td>{r.rank_ic === null ? "" : r.rank_ic.toFixed(2)}</td><td>{r.n_effective.toFixed(0)}</td></tr>
                {lbOpen === r.model && evalq.data.details[r.model] && <tr><td colSpan={12}><Detail d={evalq.data.details[r.model]} /></td></tr>}
              </Fragment>))}</tbody></table></div>
          <ul className="mt-2 list-disc pl-5 text-xs text-slate-500">{evalq.data.notes.map((n) => <li key={n}>{n}</li>)}</ul>
        </section>
      )}

      <div className="grid gap-4 lg:grid-cols-2">
        <section className={card} data-tour="seasonality">
          <div className="flex items-center gap-2"><h2 className="text-lg font-semibold">Seasonality</h2>
            {!showSeason && <button onClick={() => setShowSeason(true)} className="rounded bg-slate-200 px-2 py-0.5 text-xs dark:bg-slate-800">Analyse day-of-week and month</button>}</div>
          {season.isLoading && <div className="skeleton h-24" />}
          {season.error && <p role="alert" className="text-sm text-amber-600">{(season.error as Error).message}</p>}
          {season.data && (
            <div className="space-y-3">
              <SeasonTable title="Day of week (average daily return)" rows={season.data.day_of_week.rows} p={season.data.day_of_week.kruskal_p} />
              <SeasonTable title="Month of year" rows={season.data.month.rows} p={season.data.month.kruskal_p} />
              {season.data.stl && <p className="text-xs">Repeating {season.data.stl.period}-day cycle strength {season.data.stl.seasonal_strength.toFixed(2)}: <b>{season.data.stl.reading}</b>.</p>}
              <p className="text-xs text-slate-500">★ = significant after correcting for testing several groups. Faded bars are not significant. {season.data.notes.join(" ")}</p>
            </div>)}
          {!showSeason && <p className="text-xs text-slate-500">Does this stock behave differently on certain weekdays or months? Tested rigorously, because calendar patterns are easy to find by chance.</p>}
        </section>
        <section className={card} data-tour="pairs">
          <div className="flex items-center gap-2"><h2 className="text-lg font-semibold">Pairs (cointegration)</h2>
            {!showPairs && <button onClick={() => setShowPairs(true)} className="rounded bg-slate-200 px-2 py-0.5 text-xs dark:bg-slate-800">Scan same-sector peers</button>}</div>
          {pairs.isLoading && <div className="skeleton h-24" />}
          {pairs.error && <p role="alert" className="text-sm text-amber-600">{(pairs.error as Error).message}</p>}
          {pairs.data && (
            <div>
              <table className="w-full text-xs tabular-nums"><thead className="text-left text-slate-500"><tr><th>Peer</th><th>p (adj.)</th><th>Half-life</th><th>Spread z</th><th>Stable?</th><th /></tr></thead>
                <tbody>{pairs.data.peers.map((p) => p.skipped ? <tr key={p.peer} className="border-t border-slate-200 text-slate-400 dark:border-slate-800"><td>{p.peer}</td><td colSpan={5}>{p.skipped}</td></tr> : (
                  <tr key={p.peer} className="border-t border-slate-200 dark:border-slate-800"><td className="py-0.5">{p.peer}</td><td>{p.p_bonferroni?.toFixed(3)}</td><td>{p.half_life_days ? `${p.half_life_days.toFixed(0)} d` : "n/a"}</td>
                    <td>{p.zscore_now === null || p.zscore_now === undefined ? "n/a" : p.zscore_now.toFixed(2)}</td><td>{p.stable ? "yes" : "no"}</td><td>{p.candidate && <span className="rounded bg-green-600 px-1 text-white">candidate</span>}</td></tr>))}</tbody></table>
              {pairs.data.best_spread && <div className="mt-2"><p className="text-xs">Spread vs {pairs.data.best}:</p>
                <SvgLine dates={pairs.data.best_spread.dates} values={pairs.data.best_spread.spread} zero={false} color="#0ea5e9" height={110} label="Spread" /></div>}
              <ul className="mt-1 list-disc pl-5 text-xs text-slate-500">{pairs.data.notes.map((n) => <li key={n}>{n}</li>)}</ul>
            </div>)}
          {!showPairs && <p className="text-xs text-slate-500">Two stocks are cointegrated if their price gap keeps snapping back to normal. Needs stored prices for same-sector peers.</p>}
        </section>
      </div>
      <p className="text-xs text-slate-500">Educational tool, not investment advice. Models describe uncertainty from past data; a past edge can disappear.</p>
    </div>
  );
}

export default function Page() { return <Suspense fallback={<div className="skeleton h-96" />}><View /></Suspense>; }
