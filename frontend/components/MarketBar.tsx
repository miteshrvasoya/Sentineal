"use client";
import { useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";

function Chip({ label, q }: { label: string; q?: { last: number; change_pct: number } | null }) {
  if (!q) return <span className="text-xs text-slate-500">{label} n/a</span>;
  return (
    <span className="text-xs tabular-nums">{label} {q.last.toFixed(2)}{" "}
      <span className={q.change_pct >= 0 ? "text-up" : "text-down"}>{q.change_pct >= 0 ? "+" : ""}{q.change_pct.toFixed(2)}%</span>
    </span>
  );
}

export default function MarketBar() {
  const health = useQuery({ queryKey: ["health"], queryFn: api.health, refetchInterval: 60_000 });
  const idx = useQuery({ queryKey: ["indices"], queryFn: api.indices, refetchInterval: 60_000 });
  const [now, setNow] = useState("");
  useEffect(() => {
    const tick = () => setNow(new Date().toLocaleTimeString("en-IN", { timeZone: "Asia/Kolkata", hour12: false }));
    tick();
    const id = setInterval(tick, 1000);
    return () => clearInterval(id);
  }, []);
  const state = health.data?.market.state;
  const color = state === "open" ? "bg-green-600" : state === "pre-open" ? "bg-amber-500" : "bg-slate-500";
  return (
    <div className="flex items-center gap-3">
      {health.error ? <span className="text-xs text-red-500">backend offline</span> : (
        <span className={`rounded px-2 py-0.5 text-xs text-white ${color}`}>NSE {state ?? "…"}</span>
      )}
      <span className="text-xs tabular-nums text-slate-500">{now} IST</span>
      <Chip label="NIFTY" q={idx.data?.nifty} />
      <Chip label="VIX" q={idx.data?.vix} />
    </div>
  );
}
