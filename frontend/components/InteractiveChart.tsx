"use client";
import { useEffect, useMemo, useRef, useState } from "react";

export type Pt = { date: string; v: number };
export type ChartSeries = { name: string; color: string; points: Pt[]; dashed?: boolean; area?: boolean; thin?: boolean };
export type Marker = { date: string; kind: "buy" | "sell"; label: string; detail: string };
export type HLine = { v: number; label: string; color?: string };

const H = 300, PAD = { l: 62, r: 14, t: 14, b: 26 };
const MS = 864e5;

const parse = (d: string) => Date.parse(`${d}T00:00:00`);
const fmtLong = (d: string) => new Date(parse(d)).toLocaleDateString("en-IN", { weekday: "short", day: "numeric", month: "short", year: "numeric" });
const fmtAxis = (d: string, span: number) => new Date(parse(d)).toLocaleDateString("en-IN", span > 500 ? { month: "short", year: "numeric" } : span > 100 ? { month: "short", year: "2-digit" } : { day: "numeric", month: "short" });
const pc = (x: number) => `${x >= 0 ? "+" : ""}${(x * 100).toFixed(1)}%`;

function useWidth() {
  const ref = useRef<HTMLDivElement>(null);
  const [w, setW] = useState(720);
  useEffect(() => {
    if (!ref.current) return;
    const el = ref.current;
    const ro = new ResizeObserver(() => setW(Math.max(280, Math.floor(el.clientWidth))));
    ro.observe(el);
    setW(Math.max(280, Math.floor(el.clientWidth)));
    return () => ro.disconnect();
  }, []);
  return [ref, w] as const;
}

/** Nearest point at or before `date` (series are sorted by date). */
function valueAt(points: Pt[], date: string): number | null {
  let lo = 0, hi = points.length - 1, ans = -1;
  const t = parse(date);
  while (lo <= hi) { const m = (lo + hi) >> 1; if (parse(points[m].date) <= t) { ans = m; lo = m + 1; } else hi = m - 1; }
  return ans >= 0 ? points[ans].v : null;
}

/**
 * Interactive line/area chart: move the mouse (or finger, or arrow keys) to read exact values, drag to measure the change between two
 * days, see your own buys and sells as markers and your average price as a line. The first series is the "main" one.
 */
export default function InteractiveChart({ series, markers = [], hlines = [], fmt, label, valueName = "Price", autoColor = false, height = H }: {
  series: ChartSeries[]; markers?: Marker[]; hlines?: HLine[]; fmt: (v: number) => string; label: string; valueName?: string; autoColor?: boolean; height?: number;
}) {
  const [wrap, W] = useWidth();
  const main = series[0]?.points ?? [];
  const n = main.length;
  const [hover, setHover] = useState<number | null>(null);
  const [anchor, setAnchor] = useState<number | null>(null);   // drag start (index)
  const [sel, setSel] = useState<[number, number] | null>(null);
  const dragging = useRef(false);
  const sig = `${n}|${main[0]?.date}|${main[n - 1]?.date}`;            // reset the selection only when the data range really changes
  useEffect(() => { setHover(null); setAnchor(null); setSel(null); }, [sig]);

  const dom = useMemo(() => {
    const vals = series.flatMap((s) => s.points.map((p) => p.v));
    if (!vals.length) return { lo: 0, hi: 1 };
    let lo = Math.min(...vals), hi = Math.max(...vals);
    const span = hi - lo || Math.abs(hi) || 1;
    for (const h of hlines) if (h.v > lo - span * 0.4 && h.v < hi + span * 0.4) { lo = Math.min(lo, h.v); hi = Math.max(hi, h.v); }
    const pad = (hi - lo) * 0.06 || 1;
    return { lo: lo - pad, hi: hi + pad };
  }, [series, hlines]);
  if (n < 2) return <p className="text-sm text-slate-500">Not enough data to draw {label}.</p>;

  const t0 = parse(main[0].date), t1 = parse(main[n - 1].date), spanDays = (t1 - t0) / MS;
  const iw = W - PAD.l - PAD.r, ih = height - PAD.t - PAD.b;
  const x = (d: string) => PAD.l + ((parse(d) - t0) / (t1 - t0 || 1)) * iw;
  const y = (v: number) => PAD.t + (1 - (v - dom.lo) / (dom.hi - dom.lo)) * ih;
  const idxFromX = (px: number) => {
    const t = t0 + ((px - PAD.l) / iw) * (t1 - t0);
    let lo = 0, hi = n - 1;
    while (hi - lo > 1) { const m = (lo + hi) >> 1; if (parse(main[m].date) <= t) lo = m; else hi = m; }
    return Math.abs(parse(main[lo].date) - t) <= Math.abs(parse(main[hi].date) - t) ? lo : hi;
  };
  const clampI = (i: number) => Math.max(0, Math.min(n - 1, i));
  const pos = (e: React.PointerEvent) => idxFromX(e.clientX - (e.currentTarget as SVGSVGElement).getBoundingClientRect().left);

  const okIdx = (i: number | null) => i !== null && i >= 0 && i < n;
  const up = main[n - 1].v >= main[0].v;
  const mainColor = autoColor ? (up ? "#16a34a" : "#dc2626") : series[0].color;
  const hi = okIdx(hover) ? (hover as number) : n - 1;
  const hp = main[hi];
  const ticks = [0, 1, 2, 3, 4].map((k) => dom.lo + ((dom.hi - dom.lo) * k) / 4);
  const xt = [0, 1, 2, 3, 4].map((k) => main[Math.round(((n - 1) * k) / 4)].date);
  const maxI = main.reduce((b, p, i) => (p.v > main[b].v ? i : b), 0), minI = main.reduce((b, p, i) => (p.v < main[b].v ? i : b), 0);
  const line = (pts: Pt[]) => pts.map((p) => `${x(p.date).toFixed(1)},${y(p.v).toFixed(1)}`).join(" ");
  const mk = markers.filter((m) => parse(m.date) >= t0 && parse(m.date) <= t1).map((m) => {
    const v = valueAt(main, m.date);
    return v === null ? null : { ...m, px: x(m.date), py: y(v) };
  }).filter(Boolean) as (Marker & { px: number; py: number })[];
  const near = okIdx(hover) ? mk.find((m) => Math.abs(m.px - x(main[hover as number].date)) < 7) : undefined;

  // indexes can be stale for one render when the data range changes (the reset effect runs after render): never index past the end
  const okI = (i: number | null): i is number => i !== null && i >= 0 && i < n;
  const range = sel && okI(sel[0]) && okI(sel[1]) ? sel : (okI(anchor) && okI(hover) ? ([Math.min(anchor, hover), Math.max(anchor, hover)] as [number, number]) : null);
  const rangeInfo = range && range[0] !== range[1] ? { a: main[range[0]], b: main[range[1]] } : null;

  const tipLeft = Math.min(Math.max(x(hp.date) + 12, 4), W - 210);
  const onKey = (e: React.KeyboardEvent) => {
    const step = e.shiftKey ? 10 : 1;
    if (e.key === "ArrowLeft") { e.preventDefault(); setHover(clampI((hover ?? n - 1) - step)); }
    else if (e.key === "ArrowRight") { e.preventDefault(); setHover(clampI((hover ?? n - 1) + step)); }
    else if (e.key === "Home") setHover(0);
    else if (e.key === "End") setHover(n - 1);
    else if (e.key === "Escape") { setAnchor(null); setSel(null); setHover(null); }
  };
  const fromStart = hp.v / main[0].v - 1, toNow = main[n - 1].v / hp.v - 1;

  return (
    <div ref={wrap} className="relative select-none">
      <svg width={W} height={height} role="img" tabIndex={0} aria-label={`${label}. Use the left and right arrow keys to read values.`} onKeyDown={onKey}
        onPointerMove={(e) => { const i = pos(e); setHover(i); if (dragging.current && anchor !== null) setSel(null); }}
        onPointerLeave={() => { if (!dragging.current) setHover(null); }}
        onPointerDown={(e) => { const i = pos(e); dragging.current = true; setAnchor(i); setSel(null); setHover(i); try { (e.currentTarget as SVGSVGElement).setPointerCapture(e.pointerId); } catch { /* capture is a nicety */ } }}
        onPointerUp={(e) => { dragging.current = false; const i = pos(e); if (anchor !== null && Math.abs(i - anchor) > 1) setSel([Math.min(anchor, i), Math.max(anchor, i)]); setAnchor(null); }}
        onDoubleClick={() => { setSel(null); setAnchor(null); }}
        style={{ touchAction: "pan-y", cursor: "crosshair" }} className="w-full rounded outline-none focus-visible:ring-2 focus-visible:ring-indigo-500" data-testid="ichart">
        <defs><linearGradient id="ic-fill" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stopColor={mainColor} stopOpacity="0.28" /><stop offset="100%" stopColor={mainColor} stopOpacity="0" /></linearGradient></defs>
        {ticks.map((v) => (
          <g key={v}><line x1={PAD.l} x2={W - PAD.r} y1={y(v)} y2={y(v)} stroke="currentColor" opacity="0.1" />
            <text x={PAD.l - 6} y={y(v) + 3} fontSize="10" textAnchor="end" fill="currentColor" opacity="0.65">{fmt(v)}</text></g>))}
        {xt.map((d, k) => <text key={d + k} x={x(d)} y={height - 8} fontSize="10" textAnchor={k === 0 ? "start" : k === 4 ? "end" : "middle"} fill="currentColor" opacity="0.65">{fmtAxis(d, spanDays)}</text>)}
        {hlines.filter((h) => h.v >= dom.lo && h.v <= dom.hi).map((h) => (
          <g key={h.label}><line x1={PAD.l} x2={W - PAD.r} y1={y(h.v)} y2={y(h.v)} stroke={h.color ?? "#64748b"} strokeDasharray="5 4" opacity="0.8" />
            <text x={W - PAD.r - 2} y={y(h.v) - 3} fontSize="10" textAnchor="end" fill={h.color ?? "#64748b"}>{h.label} {fmt(h.v)}</text></g>))}
        {range && <rect x={x(main[range[0]].date)} y={PAD.t} width={Math.max(1, x(main[range[1]].date) - x(main[range[0]].date))} height={ih} fill="#6366f1" opacity="0.12" />}
        {series[0].area !== false && <polygon points={`${x(main[0].date)},${PAD.t + ih} ${line(main)} ${x(main[n - 1].date)},${PAD.t + ih}`} fill="url(#ic-fill)" />}
        {series.slice(1).map((s) => <polyline key={s.name} fill="none" stroke={s.color} strokeWidth={s.thin ? 1.1 : 1.6} strokeDasharray={s.dashed ? "4 3" : undefined} points={line(s.points)} />)}
        <polyline fill="none" stroke={mainColor} strokeWidth="2" strokeLinejoin="round" points={line(main)} />
        {[maxI, minI].map((i, k) => (i === 0 || i === n - 1 ? null : <g key={k}><circle cx={x(main[i].date)} cy={y(main[i].v)} r="3" fill={mainColor} />
          <text x={x(main[i].date)} y={y(main[i].v) + (k === 0 ? -7 : 14)} fontSize="10" textAnchor="middle" fill="currentColor" opacity="0.75">{k === 0 ? "High" : "Low"} {fmt(main[i].v)}</text></g>))}
        {mk.map((m, i) => (m.kind === "buy"
          ? <polygon key={i} points={`${m.px},${m.py - 11} ${m.px - 6},${m.py - 1} ${m.px + 6},${m.py - 1}`} fill="#16a34a" stroke="white" strokeWidth="1" />
          : <polygon key={i} points={`${m.px},${m.py + 11} ${m.px - 6},${m.py + 1} ${m.px + 6},${m.py + 1}`} fill="#dc2626" stroke="white" strokeWidth="1" />))}
        <g opacity={okIdx(hover) ? 1 : 0} pointerEvents="none">
          <line x1={x(hp.date)} x2={x(hp.date)} y1={PAD.t} y2={PAD.t + ih} stroke="currentColor" opacity="0.35" />
          {series.map((s) => { const v = valueAt(s.points, hp.date); return v === null ? null : <circle key={s.name} cx={x(hp.date)} cy={y(v)} r={s === series[0] ? 4.5 : 3.5} fill={s === series[0] ? mainColor : s.color} stroke="white" strokeWidth="1.5" />; })}
        </g>
      </svg>
      {okIdx(hover) && (
        <div role="status" className="pointer-events-none absolute z-10 w-52 rounded border border-slate-300 bg-white p-2 text-xs shadow-lg dark:border-slate-600 dark:bg-slate-900" style={{ left: tipLeft, top: 8 }} data-testid="ichart-tip">
          <div className="font-medium">{fmtLong(hp.date)}</div>
          {series.map((s) => { const v = valueAt(s.points, hp.date); return v === null ? null : (
            <div key={s.name} className="flex items-center justify-between gap-2"><span><span className="mr-1 inline-block h-2 w-2 rounded-full align-middle" style={{ background: s === series[0] ? mainColor : s.color }} />{s === series[0] ? valueName : s.name}</span><b className="tabular-nums">{fmt(v)}</b></div>); })}
          {series.length === 1 && <div className="mt-0.5 text-slate-500">{pc(fromStart)} since the start of this period; {pc(toNow)} from here to the latest.</div>}
          {near && <div className="mt-1 border-t border-slate-200 pt-1 dark:border-slate-700"><b className={near.kind === "buy" ? "text-green-700 dark:text-green-400" : "text-red-600"}>{near.kind === "buy" ? "You bought" : "You sold"}</b> {near.detail}</div>}
        </div>)}
      <div className="mt-1 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-slate-500" aria-live="polite">
        {rangeInfo ? (
          <span data-testid="ichart-measure"><b className="text-slate-800 dark:text-slate-200">{fmtLong(rangeInfo.a.date)} to {fmtLong(rangeInfo.b.date)}:</b> {fmt(rangeInfo.a.v)} to {fmt(rangeInfo.b.v)}, <b className={rangeInfo.b.v >= rangeInfo.a.v ? "text-green-700 dark:text-green-400" : "text-red-600"}>{pc(rangeInfo.b.v / rangeInfo.a.v - 1)}</b>
            {sel && <button onClick={() => setSel(null)} className="ml-2 underline">clear</button>}</span>
        ) : <span>Move over the chart to read values. Drag across it to measure a change. Arrow keys work too.</span>}
        {series.length > 1 && <span className="ml-auto flex flex-wrap gap-x-3">{series.map((s) => <span key={s.name}><span className="mr-1 inline-block h-2 w-3 rounded-sm align-middle" style={{ background: s === series[0] ? mainColor : s.color }} />{s === series[0] ? valueName : s.name}</span>)}</span>}
        {mk.length > 0 && <span><span className="text-green-600">▲</span> bought <span className="ml-1 text-red-600">▼</span> sold</span>}
      </div>
    </div>
  );
}

