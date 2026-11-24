"use client";
import { useTour } from "@/components/TourProvider";
import { TOURS } from "@/lib/tours";

/** Grid of tour launch buttons for the Guide page. */
export default function TourButtons() {
  const { start, seen } = useTour();
  return (
    <section aria-label="Interactive tours" className="mb-6 rounded border border-indigo-200 bg-indigo-50 p-3 dark:border-indigo-900 dark:bg-indigo-950">
      <h2 className="text-lg font-semibold">Interactive tours</h2>
      <p className="mb-2 text-sm text-slate-600 dark:text-slate-300">Prefer to see it on the real screens? Each tour opens the actual pages and spotlights the parts that phase added.</p>
      <div className="grid gap-2 sm:grid-cols-2">
        {TOURS.map((t) => (
          <button key={t.id} onClick={() => start(t.id)}
            className="rounded border border-indigo-300 bg-white p-2 text-left hover:bg-indigo-100 dark:border-indigo-800 dark:bg-slate-900 dark:hover:bg-slate-800">
            <span className="flex items-center gap-2 text-sm font-medium">
              <span className="rounded bg-indigo-600 px-1.5 py-0.5 text-[10px] text-white">{t.phase}</span>{t.title}
              {t.isNew && !seen.has(t.id) && <span className="rounded bg-red-500 px-1.5 py-0.5 text-[10px] text-white">NEW</span>}
              {seen.has(t.id) && <span className="ml-auto text-xs text-green-600" aria-label="completed">✓ done</span>}
            </span>
            <span className="block text-xs text-slate-500">{t.blurb} ({t.steps.length} steps)</span>
          </button>
        ))}
      </div>
    </section>
  );
}
