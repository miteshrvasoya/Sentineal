"use client";
import { useQuery } from "@tanstack/react-query";
import { useParams } from "next/navigation";
import { Suspense, useEffect, useMemo, useState } from "react";
import { colorFor, MultiLine, type Series } from "@/components/ModelCharts";
import SymbolTabs from "@/components/SymbolTabs";
import { api, type EvalResp, type RegistryRow } from "@/lib/api";
import { pct } from "@/lib/explain";

const card = "rounded border border-slate-200 p-3 dark:border-slate-800";
const HORIZONS = [1, 5, 10, 21, 42, 63];
type Row = EvalResp["leaderboard"][number] & { equity_return: number | null; exposure: number | null; failures: number };

const COLS: { key: keyof Row; label: string; tip: string; fmt: (v: never) => string; lowerBetter?: boolean }[] = [
  { key: "brier", label: "Brier", tip: "Mean squared probability error. Lower is better.", fmt: ((v: number) => v.toFixed(4)) as never, lowerBetter: true },
  { key: "brier_skill", label: "Skill", tip: "Improvement over the base-rate baseline. Positive is better than naive.", fmt: ((v: number | null) => (v === null ? "" : `${v >= 0 ? "+" : ""}${(v * 100).toFixed(1)}%`)) as never },
  { key: "hit_rate", label: "Hit rate", tip: "Up/down calls that were right (flat outcomes ignored).", fmt: ((v: number | null) => pct(v, 0)) as never },
  { key: "naive_rate", label: "Naive", tip: "Hit rate of always guessing the commoner direction.", fmt: ((v: number | null) => pct(v, 0)) as never },
  { key: "p_adjusted", label: "p (adj.)", tip: "Diebold-Mariano p-value, Bonferroni-corrected for the models tried.", fmt: ((v: number | null) => (v === null ? "" : v.toFixed(3))) as never, lowerBetter: true },
  { key: "ece", label: "ECE", tip: "Calibration error. Lower means the probabilities can be taken at face value.", fmt: ((v: number | null) => (v === null ? "" : v.toFixed(3))) as never, lowerBetter: true },
  { key: "mase", label: "MASE", tip: "Below 1 beats forecasting 'no change'.", fmt: ((v: number | null) => (v === null ? "" : v.toFixed(3))) as never, lowerBetter: true },
  { key: "coverage_90", label: "90% cover", tip: "Share of outcomes inside the model's 90% range. Should be about 90%.", fmt: ((v: number) => pct(v, 0)) as never },
  { key: "rank_ic", label: "Rank IC", tip: "Rank correlation between forecast and outcome.", fmt: ((v: number | null) => (v === null ? "" : v.toFixed(2))) as never },
  { key: "equity_return", label: "Equity", tip: "Diagnostic: return of 'long when the model says UP, else cash' over the test period. No costs.", fmt: ((v: number | null) => (v === null ? "" : `${v >= 0 ? "+" : ""}${(v * 100).toFixed(1)}%`)) as never },
  { key: "exposure", label: "Time long", tip: "Share of forecasts where the model said UP.", fmt: ((v: number | null) => pct(v, 0)) as never },
  { key: "n_effective", label: "Forecasts", tip: "Independent out-of-sample forecasts.", fmt: ((v: number) => v.toFixed(0)) as never },
];

function Verdict({ v }: { v: string }) {
  const cls = v === "demonstrated edge" ? "bg-green-600 text-white" : v === "baseline" ? "bg-slate-500 text-white" : v === "insufficient sample" ? "bg-amber-500 text-white" : "bg-slate-300 text-slate-800 dark:bg-slate-700 dark:text-slate-100";
  return <span className={`rounded px-1.5 py-0.5 text-xs ${cls}`}>{v}</span>;
}

function CalibrationOverlay({ curves }: { curves: { name: string; color: string; rows: { mean_pred: number; observed: number; n: number }[] }[] }) {
  const S = 260, P = 34;
  const x = (v: number) => P + v * (S - P - 8), y = (v: number) => S - P - v * (S - P - 8);
  return (
    <figure>
      <svg viewBox={`0 0 ${S} ${S}`} role="img" aria-label="Calibration curves of the selected models" className="w-full max-w-sm">
        <line x1={x(0)} y1={y(0)} x2={x(1)} y2={y(1)} stroke="currentColor" opacity="0.4" strokeDasharray="3 3" />
        {curves.map((c) => (
          <g key={c.name}>
            <polyline fill="none" stroke={c.color} strokeWidth="1.6" points={c.rows.map((r) => `${x(r.mean_pred)},${y(r.observed)}`).join(" ")} />
            {c.rows.map((r, i) => <circle key={i} cx={x(r.mean_pred)} cy={y(r.observed)} r="2.6" fill={c.color}><title>{`${c.name}: said ${(r.mean_pred * 100).toFixed(0)}%, was up ${(r.observed * 100).toFixed(0)}% (n=${r.n})`}</title></circle>)}
          </g>))}
        <text x={S / 2} y={S - 8} fontSize="10" textAnchor="middle" fill="currentColor" opacity="0.7">predicted P(up)</text>
        <text x={9} y={S / 2} fontSize="10" textAnchor="middle" fill="currentColor" opacity="0.7" transform={`rotate(-90 9 ${S / 2})`}>observed frequency</text>
      </svg>
      <figcaption className="flex flex-wrap gap-x-3 text-[11px]">{curves.map((c) => <span key={c.name}><span className="mr-1 inline-block h-2 w-3 rounded-sm align-middle" style={{ background: c.color }} />{c.name}</span>)}</figcaption>
    </figure>
  );
}

function decay(rows: RegistryRow[]): { flag: boolean; why: string } {
  const sk = rows.map((r) => r.brier_skill).filter((v): v is number => v !== null);
  if (sk.length < 3) return { flag: false, why: "needs 3+ versions to judge drift" };
  const latest = sk[0], prev = sk.slice(1);
  const med = [...prev].sort((a, b) => a - b)[Math.floor(prev.length / 2)];
  const wasEdge = rows.slice(1).some((r) => r.verdict === "demonstrated edge");
  if (rows[0].verdict !== "demonstrated edge" && wasEdge) return { flag: true, why: "previously showed an edge, no longer does" };
  if (latest < med - 0.02) return { flag: true, why: `skill fell from a typical ${(med * 100).toFixed(1)}% to ${(latest * 100).toFixed(1)}%` };
  return { flag: false, why: "stable across versions" };
}

function View() {
  const symbol = decodeURIComponent(String(useParams().symbol)).toUpperCase();
  const [horizon, setHorizon] = useState(5);
  const ev = useQuery({ queryKey: ["evaluation", symbol, horizon], queryFn: () => api.evaluation(symbol, horizon), retry: false });
  const reg = useQuery({ queryKey: ["registry", symbol], queryFn: () => api.registry(symbol), retry: false });
  const [sel, setSel] = useState<string[] | null>(null);
  const [sort, setSort] = useState<{ key: keyof Row; dir: 1 | -1 }>({ key: "brier", dir: 1 });
  const [cm, setCm] = useState<string | null>(null);
  const [regModel, setRegModel] = useState<string | null>(null);

  const rows: Row[] = useMemo(() => (ev.data?.leaderboard ?? []).map((r) => {
    const d = ev.data!.details[r.model];
    return { ...r, equity_return: d.equity?.total_return ?? null, exposure: d.equity?.exposure ?? null, failures: d.failures ?? 0 };
  }), [ev.data]);
  useEffect(() => { setSel(null); setCm(null); }, [symbol, horizon]);
  const selected = sel ?? rows.filter((r) => !r.baseline).slice(0, 4).map((r) => r.model).concat(rows.some((r) => r.model === "buy_hold") ? ["buy_hold"] : []);
  const sorted = [...rows].sort((a, b) => {
    const x = a[sort.key] as number | null, y = b[sort.key] as number | null;
    if (x === null || x === undefined) return 1;
    if (y === null || y === undefined) return -1;
    return (x - y) * sort.dir;
  });
  const toggle = (m: string) => setSel((cur) => { const c = cur ?? selected; return c.includes(m) ? c.filter((x) => x !== m) : [...c, m]; });
  const det = (m: string) => ev.data!.details[m];
  const colorOf = (m: string) => colorFor(rows.findIndex((r) => r.model === m));

  const equity: Series[] = ev.data ? selected.filter((m) => det(m)?.equity).map((m) => ({ name: m, color: colorOf(m), points: det(m).equity!.series })) : [];
  if (ev.data && selected.length && det(selected[0])?.equity) equity.push({ name: "always long (buy & hold)", color: "#64748b", dashed: true, points: det(selected[0]).equity!.buy_hold });
  const skill: Series[] = ev.data ? selected.filter((m) => det(m)?.cum_skill).map((m) => ({ name: m, color: colorOf(m), points: det(m).cum_skill! })) : [];
  const roll: Series[] = ev.data ? selected.filter((m) => det(m)).map((m) => ({ name: m, color: colorOf(m), points: det(m).rolling_accuracy })) : [];
  const ic: Series[] = ev.data ? selected.filter((m) => det(m)).map((m) => ({ name: m, color: colorOf(m), points: det(m).rank_ic.rolling.filter((r) => r.ic !== null).map((r) => ({ date: r.date, v: r.ic as number })) })).filter((s) => s.points.length > 1) : [];
  const calib = ev.data ? selected.filter((m) => det(m)).map((m) => ({ name: m, color: colorOf(m), rows: det(m).calibration_up.rows })) : [];
  const cmModel = cm ?? selected[0];

  const byModel = useMemo(() => {
    const m = new Map<string, RegistryRow[]>();
    (reg.data ?? []).filter((r) => r.horizon === horizon).forEach((r) => m.set(r.model, [...(m.get(r.model) ?? []), r]));
    return m;
  }, [reg.data, horizon]);
  const regNames = Array.from(byModel.keys());
  const regSel = regModel && byModel.has(regModel) ? regModel : regNames.find((n) => !/^(base_rate|buy_hold|ma_rule)$/.test(n)) ?? regNames[0];

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-3"><h1 className="text-2xl font-semibold">{symbol}</h1>
        <span className="rounded bg-violet-600 px-2 py-0.5 text-xs text-white">Model Lab: did the models actually work out of sample?</span>
        <label className="ml-auto text-sm">Horizon <select value={horizon} onChange={(e) => setHorizon(Number(e.target.value))} className="rounded border border-slate-300 bg-white px-1 dark:border-slate-700 dark:bg-slate-900">
          {HORIZONS.map((h) => <option key={h} value={h}>{h} day{h > 1 ? "s" : ""}</option>)}</select></label></div>
      <SymbolTabs />
      {ev.isLoading && <div className="skeleton h-72" />}
      {ev.error && <div className={card}><p className="text-sm">No walk-forward results stored for {symbol} at a {horizon}-day horizon yet. Go to the <b>Models</b> tab, pick models, keep &quot;walk-forward test&quot; ticked and run them.</p>
        <p className="mt-1 text-xs text-slate-500">{(ev.error as Error).message}</p></div>}

      {ev.data && (
        <>
          <section className={card} data-tour="lab-leaderboard">
            <h2 className="text-lg font-semibold">Leaderboard</h2>
            <p className="mb-2 text-xs text-slate-500">{ev.data.period.forecasts} forecasts, {ev.data.period.first} to {ev.data.period.last}. Click a column to sort; click a model name to add or remove it from the charts below.</p>
            <div className="overflow-x-auto"><table className="w-full text-xs tabular-nums">
              <thead className="text-left text-slate-500"><tr><th>Model</th><th>Verdict</th>
                {COLS.map((c) => <th key={c.key} title={c.tip} className="cursor-pointer select-none whitespace-nowrap" onClick={() => setSort((s) => ({ key: c.key, dir: s.key === c.key ? (-s.dir as 1 | -1) : 1 }))}>
                  {c.label}{sort.key === c.key ? (sort.dir === 1 ? " ▲" : " ▼") : ""}</th>)}<th>Failed</th></tr></thead>
              <tbody>{sorted.map((r) => (
                <tr key={r.model} className="border-t border-slate-200 dark:border-slate-800">
                  <td className="py-1"><button onClick={() => toggle(r.model)} aria-pressed={selected.includes(r.model)} className={`rounded px-1.5 py-0.5 font-medium ${selected.includes(r.model) ? "text-white" : "bg-slate-100 text-slate-500 dark:bg-slate-800"}`}
                    style={selected.includes(r.model) ? { background: colorOf(r.model) } : undefined}>{r.model}</button>{r.baseline && <span className="ml-1 text-[10px] text-slate-500">baseline</span>}</td>
                  <td title={ev.data.details[r.model].verdict_reason}><Verdict v={r.verdict} /></td>
                  {COLS.map((c) => <td key={c.key}>{r[c.key] === null || r[c.key] === undefined ? "" : (c.fmt as (v: unknown) => string)(r[c.key])}</td>)}
                  <td className={r.failures ? "text-amber-600" : "text-slate-400"}>{r.failures}</td></tr>))}</tbody></table></div>
          </section>

          <div className="grid gap-4 lg:grid-cols-2">
            <section className={card} data-tour="lab-equity">
              <h3 className="font-semibold">Walk-forward equity vs always-long</h3>
              <MultiLine series={equity} label="Walk-forward equity curves" baseline={100} />
              <p className="text-xs text-slate-500">{det(selected[0] ?? "")?.equity?.note ?? "Select models in the leaderboard."} A line above the dashed one means that rule did better than simply holding, before any costs.</p>
            </section>
            <section className={card} data-tour="lab-decay">
              <h3 className="font-semibold">Cumulative skill over time (decay)</h3>
              <MultiLine series={skill} label="Cumulative Brier advantage over the base-rate baseline" baseline={0} fmt={(v) => v.toFixed(3)} />
              <p className="text-xs text-slate-500">Each step up is a forecast that beat the baseline, each step down one that lost. A line that rises and then flattens or falls is an edge that decayed. Ending near zero or below means no skill.</p>
            </section>
            <section className={card}>
              <h3 className="font-semibold">Rolling 3-way accuracy</h3>
              <MultiLine series={roll} label="Rolling accuracy" fmt={(v) => `${(v * 100).toFixed(0)}%`} />
              <p className="text-xs text-slate-500">Share of recent forecasts where the top vote matched the outcome. Compare with the baselines: if they sit on top of each other, there is no skill.</p>
            </section>
            <section className={card}>
              <h3 className="font-semibold">Rolling rank IC</h3>
              {ic.length ? <MultiLine series={ic} label="Rolling rank information coefficient" baseline={0} fmt={(v) => v.toFixed(2)} /> : <p className="text-sm text-slate-500">Not enough forecasts for a rolling IC.</p>}
              <p className="text-xs text-slate-500">Correlation between forecast and outcome over a sliding window. Persistently above zero would be a sign of real skill; hovering around zero is noise.</p>
            </section>
            <section className={card} data-tour="lab-calibration">
              <h3 className="font-semibold">Calibration of P(up)</h3>
              <CalibrationOverlay curves={calib} />
              <p className="text-xs text-slate-500">Curves on the diagonal are honest probabilities. Curves above it mean the model under-states how often price rose; below, that it over-states it.</p>
            </section>
            <section className={card}>
              <div className="flex items-center gap-2"><h3 className="font-semibold">Confusion matrix</h3>
                <select value={cmModel} onChange={(e) => setCm(e.target.value)} className="rounded border border-slate-300 bg-white px-1 text-xs dark:border-slate-700 dark:bg-slate-900" aria-label="Model">{rows.map((r) => <option key={r.model}>{r.model}</option>)}</select></div>
              {ev.data.details[cmModel] && (() => {
                const c = ev.data.details[cmModel].confusion;
                const tot = c.matrix.flat().reduce((a, b) => a + b, 0) || 1;
                return (
                  <table className="mt-1 text-xs tabular-nums"><thead><tr><th className="pr-2 text-left text-slate-500">actual \\ model called</th>{c.classes.map((k) => <th key={k} className="w-16">{k}</th>)}<th className="w-16 text-slate-500">recall</th></tr></thead>
                    <tbody>{c.matrix.map((row, i) => (
                      <tr key={i}><td className="pr-2">{c.classes[i]}</td>{row.map((v, j) => <td key={j} className="h-8 text-center" style={{ background: `rgba(99,102,241,${(v / tot) * (i === j ? 2.2 : 1.2)})` }}>{v}</td>)}<td className="text-center text-slate-500">{pct(c.recall[c.classes[i]], 0)}</td></tr>))}
                      <tr><td className="pr-2 text-slate-500">precision</td>{c.classes.map((k) => <td key={k} className="text-center text-slate-500">{pct(c.precision[k], 0)}</td>)}<td /></tr></tbody></table>);
              })()}
              <p className="mt-1 text-xs text-slate-500">Rows: what really happened. Columns: what the model called. Darker = more cases. Precision: when it called a class, how often it was right. Recall: how many real cases of that class it found.</p>
            </section>
          </div>
        </>
      )}

      <section className={card} data-tour="lab-registry">
        <div className="flex flex-wrap items-center gap-2"><h2 className="text-lg font-semibold">Model registry and drift</h2>
          {regNames.length > 0 && <select value={regSel} onChange={(e) => setRegModel(e.target.value)} className="rounded border border-slate-300 bg-white px-1 text-xs dark:border-slate-700 dark:bg-slate-900" aria-label="Registry model">{regNames.map((n) => <option key={n}>{n}</option>)}</select>}</div>
        {reg.isLoading && <div className="skeleton h-16" />}
        {regNames.length === 0 && !reg.isLoading && <p className="text-sm text-slate-500">No stored runs at this horizon yet. Every run is saved as a new version with its data window, parameters and metrics, so you can see whether a model&apos;s record is stable or decaying.</p>}
        {regSel && (() => {
          const rs = byModel.get(regSel) ?? [];
          const d = decay(rs);
          return (
            <>
              <p className={`my-1 text-sm ${d.flag ? "text-amber-600" : "text-slate-600 dark:text-slate-400"}`}>{d.flag ? "Possible decay: " : "Drift check: "}{d.why}.</p>
              <div className="overflow-x-auto"><table className="w-full text-xs tabular-nums"><thead className="text-left text-slate-500"><tr><th>Version</th><th>Trained</th><th>Data to</th><th>Rows</th><th>Skill</th><th>Hit rate</th><th>Verdict</th><th>Input hash</th></tr></thead>
                <tbody>{rs.map((r) => <tr key={r.version} className="border-t border-slate-200 dark:border-slate-800"><td className="py-0.5">v{r.version}</td><td>{new Date(r.trained_at * 1000).toISOString().slice(0, 10)}</td><td>{r.train_end}</td><td>{r.n_train}</td>
                  <td>{r.brier_skill === null ? "" : `${r.brier_skill >= 0 ? "+" : ""}${(r.brier_skill * 100).toFixed(1)}%`}</td><td>{pct(r.hit_rate, 0)}</td><td>{r.verdict ?? ""}</td><td className="font-mono text-[10px] text-slate-500">{r.feature_hash}</td></tr>)}</tbody></table></div>
            </>);
        })()}
        <p className="mt-2 text-xs text-slate-500">Scheduled nightly retraining arrives in Phase 10; until then each run you start adds a version. &quot;Input hash&quot; identifies which features the model saw.</p>
      </section>
      <p className="text-xs text-slate-500">Educational tool, not investment advice. The equity lines are diagnostics without trading costs; the backtester with Indian costs comes in Phase 9.</p>
    </div>
  );
}

export default function Page() { return <Suspense fallback={<div className="skeleton h-96" />}><View /></Suspense>; }
