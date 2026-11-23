"use client";
import { useQuery } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";

export default function SearchBox() {
  const [q, setQ] = useState("");
  const [dq, setDq] = useState("");
  const [open, setOpen] = useState(false);
  const router = useRouter();
  useEffect(() => { const id = setTimeout(() => setDq(q), 150); return () => clearTimeout(id); }, [q]);
  const res = useQuery({ queryKey: ["search", dq], queryFn: () => api.search(dq), enabled: open });
  const go = (s: string) => { setOpen(false); setQ(""); router.push(`/s/${encodeURIComponent(s)}`); };
  return (
    <div className="relative">
      <input aria-label="Search symbol" placeholder="Search symbol…" value={q}
        onChange={(e) => { setQ(e.target.value); setOpen(true); }} onFocus={() => setOpen(true)}
        onBlur={() => setTimeout(() => setOpen(false), 150)}
        onKeyDown={(e) => { if (e.key === "Enter" && q.trim()) go((res.data?.[0]?.symbol ?? q.trim()).toUpperCase()); }}
        className="w-56 rounded border border-slate-300 bg-white px-2 py-1 text-sm dark:border-slate-700 dark:bg-slate-900" />
      {open && res.data && res.data.length > 0 && (
        <ul className="absolute z-20 mt-1 max-h-72 w-72 overflow-auto rounded border border-slate-300 bg-white text-sm shadow dark:border-slate-700 dark:bg-slate-900">
          {res.data.map((s) => (
            <li key={s.symbol}><button className="flex w-full justify-between px-2 py-1 text-left hover:bg-slate-100 dark:hover:bg-slate-800" onMouseDown={() => go(s.symbol)}>
              <b>{s.symbol}</b><span className="truncate pl-2 text-slate-500">{s.name}</span></button></li>
          ))}
        </ul>
      )}
    </div>
  );
}
