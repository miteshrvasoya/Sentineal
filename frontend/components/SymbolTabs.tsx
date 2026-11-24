"use client";
import Link from "next/link";
import { useParams, usePathname, useSearchParams } from "next/navigation";

export default function SymbolTabs() {
  const sym = encodeURIComponent(decodeURIComponent(String(useParams().symbol)));
  const path = usePathname();
  const qs = useSearchParams().toString();
  const tabs = [{ href: `/s/${sym}`, label: "Overview" }, { href: `/s/${sym}/structure`, label: "Structure & patterns" }, { href: `/s/${sym}/news`, label: "News & sentiment" }, { href: `/s/${sym}/fundamentals`, label: "Fundamentals & risk" }, { href: `/s/${sym}/models`, label: "Models" }, { href: `/s/${sym}/lab`, label: "Model Lab" }, { href: `/s/${sym}/analyst`, label: "AI analyst" }, { href: `/s/${sym}/backtest`, label: "Backtest" }];
  return (
    <div data-tour="tabs" className="mb-3 flex gap-4 border-b border-slate-200 text-sm dark:border-slate-800">
      {tabs.map((t) => (
        <Link key={t.href} href={qs ? `${t.href}?${qs}` : t.href}
          className={`-mb-px border-b-2 px-1 py-1.5 ${path === t.href ? "border-indigo-600 font-semibold" : "border-transparent text-slate-500 hover:text-slate-800 dark:hover:text-slate-200"}`}>{t.label}</Link>
      ))}
    </div>
  );
}
