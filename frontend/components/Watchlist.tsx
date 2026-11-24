"use client";
import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { useParams } from "next/navigation";
import { api, type WatchRow } from "@/lib/api";

function Spark({ v, up }: { v: number[]; up: boolean }) {
  if (v.length < 2) return <span className="inline-block h-5 w-16" />;
  const lo = Math.min(...v), hi = Math.max(...v), span = hi - lo || 1;
  const pts = v.map((x, i) => `${(i / (v.length - 1)) * 62 + 1},${(1 - (x - lo) / span) * 18 + 1}`).join(" ");
  return <svg viewBox="0 0 64 20" className="h-5 w-16" aria-hidden><polyline points={pts} fill="none" stroke={up ? "#16a34a" : "#dc2626"} strokeWidth="1.5" /></svg>;
}

const badge = (r: WatchRow) =>
  r.score === null ? "bg-slate-300 dark:bg-slate-700" : r.score >= 25 ? "bg-green-600" : r.score <= -25 ? "bg-red-600" : "bg-slate-400";

export default function Watchlist() {
  const params = useParams();
  const active = params.symbol ? decodeURIComponent(String(params.symbol)).toUpperCase() : "";
  const wl = useQuery({ queryKey: ["watchsummary"], queryFn: api.watchSummary, refetchInterval: 120_000 });
  return (
    <nav aria-label="Watchlist">
      <h2 className="mb-2 text-xs font-semibold uppercase text-slate-500">Watchlist</h2>
      {wl.isLoading && <div className="space-y-1">{Array.from({ length: 6 }).map((_, i) => <div key={i} className="skeleton h-8" />)}</div>}
      {wl.error && <p className="text-xs text-red-500">{(wl.error as Error).message}</p>}
      <ul className="space-y-0.5">
        {wl.data?.map((r) => (
          <li key={r.symbol}>
            <Link href={`/s/${encodeURIComponent(r.symbol)}`}
              className={`flex items-center gap-2 rounded px-2 py-1 text-sm hover:bg-slate-200 dark:hover:bg-slate-800 ${r.symbol === active ? "bg-indigo-100 font-semibold dark:bg-indigo-950" : ""}`}>
              <span className="min-w-0 flex-1">
                <span className="block truncate">{r.symbol}</span>
                {r.last !== null && (
                  <span className="block text-[11px] tabular-nums text-slate-500">
                    {r.last.toLocaleString("en-IN")}{" "}
                    <span className={(r.change_pct ?? 0) >= 0 ? "text-up" : "text-down"}>{(r.change_pct ?? 0) >= 0 ? "+" : ""}{r.change_pct?.toFixed(2)}%</span>
                  </span>
                )}
              </span>
              <Spark v={r.spark} up={(r.change_pct ?? 0) >= 0} />
              <span className={`h-2.5 w-2.5 shrink-0 rounded-full ${badge(r)}`} title={r.label ? `Scorecard: ${r.label} (${r.score})` : "Scorecard: not enough data"} aria-label={r.label ?? "no scorecard"} />
            </Link>
          </li>
        ))}
      </ul>
      <p className="mt-2 text-[10px] text-slate-400">Dot = scorecard: green leaning positive, red negative, grey mixed or no data.</p>
    </nav>
  );
}
