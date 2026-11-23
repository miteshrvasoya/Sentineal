"use client";
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { api } from "@/lib/api";

const ts = (t: number | null) => (t ? new Date(t * 1000).toLocaleString("en-IN", { timeZone: "Asia/Kolkata" }) : "never");
const sev = { error: "text-red-600", warn: "text-amber-600", info: "text-slate-500" } as const;

export default function Settings() {
  const prov = useQuery({ queryKey: ["providers"], queryFn: api.providers, refetchInterval: 15_000 });
  const [sym, setSym] = useState("RELIANCE");
  const [go, setGo] = useState("RELIANCE");
  const dq = useQuery({ queryKey: ["dq", go], queryFn: () => api.quality(go) });
  return (
    <div className="space-y-8">
      <section>
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
      <section>
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
