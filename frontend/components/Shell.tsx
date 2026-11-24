"use client";
import Link from "next/link";
import MarketBar from "./MarketBar";
import SearchBox from "./SearchBox";
import ThemeToggle from "./ThemeToggle";
import Watchlist from "./Watchlist";

export default function Shell({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex min-h-screen flex-col">
      <header className="flex flex-wrap items-center gap-4 border-b border-slate-200 px-4 py-2 dark:border-slate-800">
        <Link href="/" className="text-lg font-bold">Quant<span className="text-indigo-500">Lens</span></Link>
        <SearchBox />
        <Link href="/guide" className="text-sm font-medium text-indigo-600 hover:underline dark:text-indigo-300">Guide</Link>
        <Link href="/settings" className="text-sm text-slate-500 hover:underline">Data health &amp; LLM</Link>
        <MarketBar />
        <ThemeToggle />
      </header>
      <div className="flex flex-1 flex-col md:flex-row">
        <aside className="border-b border-slate-200 p-3 dark:border-slate-800 md:w-60 md:border-b-0 md:border-r"><Watchlist /></aside>
        <main className="flex-1 p-4">{children}</main>
      </div>
      <footer role="note" className="border-t border-amber-300 bg-amber-50 px-4 py-2 text-xs text-amber-900 dark:border-amber-800 dark:bg-amber-950 dark:text-amber-200">
        Educational tool, not investment advice. Data may be delayed or wrong. No model here is a guarantee.
      </footer>
    </div>
  );
}
