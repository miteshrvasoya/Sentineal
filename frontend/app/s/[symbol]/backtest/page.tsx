"use client";
import { useMutation, useQuery } from "@tanstack/react-query";
import { useParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";
import { AiFooter, AiStatus, ClaimList } from "@/components/AiParts";
import { MultiLine } from "@/components/ModelCharts";
import SymbolTabs from "@/components/SymbolTabs";
import { api, type BacktestOut, type BtBoot } from "@/lib/api";
import { pct } from "@/lib/explain";

const card = "rounded border border-slate-200 p-3 dark:border-slate-800";
const inr = (v: number) => `₹${Math.round(v).toLocaleString("en-IN")}`;
const sg = (v: number | null | undefined, d = 1) => (v === null || v === undefined ? "n/a" : `${v >= 0 ? "+" : ""}${(v * 100).toFixed(d)}%`);
const num = (v: number | null | undefined, d = 2) => (v === null || v === undefined ? "n/a" : v.toFixed(d));

function Hist({ b }: { b: BtBoot }) {
  if (!b.available || !b.hist) return <p className="text-sm text-slate-500">{b.reason ?? "Not enough data."}</p>;
  const { counts, edges } = b.hist, W = 320, H = 110, mx = Math.max(...counts);
  const x = (v: number) => 8 + ((v - edges[0]) / (edges[edges.length - 1] - edges[0])) * (W - 16);
  const lo = b.sharpe_ci90![0], hi = b.sharpe_ci90![1];
  return (
    <svg viewBox={`0 0 ${W} ${H + 18}`} role="img" aria-label="Bootstrap distribution of the Sharpe ratio" className="w-full max-w-md">
      {counts.map((c, i) => <rect key={i} x={x(edges[i])} y={H - (c / mx) * (H - 6)} width={Math.max(1, x(edges[i + 1]) - x(edges[i]) - 1)} height={(c / mx) * (H - 6)} fill="#6366f1" opacity={edges[i] >= lo && edges[i + 1] <= hi ? 0.9 : 0.35} />)}
      {edges[0] < 0 && edges[edges.length - 1] > 0 && <><line x1={x(0)} x2={x(0)} y1={0} y2={H} stroke="#dc2626" strokeDasharray="3 3" /><text x={x(0) + 3} y={10} fontSize="9" fill="#dc2626">0 = no skill</text></>}
      <text x={W / 2} y={H + 13} fontSize="9" textAnchor="middle" fill="currentColor" opacity="0.7">Sharpe ratio across {b.reps} resampled histories (dark = middle 90%)</text>
    </svg>
  );
}

const Stat = ({ k, v, tip }: { k: string; v: string; tip?: string }) => <div title={tip} className="rounded bg-slate-100 px-2 py-1 dark:bg-slate-800"><div className="text-[10px] uppercase tracking-wide text-slate-500">{k}</div><div className="tabular-nums font-medium">{v}</div></div>;

function Result({ r, symbol }: { r: BacktestOut; symbol: string }) {
  const m = r.metrics, bh = r.buy_hold, ho = r.held_out;
  const review = useMutation({ mutationFn: () => api.aiBacktestReview(`${r.strategy} ${JSON.stringify(r.params)} on ${symbol}`, r.reviewer_input) });
  const rv = review.data?.report;
  const bad = r.verdict.label !== "survives these tests";
  const judge = ho ? ho.bootstrap_oos : r.bootstrap;
  return (
    <div className="space-y-4">
      <section className={`${card} ${bad ? "border-amber-500" : "border-green-600"}`} data-tour="bt-verdict">
        <div className="flex flex-wrap items-center gap-2"><h2 className="text-lg font-semibold">Verdict</h2>
          <span className={`rounded px-2 py-0.5 text-xs text-white ${bad ? "bg-slate-600" : "bg-green-600"}`}>{r.verdict.label}</span>
          <span className="text-xs text-slate-500">{r.strategy} {JSON.stringify(r.params)}, {r.first_trade_allowed} to {r.last_bar}</span></div>
        {r.verdict.reasons.length > 0 && <ul className="mt-1 list-disc pl-5 text-sm">{r.verdict.reasons.map((x) => <li key={x}>{x}</li>)}</ul>}
        <p className="mt-1 text-xs text-slate-500">{r.verdict.caveat}</p>
      </section>

      <section className={card}>
        <div className="grid grid-cols-2 gap-2 text-sm sm:grid-cols-4 lg:grid-cols-6">
          <Stat k="Strategy return" v={sg(m.total_return)} tip="Total return after costs and slippage" />
          <Stat k="Buy & hold" v={sg(bh.total_return)} tip="Buying at the same start and holding, paying the same costs" />
          <Stat k="Return before costs" v={sg(r.no_cost.total_return)} />
          <Stat k="CAGR" v={sg(m.cagr)} tip="Compound annual growth rate" />
          <Stat k="Sharpe" v={num(m.sharpe)} tip="Excess return over the risk-free rate per unit of volatility, annualised" />
          <Stat k="Max drawdown" v={sg(m.max_drawdown)} tip="Worst peak-to-trough fall" />
          <Stat k="Trades" v={String(m.n_trades ?? 0)} tip="Fewer than about 30 cannot separate skill from luck" />
          <Stat k="Win rate" v={pct(m.win_rate ?? null, 0)} />
          <Stat k="Profit factor" v={num(m.profit_factor)} tip="Gross profit / gross loss of trades" />
          <Stat k="Time invested" v={pct(r.costs.exposure, 0)} />
          <Stat k="Avg days held" v={num(m.avg_bars_held, 0)} />
          <Stat k="Top-5 trades share" v={pct(m.top5_trade_share ?? null, 0)} tip="Share of total profit from the five best trades" />
        </div>
      </section>

      <div className="grid gap-4 lg:grid-cols-2">
        <section className={card} data-tour="bt-equity">
          <h3 className="font-semibold">Equity vs buy & hold (start = 100)</h3>
          <MultiLine series={[{ name: "strategy (after costs)", color: "#6366f1", points: r.series.equity }, { name: "buy & hold", color: "#64748b", dashed: true, points: r.series.buy_hold }]} label="Equity curves" baseline={100} />
          {r.series.split_date && <p className="text-xs text-slate-500">Parameters were chosen only on data before {r.series.split_date}. Judge the strategy on what happens after that date.</p>}
        </section>
        <section className={card}>
          <h3 className="font-semibold">Drawdown</h3>
          <MultiLine series={[{ name: "drawdown", color: "#dc2626", points: r.series.drawdown }]} label="Drawdown" baseline={0} fmt={(v) => `${(v * 100).toFixed(0)}%`} />
          <p className="text-xs text-slate-500">How far below its previous high the account was. Can you sit through the deepest dip?</p>
        </section>
      </div>

      <section className={card} data-tour="bt-costs">
        <h3 className="font-semibold">What trading costs took</h3>
        <p className="text-sm">Charges ₹{Math.round(r.costs.total_charges).toLocaleString("en-IN")} + slippage ₹{Math.round(r.costs.slippage).toLocaleString("en-IN")} = <b>{inr(r.costs.total_drag)}</b> ({pct(r.costs.drag_pct_of_capital, 1)} of starting capital), which turned a {sg(r.no_cost.total_return)} gross result into {sg(m.total_return)}.</p>
        <div className="mt-1 flex flex-wrap gap-2 text-xs">{Object.entries(r.costs.paid).filter(([, v]) => v > 0).map(([k, v]) => <span key={k} className="rounded bg-slate-100 px-2 py-0.5 dark:bg-slate-800">{k} {inr(v)}</span>)}</div>
        <p className="mt-1 text-xs text-slate-500">STT, stamp duty, exchange and SEBI fees, GST, depository charge and brokerage, itemised per fill. Rates are editable defaults for NSE delivery trades: check your broker&apos;s current rate card.</p>
      </section>

      <section className={card} data-tour="bt-luck">
        <h3 className="font-semibold">Was it skill or luck?</h3>
        <div className="grid gap-4 md:grid-cols-2">
          <div><h4 className="mb-1 text-sm font-semibold">Bootstrap of the Sharpe ratio{ho ? " (held-out period only)" : ""}</h4><Hist b={judge} />
            {judge.available && <p className="mt-1 text-sm">Sharpe {num(judge.sharpe)}, 90% range {num(judge.sharpe_ci90![0])} to {num(judge.sharpe_ci90![1])}. Chance a zero-skill strategy does this well: <b>{num(judge.p_value, 3)}</b>{judge.trials! > 1 ? `, ${num(judge.p_adjusted, 3)} after adjusting for ${judge.trials} parameter sets tried` : ""}.</p>}</div>
          <div><h4 className="mb-1 text-sm font-semibold">Random-timing test</h4>
            {r.luck_test.available ? <p className="text-sm">Same trades, same time in the market, but random timing: this strategy&apos;s timing beat <b>{pct(r.luck_test.percentile ?? null, 0)}</b> of {r.bootstrap.reps ?? 2000} random timings (before costs). p = {num(r.luck_test.p_value, 3)}. Random timings median {num(r.luck_test.random_median, 3)} log return vs this strategy {num(r.luck_test.real_log_return, 3)}.</p> : <p className="text-sm text-slate-500">{r.luck_test.reason}</p>}
            <p className="mt-1 text-xs text-slate-500">Around 50% means the timing added nothing; a persistently high percentile on held-out data would be interesting.</p></div>
        </div>
      </section>

      {ho && (
        <section className={card} data-tour="bt-heldout">
          <h3 className="font-semibold">In-sample vs held-out (split {ho.split_date})</h3>
          <table className="w-full text-sm tabular-nums"><thead className="text-left text-xs text-slate-500"><tr><th></th><th>Return</th><th>Sharpe</th><th>Max drawdown</th><th>Trades</th></tr></thead><tbody>
            {([["In-sample (used to choose parameters)", ho.in_sample], ["Held-out (never used)", ho.out_of_sample], ["Buy & hold, held-out", ho.buy_hold_oos]] as const).map(([k, v]) => (
              <tr key={k} className="border-t border-slate-200 dark:border-slate-800"><td className="py-1">{k}</td><td>{sg(v.total_return)}</td><td>{num(v.sharpe)}</td><td>{sg(v.max_drawdown)}</td><td>{v.n_trades ?? ""}</td></tr>))}</tbody></table>
          <p className="mt-1 text-xs text-slate-500">Sharpe dropped by {num(ho.sharpe_drop)} out of sample. A big drop is the signature of overfitting: the rule learned the past, not a pattern.</p>
        </section>)}

      {r.search && (
        <section className={card} data-tour="bt-search">
          <h3 className="font-semibold">Parameter search: {r.search.trials} combinations tried</h3>
          <p className="text-sm">Best in-sample: {JSON.stringify(r.search.chosen)}. The more combinations you try, the better the winner looks by luck alone, so the p-value above is multiplied by {r.search.trials}.</p>
          <div className="mt-1 grid gap-3 text-xs sm:grid-cols-2"><div><b>Best 5 (in-sample Sharpe)</b>{r.search.top.map((t, i) => <div key={i} className="flex justify-between"><span className="font-mono">{JSON.stringify(t.params)}</span><span>{num(t.in_sample_sharpe)}</span></div>)}</div>
            <div><b>Worst 3</b>{r.search.worst.map((t, i) => <div key={i} className="flex justify-between"><span className="font-mono">{JSON.stringify(t.params)}</span><span>{num(t.in_sample_sharpe)}</span></div>)}</div></div>
        </section>)}

      <section className={card} data-tour="bt-trades">
        <details><summary className="cursor-pointer font-semibold">Trades ({r.trades.length}{(m.n_trades ?? 0) > r.trades.length ? ` of ${m.n_trades}, latest shown` : ""})</summary>
          <div className="mt-2 max-h-72 overflow-auto"><table className="w-full text-xs tabular-nums"><thead className="sticky top-0 bg-white text-left text-slate-500 dark:bg-slate-950"><tr><th>Entry</th><th>Exit</th><th>Qty</th><th>In</th><th>Out</th><th>Gross</th><th>Costs</th><th>Net</th><th>Return</th><th>Days</th><th>Exit</th></tr></thead>
            <tbody>{[...r.trades].reverse().map((t, i) => <tr key={i} className="border-t border-slate-200 dark:border-slate-800"><td>{t.entry_date}</td><td>{t.exit_date}</td><td>{t.qty}</td><td>{t.entry_price}</td><td>{t.exit_price}</td><td>{inr(t.gross_pnl)}</td><td>{inr(t.costs)}</td>
              <td className={t.net_pnl >= 0 ? "text-green-700 dark:text-green-400" : "text-red-600"}>{inr(t.net_pnl)}</td><td>{sg(t.return_pct)}</td><td>{t.bars}</td><td>{t.exit_reason}</td></tr>)}</tbody></table></div></details>
      </section>

      <section className={card} data-tour="bt-review">
        <div className="flex flex-wrap items-center gap-2"><h3 className="font-semibold">AI review of this backtest</h3>
          <span className="rounded bg-violet-600 px-1.5 py-0.5 text-[10px] text-white">AI-generated</span>
          <button onClick={() => review.mutate()} disabled={review.isPending} className="ml-auto rounded bg-indigo-600 px-3 py-1 text-sm text-white disabled:opacity-50">{review.isPending ? "Reviewing…" : "Review"}</button></div>
        {review.error && <p className="text-sm text-red-600" role="alert">{(review.error as Error).message}</p>}
        {review.data && review.data.red_flags.length > 0 && <ul className="mt-2 space-y-1">{review.data.red_flags.map((f) => <li key={f.id} className="border-l-2 border-red-600 pl-2 text-sm">{f.message}</li>)}</ul>}
        {review.data && <div className="mt-2"><AiStatus d={review.data} report={rv} /></div>}
        {rv && review.data && <div className="mt-2 space-y-2 text-sm"><p><b>{rv.verdict}.</b> {rv.plain_summary}</p><ClaimList title="Concerns" items={rv.concerns} facts={review.data.facts} tone="bad" /><ClaimList title="Strengths" items={rv.strengths} facts={review.data.facts} tone="good" /></div>}
        {review.data && <AiFooter d={review.data} />}
      </section>
      <ul className="list-disc pl-5 text-xs text-slate-500">{r.notes.map((n) => <li key={n}>{n}</li>)}</ul>
    </div>
  );
}

function View() {
  const symbol = decodeURIComponent(String(useParams().symbol)).toUpperCase();
  const cat = useQuery({ queryKey: ["btstrats"], queryFn: api.btStrategies });
  const [name, setName] = useState("ma_cross");
  const [params, setParams] = useState<Record<string, number>>({});
  const [preset, setPreset] = useState("india_delivery");
  const [capital, setCapital] = useState(1000000);
  const [stop, setStop] = useState("");
  const [oos, setOos] = useState(0.3);
  const [opt, setOpt] = useState(false);
  const strat = cat.data?.strategies.find((s) => s.name === name);
  useEffect(() => { if (strat) setParams({ ...strat.defaults }); }, [strat?.name]); // eslint-disable-line react-hooks/exhaustive-deps
  const run = useMutation({ mutationFn: () => api.backtest(symbol, { strategy: name, params: opt ? {} : params, cost_preset: preset, capital, stop_loss: stop ? Number(stop) / 100 : null, oos_fraction: oos, optimize: opt }) });
  const input = "rounded border border-slate-300 bg-white px-1 py-0.5 text-sm dark:border-slate-700 dark:bg-slate-900";
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-3"><h1 className="text-2xl font-semibold">{symbol}</h1>
        <span className="rounded bg-violet-600 px-2 py-0.5 text-xs text-white">Backtester: would this rule have worked, and was it luck?</span></div>
      <SymbolTabs />
      <section className={card} data-tour="bt-controls">
        <div className="flex flex-wrap items-end gap-3 text-sm">
          <label>Strategy <select value={name} onChange={(e) => setName(e.target.value)} className={input}>{cat.data?.strategies.map((s) => <option key={s.name} value={s.name}>{s.title}</option>)}</select></label>
          {!opt && strat && Object.keys(strat.defaults).map((k) => <label key={k}>{k.replace(/_/g, " ")} <input type="number" step="any" value={params[k] ?? ""} onChange={(e) => setParams((p) => ({ ...p, [k]: Number(e.target.value) }))} className={`${input} w-20`} /></label>)}
          <label>Costs <select value={preset} onChange={(e) => setPreset(e.target.value)} className={input}><option value="india_delivery">Indian delivery costs</option><option value="none">None (unrealistic)</option></select></label>
          <label>Capital ₹ <input type="number" min={10000} step={10000} value={capital} onChange={(e) => setCapital(Number(e.target.value))} className={`${input} w-28`} /></label>
          <label>Stop-loss % <input type="number" min={1} max={80} placeholder="none" value={stop} onChange={(e) => setStop(e.target.value)} className={`${input} w-20`} /></label>
          <label title="Share of the most recent history kept out of parameter selection">Held-out <select value={oos} onChange={(e) => setOos(Number(e.target.value))} className={input}>{[0, 0.2, 0.3, 0.4].map((v) => <option key={v} value={v}>{v ? `last ${v * 100}%` : "none"}</option>)}</select></label>
          <label className="flex items-center gap-1" title="Try every parameter combination on the in-sample part and pick the best (needs a held-out period)"><input type="checkbox" checked={opt} onChange={(e) => { setOpt(e.target.checked); if (e.target.checked && oos < 0.2) setOos(0.3); }} />search parameters{strat ? ` (${strat.grid_size} combos)` : ""}</label>
          <button onClick={() => run.mutate()} disabled={run.isPending || !strat} className="rounded bg-indigo-600 px-3 py-1 text-white disabled:opacity-50">{run.isPending ? "Running…" : "Run backtest"}</button>
        </div>
        {strat && <p className="mt-2 text-xs text-slate-500">{strat.description} Signals use the close of a day and fill at the next day&apos;s open, long only.</p>}
        {cat.data && <p className="text-xs text-slate-500">{cat.data.cost_note}</p>}
        {run.error && <p className="mt-2 text-sm text-red-600" role="alert">{(run.error as Error).message}</p>}
      </section>
      {run.data && <Result r={run.data} symbol={symbol} />}
      <p className="text-xs text-slate-500">Educational tool, not investment advice. A backtest shows what a rule would have done, not what it will do.</p>
    </div>
  );
}

export default function Page() { return <Suspense fallback={<div className="skeleton h-96" />}><View /></Suspense>; }
