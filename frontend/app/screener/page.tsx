"use client";
import { useMutation, useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { Suspense, useState } from "react";
import { api, type ScreenCond, type ScreenField, type ScreenRow } from "@/lib/api";

const card = "rounded border border-slate-200 p-3 dark:border-slate-800";
const input = "rounded border border-slate-300 bg-white px-1 py-0.5 text-sm dark:border-slate-700 dark:bg-slate-900";

function fmt(f: ScreenField | undefined, v: unknown): string {
  if (v === null || v === undefined) return "";
  if (typeof v === "boolean") return v ? "yes" : "no";
  if (typeof v === "string") return v;
  const n = Number(v);
  switch (f?.unit) {
    case "pct": return `${(n * 100).toFixed(1)}%`;
    case "price": return n.toFixed(2);
    case "x": return n.toFixed(2);
    default: return n.toFixed(1);
  }
}

type Draft = { field: string; op: string; value: string };

function View() {
  const meta = useQuery({ queryKey: ["screenfields"], queryFn: api.screenFields });
  const [conds, setConds] = useState<Draft[]>([{ field: "rs_rank_126", op: ">=", value: "70" }]);
  const [sort, setSort] = useState("rs_rank_126");
  const [desc, setDesc] = useState(true);
  const fields = meta.data?.fields ?? [];
  const fmap = new Map(fields.map((f) => [f.key, f]));
  const toApi = (d: Draft): ScreenCond => {
    const f = fmap.get(d.field);
    if (f?.kind === "bool") return { field: d.field, op: d.op, value: d.value === "true" };
    if (f?.kind === "text") return { field: d.field, op: d.op, value: d.op === "in" ? d.value.split(",").map((s) => s.trim()).filter(Boolean) : d.value };
    if (d.op === "between") return { field: d.field, op: d.op, value: d.value.split(",").map(Number) };
    // percentage-type fields are shown as percent in the UI but stored as fractions
    return { field: d.field, op: d.op, value: Number(d.value) / (f?.unit === "pct" ? 100 : 1) };
  };
  const run = useMutation({ mutationFn: (c: Draft[]) => api.screenRun(c.map(toApi), sort, desc) });
  const fromApi = (c: ScreenCond): Draft => {
    const f = fmap.get(c.field);
    const v = c.value;
    const show = (x: unknown) => (f?.unit === "pct" && typeof x === "number" ? String(+(x * 100).toFixed(4)) : String(x));
    return { field: c.field, op: c.op, value: Array.isArray(v) ? v.map(show).join(",") : show(v) };
  };
  const set = (i: number, patch: Partial<Draft>) => setConds((cs) => cs.map((c, j) => (j === i ? { ...c, ...patch } : c)));
  const cols = ["rs_rank_126", "ret_21d", "ret_126d", "rsi", "close_vs_sma200", "pct_from_52w_high", "rvol", "composite", "pe", "roe"];
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-3"><h1 className="text-2xl font-semibold">Screener</h1>
        <span className="rounded bg-violet-600 px-2 py-0.5 text-xs text-white">A filter on today&apos;s numbers, not a forecast</span></div>
      <section className={card} data-tour="screen-presets">
        <h2 className="mb-1 text-sm font-semibold">Start from an idea</h2>
        <div className="flex flex-wrap gap-2">{meta.data?.presets.map((p) => (
          <button key={p.id} title={p.idea} onClick={() => { const d = p.conditions.map(fromApi); setConds(d); run.mutate(d); }}
            className="rounded border border-slate-300 px-2 py-1 text-sm hover:bg-slate-100 dark:border-slate-700 dark:hover:bg-slate-800">{p.title}</button>))}</div>
      </section>
      <section className={card} data-tour="screen-builder">
        <h2 className="mb-1 text-sm font-semibold">Conditions (all must be true)</h2>
        <div className="space-y-1">{conds.map((c, i) => {
          const f = fmap.get(c.field);
          const ops = f?.kind === "bool" ? ["=="] : f?.kind === "text" ? ["==", "!=", "in"] : (meta.data?.ops ?? []).filter((o) => o !== "in");
          return (
            <div key={i} className="flex flex-wrap items-center gap-1 text-sm">
              <select value={c.field} onChange={(e) => { const nf = fmap.get(e.target.value); set(i, { field: e.target.value, op: nf?.kind === "text" ? "in" : nf?.kind === "bool" ? "==" : ">=", value: nf?.kind === "bool" ? "true" : "" }); }} className={input} aria-label="Field">
                {Array.from(new Set(fields.map((x) => x.group))).map((g) => <optgroup key={g} label={g}>{fields.filter((x) => x.group === g).map((x) => <option key={x.key} value={x.key}>{x.label}</option>)}</optgroup>)}</select>
              <select value={c.op} onChange={(e) => set(i, { op: e.target.value })} className={input} aria-label="Operator">{ops.map((o) => <option key={o}>{o}</option>)}</select>
              {f?.kind === "bool" ? <select value={c.value} onChange={(e) => set(i, { value: e.target.value })} className={input}><option value="true">yes</option><option value="false">no</option></select>
                : <input value={c.value} onChange={(e) => set(i, { value: e.target.value })} className={`${input} w-40`} aria-label="Value" placeholder={f?.kind === "text" ? "IT, Banks" : c.op === "between" ? "low,high" : f?.unit === "pct" ? "number in %" : "number"} />}
              <button onClick={() => setConds((cs) => cs.filter((_, j) => j !== i))} className="px-1 text-slate-500 hover:text-red-600" aria-label="Remove condition">✕</button>
              {f && <span className="text-xs text-slate-500">{f.desc}</span>}
            </div>);
        })}</div>
        <div className="mt-2 flex flex-wrap items-center gap-2 text-sm">
          <button onClick={() => setConds((c) => [...c, { field: "rsi", op: "<", value: "" }])} className="rounded border border-slate-300 px-2 py-0.5 dark:border-slate-700">+ condition</button>
          <label>sort by <select value={sort} onChange={(e) => setSort(e.target.value)} className={input}>{fields.filter((f) => f.kind === "number").map((f) => <option key={f.key} value={f.key}>{f.label}</option>)}</select></label>
          <label className="flex items-center gap-1"><input type="checkbox" checked={desc} onChange={(e) => setDesc(e.target.checked)} />high first</label>
          <button onClick={() => run.mutate(conds)} disabled={run.isPending} className="ml-auto rounded bg-indigo-600 px-3 py-1 text-white disabled:opacity-50">{run.isPending ? "Screening…" : "Run screen"}</button>
        </div>
        {run.error && <p className="mt-2 text-sm text-red-600" role="alert">{(run.error as Error).message}</p>}
      </section>
      {run.data && (
        <section className={card} data-tour="screen-results">
          <h2 className="text-lg font-semibold">{run.data.matches} of {run.data.universe} stocks match</h2>
          {Object.keys(run.data.missing_data).length > 0 && <p className="text-xs text-amber-600">Stocks lacking data for a condition never match it: {Object.entries(run.data.missing_data).map(([k, v]) => `${fmap.get(k)?.label ?? k} (${v} missing)`).join(", ")}.</p>}
          <div className="mt-1 overflow-x-auto"><table className="w-full text-xs tabular-nums"><thead className="text-left text-slate-500"><tr><th>Stock</th><th>Sector</th>{cols.map((k) => <th key={k} title={fmap.get(k)?.desc}>{fmap.get(k)?.label}</th>)}</tr></thead>
            <tbody>{run.data.rows.map((r: ScreenRow) => (
              <tr key={r.symbol} className="border-t border-slate-200 dark:border-slate-800"><td className="py-1"><Link href={`/s/${r.symbol}`} className="font-medium text-indigo-600 hover:underline dark:text-indigo-300">{r.symbol}</Link></td><td>{r.sector}</td>
                {cols.map((k) => <td key={k}>{fmt(fmap.get(k), r[k])}</td>)}</tr>))}</tbody></table></div>
          <p className="mt-2 text-xs text-slate-500">{run.data.disclaimer} Whether a filter like this ever picked winners is a question for the Backtest and Model Lab tabs.</p>
        </section>)}
    </div>
  );
}

export default function Page() { return <Suspense fallback={<div className="skeleton h-96" />}><View /></Suspense>; }
