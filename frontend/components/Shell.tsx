"use client";
import Link from "next/link";
import { useMode } from "@/lib/mode";
import MarketBar from "./MarketBar";
import SearchBox from "./SearchBox";
import ThemeToggle from "./ThemeToggle";
import TourMenu, { WhatsNewBanner } from "./TourMenu";
import Watchlist from "./Watchlist";

const link = "text-sm font-medium hover:underline";

export default function Shell({ children }: { children: React.ReactNode }) {
  const { mode, setMode } = useMode();
  const simple = mode === "simple";
  return (
    <div className="flex min-h-screen flex-col">
      <header className="flex flex-wrap items-center gap-x-4 gap-y-2 border-b border-slate-200 px-4 py-2 dark:border-slate-800">
        <Link href="/" className="text-lg font-bold">Quant<span className="text-indigo-500">Lens</span></Link>
        <SearchBox />
        <nav aria-label="Main" className="flex flex-wrap items-center gap-x-4 gap-y-1" data-tour="main-nav">
          <Link href="/" className={link}>My investments</Link>
          <Link href="/discover" className={link}>Find stocks</Link>
          {!simple && <Link href="/briefing" className={link}>Briefing</Link>}
          <Link href="/chat" className={link}>Ask</Link>
          {!simple && <Link href="/screener" className={link}>Screener</Link>}
          {!simple && <Link href="/market" className={link}>Market</Link>}
          <Link href="/learn" className={link}>Learn</Link>
          {!simple && <Link href="/guide" className="text-sm font-medium text-indigo-600 hover:underline dark:text-indigo-300">Guide</Link>}
          {!simple && <Link href="/settings" className="text-sm text-slate-500 hover:underline">Data health &amp; AI</Link>}
          {simple && <Link href="/settings" className="text-sm text-slate-500 hover:underline">Settings</Link>}
        </nav>
        <div data-tour="market-bar"><MarketBar /></div>
        <div className="ml-auto flex items-center gap-2">
          <div role="group" aria-label="View mode" data-tour="mode-toggle" className="flex overflow-hidden rounded border border-slate-300 text-xs dark:border-slate-700">
            <button onClick={() => setMode("simple")} aria-pressed={simple} title="Plain English, only what a beginner needs"
              className={`px-2 py-1 ${simple ? "bg-indigo-600 text-white" : "hover:bg-slate-100 dark:hover:bg-slate-800"}`}>Simple</button>
            <button onClick={() => setMode("advanced")} aria-pressed={!simple} title="Charts, models, backtests and all the analysis tools"
              className={`px-2 py-1 ${!simple ? "bg-indigo-600 text-white" : "hover:bg-slate-100 dark:hover:bg-slate-800"}`}>Advanced</button>
          </div>
          <TourMenu />
          <ThemeToggle />
        </div>
      </header>
      <WhatsNewBanner />
      <div className="flex flex-1 flex-col md:flex-row">
        <aside data-tour="watchlist" className="border-b border-slate-200 p-3 dark:border-slate-800 md:w-60 md:border-b-0 md:border-r"><Watchlist /></aside>
        <main className="flex-1 p-4">{children}</main>
      </div>
      <footer role="note" data-tour="disclaimer" className="border-t border-amber-300 bg-amber-50 px-4 py-2 text-xs text-amber-900 dark:border-amber-800 dark:bg-amber-950 dark:text-amber-200">
        Educational tool, not investment advice. Data may be delayed or wrong. Investing can lose money. No score or idea here is a guarantee.
      </footer>
    </div>
  );
}
