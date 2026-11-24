"use client";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";
import SvgLine from "@/components/SvgLine";
import SymbolTabs from "@/components/SymbolTabs";
import { api, type Corr, type Fundamentals, type Pct } from "@/lib/api";
import { fmtVal, num, pct, RATIOS, RISK_TIPS } from "@/lib/explain";

const card = "rounded border border-slate-200 p-3 dark:border-slate-800";
const Err = ({ e }: { e: unknown }) => <p role="alert" className="text-sm text-amber-600">{(e as Error).message}</p>;

function PctBar({ p, metric }: { p?: Pct; metric: string }) {
  if (!p || p.percentile === null) return <span className="text-xs text-slate-400">needs 3+ peers{p ? ` (have ${p.peers})` : ""}</span>;
  const hib = p.higher_is_better;
  return (
    <div className="w-40">
      <div className="relative h-1.5 rounded bg-gradient-to-r from-slate-200 to-indigo-300 dark:from-slate-700 dark:to-indigo-800" title={`${metric}: percentile ${p.percentile} among ${p.peers} peers`}>
        <div className="absolute -top-1 h-3.5 w-1 rounded bg-slate-900 dark:bg-white" style={{ left: `${p.percentile}%` }} />
      </div>
      <p className="mt-0.5 text-[10px] text-slate-500">{hib ? `higher than ${p.percentile}%` : `lower than ${(100 - p.percentile).toFixed(0)}%`} of {p.peers} peers</p>
    </div>
  );
}

function Heat({ c }: { c: Corr }) {
  const bg = (v: number | null) => (v === null ? "transparent" : v >= 0 ? `rgba(220,38,38,${Math.abs(v) * 0.75})` : `rgba(37,99,235,${Math.abs(v) * 0.75})`);
  return (
    <div className="overflow-x-auto">
      <table className="text-xs tabular-nums" aria-label="Correlation matrix">
        <thead><tr><th />{c.symbols.map((s) => <th key={s} className="px-1 font-medium"><span className="block max-w-[3.5rem] truncate">{s}</span></th>)}</tr></thead>
        <tbody>{c.matrix.map((row, i) => (
          <tr key={c.symbols[i]}><th className="pr-2 text-right font-medium">{c.symbols[i]}</th>
            {row.map((v, j) => <td key={j} className="h-8 w-14 text-center" style={{ background: bg(v) }} title={`${c.symbols[i]} vs ${c.symbols[j]}: ${v ?? "n/a"}`}>{v === null ? "–" : v.toFixed(2)}</td>)}</tr>))}
        </tbody>
      </table>
      <p className="mt-1 text-xs text-slate-500">Over the last {c.days} trading days. Red = move together, blue = move opposite, white = unrelated.</p>
    </div>
  );
}

function Stat({ label, value, tip, sub }: { label: string; value: string; tip?: string; sub?: string }) {
  return (
    <div className="rounded border border-slate-200 p-2 dark:border-slate-800" title={tip}>
      <div className="text-xs text-slate-500">{label}</div>
      <div className="text-lg font-semibold tabular-nums">{value}</div>
      {sub && <div className="text-[11px] text-slate-500">{sub}</div>}
      {tip && <div className="mt-0.5 text-[10px] leading-snug text-slate-400">{tip}</div>}
    </div>
  );
}

function Dcf({ f, symbol }: { f: Fundamentals; symbol: string }) {
  const d = f.dcf_defaults;
  const [p, setP] = useState(d);
  const [qs, setQs] = useState("");
  useEffect(() => { setP(d); setQs(""); }, [symbol, d.r, d.g1]);   // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    const id = setTimeout(() => setQs(`?r=${p.r}&g1=${p.g1}&g2=${p.g2}&years=${p.years}`), 250);
    return () => clearTimeout(id);
  }, [p]);
  const q = useQuery({ queryKey: ["fund-dcf", symbol, qs], queryFn: () => api.fundamentals(symbol, qs), placeholderData: (x) => x, retry: false });
  const cur = q.data ?? f;
  const dc = cur.dcf;
  const slider = (k: "r" | "g1" | "g2", label: string, min: number, max: number, step: number, hint: string) => (
    <label className="block text-sm">
      <span className="flex justify-between"><span>{label}</span><b className="tabular-nums">{(p[k] * 100).toFixed(1)}%</b></span>
      <input type="range" min={min} max={max} step={step} value={p[k]} onChange={(e) => setP({ ...p, [k]: Number(e.target.value) })} className="w-full" aria-label={label} />
      <span className="text-[11px] text-slate-500">{hint}</span>
    </label>
  );
  return (
    <section className={card} data-tour="dcf">
      <h2 className="text-lg font-semibold">Discounted cash flow (editable)</h2>
      <p className="mb-3 text-xs text-slate-500">Projects free cash flow, then discounts it to today. Treat the answer as a way to test assumptions, not as a price target. Drag the sliders and watch how fragile it is.</p>
      <div className="grid gap-6 md:grid-cols-2">
        <div className="space-y-3">
          {slider("r", "Discount rate", 0.06, 0.20, 0.005, "How much return you demand. Higher = lower value today.")}
          {slider("g1", "Growth, next years", -0.05, 0.30, 0.005, "Yearly growth of free cash flow for the projection years.")}
          {slider("g2", "Long-run growth", 0, 0.08, 0.0025, "Growth forever after that. Must stay below the discount rate.")}
          <label className="block text-sm"><span className="flex justify-between"><span>Projection years</span><b>{p.years}</b></span>
            <input type="range" min={3} max={15} step={1} value={p.years} onChange={(e) => setP({ ...p, years: Number(e.target.value) })} className="w-full" aria-label="Projection years" /></label>
          <button onClick={() => setP(d)} className="text-xs underline">Reset to defaults (growth taken from last year&apos;s revenue growth, clamped 2–20%)</button>
        </div>
        <div>
          {q.error && <p role="alert" className="mb-2 rounded bg-amber-50 p-2 text-sm text-amber-900 dark:bg-amber-950 dark:text-amber-200">{(q.error as Error).message.includes("greater than terminal") ? "The discount rate must be higher than the long-run growth rate." : (q.error as Error).message}</p>}
          {dc.intrinsic_per_share === null ? (
            <p className="text-sm text-slate-500">No DCF value: {dc.reason ?? "missing data"}. (Free cash flow is {dc.fcf0 === null ? "unknown" : dc.fcf0 <= 0 ? "not positive" : "ok"}.)</p>
          ) : (
            <>
              <p className="text-sm text-slate-500">Estimated value per share</p>
              <p className="text-3xl font-bold tabular-nums">{f.currency === "INR" ? "₹" : ""}{dc.intrinsic_per_share.toLocaleString("en-IN", { maximumFractionDigits: 0 })}</p>
              <p className="text-sm">vs price {f.price?.toLocaleString("en-IN", { maximumFractionDigits: 2 })}
                {dc.upside_pct !== null && dc.upside_pct !== undefined && <b className={dc.upside_pct >= 0 ? "text-up" : "text-down"}> ({dc.upside_pct >= 0 ? "+" : ""}{dc.upside_pct}%)</b>}</p>
              <p className="mt-1 text-xs text-slate-500">{dc.terminal_share_pct}% of this value comes from the far-future terminal term. {dc.note}</p>
            </>
          )}
          {cur.dcf_sensitivity.length > 0 && (
            <div className="mt-3 overflow-x-auto">
              <table className="w-full text-xs tabular-nums"><caption className="text-left text-slate-500">Same estimate under nearby assumptions (rows: discount rate, columns: growth)</caption>
                <thead><tr><th />{Array.from(new Set(cur.dcf_sensitivity.map((s) => s.g1))).sort((a, b) => a - b).map((g) => <th key={g} className="p-1 font-medium">{(g * 100).toFixed(1)}%</th>)}</tr></thead>
                <tbody>{Array.from(new Set(cur.dcf_sensitivity.map((s) => s.r))).sort((a, b) => a - b).map((r) => (
                  <tr key={r}><th className="p-1 text-right font-medium">{(r * 100).toFixed(1)}%</th>
                    {Array.from(new Set(cur.dcf_sensitivity.map((s) => s.g1))).sort((a, b) => a - b).map((g) => {
                      const c = cur.dcf_sensitivity.find((s) => s.r === r && s.g1 === g);
                      return <td key={g} className="p-1 text-center">{c?.intrinsic == null ? "–" : Math.round(c.intrinsic).toLocaleString("en-IN")}</td>;
                    })}</tr>))}</tbody></table>
            </div>
          )}
        </div>
      </div>
    </section>
  );
}

function View() {
  const symbol = decodeURIComponent(String(useParams().symbol)).toUpperCase();
  const qc = useQueryClient();
  const [rf, setRf] = useState(0.07);
  const fund = useQuery({ queryKey: ["fund", symbol], queryFn: () => api.fundamentals(symbol), retry: false });
  const risk = useQuery({ queryKey: ["risk", symbol, rf], queryFn: () => api.risk(symbol, rf), retry: false, placeholderData: (x) => x });
  const corr = useQuery({ queryKey: ["corr"], queryFn: api.correlation, retry: false });
  const refresh = useMutation({ mutationFn: () => api.refreshFundamentals(symbol), onSuccess: () => { qc.invalidateQueries({ queryKey: ["fund"] }); qc.invalidateQueries({ queryKey: ["scorecard"] }); } });
  const f = fund.data;
  const s = risk.data?.summary;
  const vb = s?.vs_benchmark;

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-3">
        <h1 className="text-2xl font-semibold">{symbol}</h1>
        {f && <span className="rounded bg-slate-200 px-2 py-0.5 text-xs dark:bg-slate-800">{f.sector || "sector unknown"} · data {f.stale_days} days old</span>}
        <button data-tour="fund-refresh" onClick={() => refresh.mutate()} disabled={refresh.isPending} className="ml-auto rounded bg-indigo-600 px-3 py-1 text-sm text-white disabled:opacity-50">
          {refresh.isPending ? "Fetching…" : "Fetch / refresh fundamentals"}</button>
      </div>
      <SymbolTabs />
      {refresh.data && <p role="status" className="rounded border border-slate-300 p-2 text-sm dark:border-slate-700">Found {refresh.data.fields_found} of {refresh.data.fields_total} statement fields{refresh.data.has_prior_year ? "" : " (no prior year, so growth and some scores are unavailable)"}.</p>}
      {refresh.error && <p role="alert" className="rounded border border-red-400 bg-red-50 p-2 text-sm text-red-800 dark:bg-red-950 dark:text-red-200">Could not fetch fundamentals: {(refresh.error as Error).message}. Yahoo may be unreachable from your network.</p>}

      {fund.error && !f && (
        <div className={card}><p className="text-sm">No fundamentals stored for {symbol} yet. Click <b>Fetch / refresh fundamentals</b>. They come from Yahoo Finance statements (free, sometimes incomplete). The risk section below only needs prices.</p></div>
      )}

      {f && (
        <>
          {f.notes.map((n) => <p key={n} className="rounded bg-amber-50 p-2 text-xs text-amber-900 dark:bg-amber-950 dark:text-amber-200">{n}</p>)}
          <section className={card} data-tour="ratios">
            <h2 className="mb-2 text-lg font-semibold">Key ratios</h2>
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead className="text-left text-slate-500"><tr><th>Ratio</th><th>Value</th><th>Versus sector peers</th><th>What it means</th></tr></thead>
                <tbody>{RATIOS.map((r) => (
                  <tr key={r.key} className="border-t border-slate-200 align-top dark:border-slate-800">
                    <td className="py-1.5 pr-3 font-medium">{r.label}</td>
                    <td className="pr-3 tabular-nums">{fmtVal(f.ratios[r.key], r.fmt)}</td>
                    <td className="pr-3"><PctBar p={f.percentiles[r.key]} metric={r.label} /></td>
                    <td className="py-1.5 text-xs text-slate-600 dark:text-slate-400">{r.meaning} <span className="text-slate-400">{r.good}</span></td>
                  </tr>))}</tbody>
              </table>
            </div>
          </section>

          <div className="grid gap-3 md:grid-cols-3" data-tour="scores">
            <section className={card}>
              <h3 className="font-semibold">Piotroski F-score</h3>
              <p className="text-2xl font-bold tabular-nums">{f.piotroski.score}<span className="text-sm font-normal text-slate-500"> / {f.piotroski.out_of} ({f.piotroski.evaluated} checkable)</span></p>
              <p className="mb-1 text-xs text-slate-500">{f.piotroski.reading}. Nine yes/no accounting health checks.</p>
              <ul className="space-y-0.5 text-xs">{f.piotroski.criteria.map((c) => (
                <li key={c.id} className="flex gap-1.5"><span className={c.result === "pass" ? "text-up" : c.result === "fail" ? "text-down" : "text-slate-400"} aria-label={c.result}>{c.result === "pass" ? "✔" : c.result === "fail" ? "✘" : "–"}</span>{c.label}</li>))}</ul>
            </section>
            <section className={card}>
              <h3 className="font-semibold">Altman Z-score</h3>
              {f.altman.applicable ? (
                <>
                  <p className="text-2xl font-bold tabular-nums">{f.altman.z ?? "n/a"}{f.altman.zone && <span className={`ml-2 rounded px-2 py-0.5 text-sm font-medium text-white ${f.altman.zone === "safe" ? "bg-green-600" : f.altman.zone === "distress" ? "bg-red-600" : "bg-amber-500"}`}>{f.altman.zone}</span>}</p>
                  <p className="mt-1 text-xs text-slate-500">Bankruptcy-risk score for non-financial companies. Above 2.99 safe, 1.81 to 2.99 grey, below 1.81 distress. {f.altman.note}</p>
                </>
              ) : <p className="text-sm text-slate-500">{f.altman.note}</p>}
            </section>
            <section className={card}>
              <h3 className="font-semibold">Graham number</h3>
              {f.graham.value ? (
                <>
                  <p className="text-2xl font-bold tabular-nums">{f.graham.value.toLocaleString("en-IN")}</p>
                  <p className="text-xs text-slate-500">A conservative &apos;fair price&apos; ceiling: square root of 22.5 × earnings per share × book value per share. Price is {f.graham.price_vs_graham !== null && f.graham.price_vs_graham !== undefined ? `${pct(Math.abs(f.graham.price_vs_graham), 0)} ${f.graham.price_vs_graham < 0 ? "below" : "above"}` : "n/a vs"} it.</p>
                </>
              ) : <p className="text-sm text-slate-500">{f.graham.note}</p>}
            </section>
          </div>
          <Dcf f={f} symbol={symbol} />
        </>
      )}

      <section className="space-y-3" aria-label="Risk">
        <div className="flex flex-wrap items-center gap-3">
          <h2 className="text-lg font-semibold">Risk and performance</h2>
          <label className="ml-auto text-sm">Risk-free rate <input type="number" step="0.005" min={0} max={0.3} value={rf} onChange={(e) => setRf(Math.max(0, Math.min(0.3, Number(e.target.value))))}
            className="w-20 rounded border border-slate-300 bg-white px-1 dark:border-slate-700 dark:bg-slate-900" aria-label="Risk-free rate" /> <span className="text-xs text-slate-500">(assumption; moves Sharpe, Sortino, alpha)</span></label>
        </div>
        {risk.error && !s && <Err e={risk.error} />}
        {risk.data?.notes.map((n) => <p key={n} className="rounded bg-amber-50 p-2 text-xs text-amber-900 dark:bg-amber-950 dark:text-amber-200">{n}</p>)}
        {s && (
          <>
            <div className="grid grid-cols-2 gap-2 md:grid-cols-4" data-tour="risk-cards">
              <Stat label="Yearly return (CAGR)" value={pct(s.cagr)} tip={RISK_TIPS.cagr} sub={`${s.first} to ${s.last}`} />
              <Stat label="Volatility (annual)" value={pct(s.volatility_annual)} tip={RISK_TIPS.volatility} />
              <Stat label="Sharpe" value={num(s.sharpe)} tip={RISK_TIPS.sharpe} />
              <Stat label="Sortino" value={num(s.sortino)} tip={RISK_TIPS.sortino} />
              <Stat label="Max drawdown" value={pct(s.max_drawdown)} tip={RISK_TIPS.maxdd} sub={`${s.max_drawdown_peak} → ${s.max_drawdown_trough}`} />
              <Stat label="Calmar" value={num(s.calmar)} tip={RISK_TIPS.calmar} />
              <Stat label={`Beta vs ${risk.data?.benchmark ?? "benchmark"}`} value={num(vb?.beta)} tip={RISK_TIPS.beta} sub={vb ? `${vb.n} days` : undefined} />
              <Stat label="Alpha (annual)" value={pct(vb?.alpha_annual)} tip={RISK_TIPS.alpha} sub={vb ? `correlation ${num(vb.correlation)} · R² ${num(vb.r_squared)}` : undefined} />
            </div>
            <div className="grid gap-2 md:grid-cols-2">
              {(["var_95", "var_99"] as const).map((k) => (
                <div key={k} className={card}>
                  <h3 className="font-semibold">One-day loss on the worst {k === "var_95" ? "5%" : "1%"} of days</h3>
                  <table className="mt-1 w-full text-sm tabular-nums"><tbody>
                    <tr><td className="text-slate-500">VaR, historical</td><td>{pct(s[k].historical_var, 2)}</td><td className="text-slate-500">CVaR, historical</td><td>{pct(s[k].historical_cvar, 2)}</td></tr>
                    <tr><td className="text-slate-500">VaR, normal-model</td><td>{pct(s[k].parametric_var, 2)}</td><td className="text-slate-500">CVaR, normal-model</td><td>{pct(s[k].parametric_cvar, 2)}</td></tr>
                  </tbody></table>
                  <p className="mt-1 text-[11px] text-slate-500">{RISK_TIPS.var} {RISK_TIPS.cvar} The normal-model figures assume a bell curve and usually understate real tail losses.</p>
                </div>
              ))}
            </div>
            <div className="grid gap-4 md:grid-cols-2">
              <div className={card} data-tour="drawdown">
                <h3 className="font-semibold">Underwater chart (drawdown)</h3>
                <SvgLine dates={risk.data!.series.dates} values={risk.data!.series.drawdown} color="#dc2626" area fmt={(v) => `${(v * 100).toFixed(0)}%`} label="Drawdown from previous peak" />
                <p className="text-xs text-slate-500">How far below its previous high the stock was each day. Longest stretch without a new high: {s.longest_drawdown_bars} trading days; right now: {pct(s.current_drawdown)} for {s.current_drawdown_bars} days.</p>
              </div>
              <div className={card} data-tour="rolling-beta">
                <h3 className="font-semibold">Rolling beta ({risk.data!.window}-day window)</h3>
                {risk.data!.series.beta ? <SvgLine dates={risk.data!.series.dates} values={risk.data!.series.beta} color="#6366f1" zero={false} label="Rolling beta" />
                  : <p className="text-sm text-slate-500">Needs benchmark prices (run make seed).</p>}
                <h3 className="mt-2 font-semibold">Rolling correlation</h3>
                {risk.data!.series.correlation && <SvgLine dates={risk.data!.series.dates} values={risk.data!.series.correlation} color="#0ea5e9" zero={false} height={110} label="Rolling correlation" />}
                <p className="text-xs text-slate-500">Each point uses only the previous {risk.data!.window} days.</p>
              </div>
              <div className={card}>
                <h3 className="font-semibold">Rolling Sharpe</h3>
                <SvgLine dates={risk.data!.series.dates} values={risk.data!.series.sharpe} color="#16a34a" label="Rolling Sharpe ratio" />
              </div>
              <div className={card}>
                <h3 className="font-semibold">Growth of 100 invested</h3>
                <SvgLine dates={risk.data!.series.dates} values={risk.data!.series.equity} color="#f59e0b" zero={false} fmt={(v) => v.toFixed(0)} label="Equity curve" />
              </div>
            </div>
            {s.kelly && (
              <div className="rounded border-2 border-amber-400 bg-amber-50 p-3 text-sm dark:bg-amber-950" data-tour="kelly" role="note">
                <h3 className="font-semibold">Kelly fraction (display only): {s.kelly.full === null ? "n/a" : s.kelly.full.toFixed(2)} (half-Kelly {s.kelly.half === null ? "n/a" : s.kelly.half.toFixed(2)})</h3>
                <p className="mt-1">{s.kelly.warning}</p>
              </div>
            )}
          </>
        )}
        <div className={card}>
          <h3 className="mb-2 font-semibold">Correlation across your watchlist</h3>
          <div data-tour="correlation">
            {corr.data ? <Heat c={corr.data} /> : <p className="text-sm text-slate-500">{corr.error ? (corr.error as Error).message : "Loading…"}</p>}
          </div>
        </div>
      </section>
      <p className="text-xs text-slate-500">All figures describe the past and depend on data quality and your assumptions. Educational tool, not investment advice.</p>
    </div>
  );
}

export default function Page() { return <Suspense fallback={<div className="skeleton h-96" />}><View /></Suspense>; }
