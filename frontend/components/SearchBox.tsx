"use client";
import { useQuery } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { api } from "@/lib/api";

/** Search every NSE company (and BSE / new listings via a live lookup) by name, nickname, symbol or even a typo. */
export default function SearchBox({ onPick }: { onPick?: (symbol: string) => void }) {
  const [q, setQ] = useState("");
  const [dq, setDq] = useState("");
  const [open, setOpen] = useState(false);
  const [hi, setHi] = useState(0);
  const router = useRouter();
  const box = useRef<HTMLDivElement>(null);
  useEffect(() => { const id = setTimeout(() => setDq(q.trim()), 180); return () => clearTimeout(id); }, [q]);
  const res = useQuery({ queryKey: ["search", dq], queryFn: () => api.search(dq), enabled: open, staleTime: 60_000, placeholderData: (prev) => prev });
  const rows = res.data ?? [];
  useEffect(() => setHi(0), [dq]);
  useEffect(() => {
    const close = (e: MouseEvent) => { if (box.current && !box.current.contains(e.target as Node)) setOpen(false); };
    document.addEventListener("mousedown", close);
    return () => document.removeEventListener("mousedown", close);
  }, []);
  const go = (s: string) => {
    setOpen(false); setQ("");
    if (onPick) onPick(s.toUpperCase()); else router.push(`/s/${encodeURIComponent(s.toUpperCase())}`);
  };
  const typed = q.trim();
  return (
    <div className="relative" ref={box} data-tour="search">
      <input aria-label="Search any stock" role="combobox" aria-expanded={open} aria-controls="search-results" autoComplete="off"
        placeholder="Search any stock: Tata Motors, SBI, INFY…" value={q}
        onChange={(e) => { setQ(e.target.value); setOpen(true); }} onFocus={() => setOpen(true)}
        onKeyDown={(e) => {
          if (e.key === "ArrowDown") { e.preventDefault(); setHi((h) => Math.min(h + 1, Math.max(rows.length - 1, 0))); }
          else if (e.key === "ArrowUp") { e.preventDefault(); setHi((h) => Math.max(h - 1, 0)); }
          else if (e.key === "Escape") setOpen(false);
          else if (e.key === "Enter" && typed) go(rows[hi]?.symbol ?? typed);
        }}
        className="w-64 rounded border border-slate-300 bg-white px-2 py-1 text-sm dark:border-slate-700 dark:bg-slate-900 md:w-80" />
      {open && (
        <ul id="search-results" role="listbox" className="absolute z-30 mt-1 max-h-80 w-[22rem] max-w-[92vw] overflow-auto rounded border border-slate-300 bg-white text-sm shadow-lg dark:border-slate-700 dark:bg-slate-900">
          {!typed && <li className="px-2 py-1 text-xs text-slate-500">Popular stocks. Type a company name or symbol to search all ~2,200 NSE stocks.</li>}
          {rows.map((s, i) => (
            <li key={s.symbol} role="option" aria-selected={i === hi}>
              <button className={`flex w-full items-center justify-between gap-2 px-2 py-1.5 text-left ${i === hi ? "bg-indigo-50 dark:bg-indigo-950" : "hover:bg-slate-100 dark:hover:bg-slate-800"}`}
                onMouseDown={() => go(s.symbol)} onMouseEnter={() => setHi(i)}>
                <span className="min-w-0"><b>{s.symbol}</b> <span className="truncate text-slate-500">{s.name}</span></span>
                <span className="shrink-0 text-[10px] uppercase text-slate-500">{s.sector ? `${s.sector} · ` : ""}{s.exchange ?? "NSE"}</span></button></li>))}
          {typed && !res.isFetching && rows.length === 0 && (
            <li className="px-2 py-2 text-slate-600 dark:text-slate-400">No match in the stock list. <button className="font-medium text-indigo-600 underline dark:text-indigo-300" onMouseDown={() => go(typed)}>Try &quot;{typed.toUpperCase()}&quot; anyway</button> (works for any symbol Yahoo Finance knows, e.g. 500325.BO for BSE).</li>)}
          {typed && res.isFetching && rows.length === 0 && <li className="px-2 py-2 text-slate-500">Searching…</li>}
        </ul>)}
    </div>
  );
}
