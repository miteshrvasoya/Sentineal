"use client";
import { useEffect, useRef, useState } from "react";
import { useTour } from "@/components/TourProvider";
import { NEWEST_TOUR, TOURS } from "@/lib/tours";

/** Top-bar "Tour" button with a list of all phase tours; the newest unseen one is flagged NEW. */
export default function TourMenu() {
  const { start, seen } = useTour();
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const close = (e: MouseEvent) => { if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false); };
    document.addEventListener("mousedown", close);
    return () => document.removeEventListener("mousedown", close);
  }, []);
  const hasNew = !!NEWEST_TOUR && !seen.has(NEWEST_TOUR.id);
  return (
    <div className="relative" ref={ref} data-tour="tour-menu">
      <button onClick={() => setOpen((o) => !o)} aria-haspopup="menu" aria-expanded={open}
        className="relative rounded border border-indigo-500 px-2 py-1 text-sm font-medium text-indigo-600 hover:bg-indigo-50 dark:text-indigo-300 dark:hover:bg-indigo-950">
        Tour{hasNew && <span className="absolute -right-1 -top-1 h-2.5 w-2.5 rounded-full bg-red-500" aria-label="new tour available" />}
      </button>
      {open && (
        <div role="menu" className="absolute right-0 z-40 mt-1 w-80 rounded-lg border border-slate-200 bg-white p-1 shadow-xl dark:border-slate-700 dark:bg-slate-900">
          <p className="px-2 py-1 text-xs text-slate-500">Guided tours of the real pages, one per phase.</p>
          {TOURS.map((t) => (
            <button key={t.id} role="menuitem" onClick={() => { setOpen(false); start(t.id); }}
              className="block w-full rounded px-2 py-1.5 text-left hover:bg-slate-100 dark:hover:bg-slate-800">
              <span className="flex items-center gap-2 text-sm font-medium">
                <span className="rounded bg-slate-200 px-1.5 py-0.5 text-[10px] dark:bg-slate-700">{t.phase}</span>{t.title}
                {t.isNew && !seen.has(t.id) && <span className="rounded bg-red-500 px-1.5 py-0.5 text-[10px] text-white">NEW</span>}
                {seen.has(t.id) && <span className="ml-auto text-xs text-green-600" title="You completed this tour">✓</span>}
              </span>
              <span className="block text-xs text-slate-500">{t.blurb}</span>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

/** One-time prompt announcing the newest tour. Dismissal is remembered per tour. */
export function WhatsNewBanner() {
  const { start, seen } = useTour();
  const [dismissed, setDismissed] = useState(true);
  useEffect(() => {
    try { setDismissed(localStorage.getItem("ql-banner-dismissed") === NEWEST_TOUR?.id); } catch { setDismissed(false); }
  }, []);
  const nt = NEWEST_TOUR;
  if (!nt || dismissed || seen.has(nt.id)) return null;
  const hide = () => { setDismissed(true); try { localStorage.setItem("ql-banner-dismissed", nt.id); } catch { /* ignore */ } };
  return (
    <div role="status" className="flex flex-wrap items-center gap-3 border-b border-indigo-200 bg-indigo-50 px-4 py-2 text-sm text-indigo-900 dark:border-indigo-900 dark:bg-indigo-950 dark:text-indigo-100">
      <span className="rounded bg-red-500 px-1.5 py-0.5 text-xs font-medium text-white">NEW</span>
      <span><b>{nt.phase}: {nt.title}.</b> {nt.blurb}</span>
      <button onClick={() => { hide(); start(nt.id); }} className="ml-auto rounded bg-indigo-600 px-3 py-1 font-medium text-white hover:bg-indigo-700">Take the tour</button>
      <button onClick={hide} className="text-xs underline">Dismiss</button>
    </div>
  );
}
