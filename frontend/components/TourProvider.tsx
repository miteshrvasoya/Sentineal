"use client";
import { usePathname, useRouter } from "next/navigation";
import { createContext, useCallback, useContext, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { TOURS, type TourDef } from "@/lib/tours";

type Ctx = {
  start: (id: string) => void;
  stop: () => void;
  seen: Set<string>;
  active: TourDef | null;
};
const TourCtx = createContext<Ctx>({ start: () => {}, stop: () => {}, seen: new Set(), active: null });
export const useTour = () => useContext(TourCtx);

const SEEN_KEY = "ql-tours-seen";
const PAD = 6;
const POP_W = 360;

type Rect = { x: number; y: number; w: number; h: number };

function readSeen(): Set<string> {
  try { return new Set(JSON.parse(localStorage.getItem(SEEN_KEY) ?? "[]")); } catch { return new Set(); }
}

function currentSymbol(path: string): string {
  const m = path.match(/^\/s\/([^/]+)/);
  return m ? decodeURIComponent(m[1]) : "RELIANCE";
}

export default function TourProvider({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const pathname = usePathname();
  const [tour, setTour] = useState<TourDef | null>(null);
  const [idx, setIdx] = useState(0);
  const [rect, setRect] = useState<Rect | null>(null);
  const [missing, setMissing] = useState(false);
  const [seen, setSeen] = useState<Set<string>>(new Set());
  const nextBtn = useRef<HTMLButtonElement>(null);
  const popRef = useRef<HTMLDivElement>(null);
  const [popH, setPopH] = useState(260);
  const symbolRef = useRef("RELIANCE");

  useEffect(() => setSeen(readSeen()), []);

  const markSeen = useCallback((id: string) => {
    setSeen((s) => {
      const n = new Set(s).add(id);
      try { localStorage.setItem(SEEN_KEY, JSON.stringify(Array.from(n))); } catch { /* ignore */ }
      return n;
    });
  }, []);

  const stop = useCallback(() => { setTour(null); setRect(null); setMissing(false); }, []);

  const start = useCallback((id: string) => {
    const t = TOURS.find((x) => x.id === id);
    if (!t) return;
    symbolRef.current = currentSymbol(window.location.pathname);
    setIdx(0);
    setRect(null);
    setMissing(false);
    setTour(t);
  }, []);

  const step = tour?.steps[idx];
  const routeFor = useCallback((r?: string) => (r ? r.replace("{symbol}", encodeURIComponent(symbolRef.current)) : undefined), []);

  // Navigate to the step's page if needed, then find (and wait for) its target element.
  useEffect(() => {
    if (!tour || !step) return;
    setRect(null);
    setMissing(false);
    const want = routeFor(step.route);
    if (want && window.location.pathname !== want) router.push(want);
    if (!step.target) return;
    let cancelled = false;
    const t0 = Date.now();
    const find = () => {
      if (cancelled) return;
      const el = document.querySelector<HTMLElement>(`[data-tour="${step.target}"]`);
      const onRightPage = !want || window.location.pathname === want;
      if (el && onRightPage) {
        el.scrollIntoView({ block: el.getBoundingClientRect().height > window.innerHeight * 0.6 ? "start" : "center", behavior: "auto" });
        setMissing(false);
        return;
      }
      if (Date.now() - t0 > 7000) { setMissing(true); return; }
      setTimeout(find, 150);
    };
    find();
    return () => { cancelled = true; };
  }, [tour, idx, step, routeFor, router]);

  // Keep the spotlight glued to the element (it moves on scroll, resize, and when data loads).
  useEffect(() => {
    if (!tour || !step?.target) return;
    let raf = 0;
    const tick = () => {
      const el = document.querySelector<HTMLElement>(`[data-tour="${step.target}"]`);
      if (el) {
        const b = el.getBoundingClientRect();
        setRect((r) => (r && Math.abs(r.x - b.left) < 0.5 && Math.abs(r.y - b.top) < 0.5 && Math.abs(r.w - b.width) < 0.5 && Math.abs(r.h - b.height) < 0.5
          ? r : { x: b.left, y: b.top, w: b.width, h: b.height }));
      }
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [tour, idx, step]);

  const finish = useCallback(() => { if (tour) markSeen(tour.id); stop(); }, [tour, markSeen, stop]);
  const next = useCallback(() => {
    if (!tour) return;
    if (idx >= tour.steps.length - 1) finish(); else setIdx(idx + 1);
  }, [tour, idx, finish]);
  const prev = useCallback(() => setIdx((i) => Math.max(0, i - 1)), []);

  useEffect(() => {
    if (!tour) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") stop();
      else if (e.key === "ArrowRight" || e.key === "Enter") { e.preventDefault(); next(); }
      else if (e.key === "ArrowLeft") prev();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [tour, next, prev, stop]);

  useEffect(() => { nextBtn.current?.focus(); }, [idx, tour, rect === null]);

  useLayoutEffect(() => {
    if (popRef.current) setPopH(popRef.current.offsetHeight);
  }, [idx, tour, missing, rect === null]);

  const ctx = useMemo(() => ({ start, stop, seen, active: tour }), [start, stop, seen, tour]);

  // Popover placement: below the target if it fits, else above, else docked in a corner (very tall targets).
  let pop: React.CSSProperties = { left: "50%", top: "50%", transform: "translate(-50%, -50%)", width: POP_W };
  if (rect && step?.target && !missing) {
    const vw = window.innerWidth, vh = window.innerHeight, h = popH, gap = PAD + 12;
    const spaceBelow = vh - (rect.y + rect.h) - gap, spaceAbove = rect.y - gap;
    const left = Math.min(Math.max(12, rect.x + rect.w / 2 - POP_W / 2), vw - POP_W - 12);
    if (spaceBelow >= h + 12) pop = { left, top: rect.y + rect.h + gap, width: POP_W };
    else if (spaceAbove >= h + 12) pop = { left, top: rect.y - gap - h, width: POP_W };
    else pop = { left: vw - POP_W - 16, top: Math.max(12, vh - h - 16), width: POP_W };   // docked bottom-right
  }
  const lastStep = !!tour && idx === tour.steps.length - 1;

  return (
    <TourCtx.Provider value={ctx}>
      {children}
      {tour && step && (
        <div className="fixed inset-0 z-[100]" data-testid="tour-overlay">
          {/* click shield: keeps the page still while touring */}
          <div className="absolute inset-0" onClick={(e) => e.stopPropagation()} />
          {rect && step.target && !missing ? (
            <div aria-hidden className="pointer-events-none absolute rounded-lg ring-2 ring-indigo-400 transition-all duration-200"
              style={{ left: rect.x - PAD, top: rect.y - PAD, width: rect.w + PAD * 2, height: rect.h + PAD * 2, boxShadow: "0 0 0 9999px rgba(15,23,42,0.62)" }} />
          ) : (
            <div aria-hidden className="pointer-events-none absolute inset-0 bg-slate-900/60" />
          )}
          <div ref={popRef} role="dialog" aria-modal="true" aria-label={`${tour.title}: ${step.title}`} style={pop}
            className="absolute rounded-xl border border-slate-200 bg-white p-4 text-slate-900 shadow-2xl dark:border-slate-700 dark:bg-slate-900 dark:text-slate-100">
            <div className="mb-1 flex items-center gap-2 text-xs text-slate-500">
              <span className="rounded bg-indigo-600 px-1.5 py-0.5 font-medium text-white">{tour.phase}</span>
              <span>{tour.title}</span>
              <span className="ml-auto tabular-nums">{idx + 1} / {tour.steps.length}</span>
            </div>
            <h2 className="text-lg font-semibold">{step.title}</h2>
            <div className="mt-1 space-y-2 text-sm leading-relaxed" aria-live="polite">
              {step.body.split("\n\n").map((p, i) => <p key={i}>{p}</p>)}
              {missing && (
                <p className="rounded bg-amber-50 p-2 text-xs text-amber-900 dark:bg-amber-950 dark:text-amber-200">
                  {step.note ?? "This part of the page is not on screen right now (it may need data first, for example run make seed or fetch news). You can keep going."}
                </p>
              )}
            </div>
            <div className="mt-3 flex items-center gap-2">
              <button onClick={stop} className="text-xs text-slate-500 underline hover:text-slate-800 dark:hover:text-slate-200">Skip tour</button>
              <span className="ml-auto" />
              <button onClick={prev} disabled={idx === 0} className="rounded border border-slate-300 px-3 py-1 text-sm disabled:opacity-40 dark:border-slate-600">Back</button>
              <button ref={nextBtn} onClick={next} className="rounded bg-indigo-600 px-3 py-1 text-sm font-medium text-white hover:bg-indigo-700">{lastStep ? "Finish" : "Next"}</button>
            </div>
            <p className="mt-2 text-[10px] text-slate-400">Keys: ← → to move, Esc to leave</p>
          </div>
        </div>
      )}
    </TourCtx.Provider>
  );
}
