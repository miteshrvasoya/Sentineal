"use client";
import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { useParams } from "next/navigation";
import { api } from "@/lib/api";

export default function Watchlist() {
  const active = useParams().symbol ? decodeURIComponent(String(useParams().symbol)).toUpperCase() : "";
  const wl = useQuery({ queryKey: ["watchlist"], queryFn: api.watchlist });
  return (
    <nav aria-label="Watchlist">
      <h2 className="mb-2 text-xs font-semibold uppercase text-slate-500">Watchlist</h2>
      {wl.isLoading && <div className="space-y-1">{Array.from({ length: 6 }).map((_, i) => <div key={i} className="skeleton h-6" />)}</div>}
      {wl.error && <p className="text-xs text-red-500">{(wl.error as Error).message}</p>}
      <ul className="space-y-0.5">
        {wl.data?.map((s) => (
          <li key={s}><Link href={`/s/${encodeURIComponent(s)}`}
            className={`block rounded px-2 py-1 text-sm hover:bg-slate-200 dark:hover:bg-slate-800 ${s === active ? "bg-indigo-100 font-semibold dark:bg-indigo-950" : ""}`}>{s}</Link></li>
        ))}
      </ul>
    </nav>
  );
}
