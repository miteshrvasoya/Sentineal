// Small dependency-free SVG charts for the Models page.
import type { FanData, VolCone } from "@/lib/api";

const W = 640;

/** Stacked bar of the three outcome probabilities. */
export function ProbBar({ up, flat, down }: { up: number; flat: number; down: number }) {
  const seg = (v: number, cls: string, label: string) => (
    <div className={`${cls} flex items-center justify-center text-[10px] text-white`} style={{ width: `${v * 100}%` }} title={`${label} ${(v * 100).toFixed(0)}%`}>
      {v >= 0.12 ? `${(v * 100).toFixed(0)}%` : ""}
    </div>
  );
  return (
    <div className="flex h-5 w-full overflow-hidden rounded" role="img" aria-label={`Up ${(up * 100).toFixed(0)}%, flat ${(flat * 100).toFixed(0)}%, down ${(down * 100).toFixed(0)}%`}>
      {seg(up, "bg-green-600", "Up")}{seg(flat, "bg-slate-400", "Flat")}{seg(down, "bg-red-600", "Down")}
    </div>
  );
}

/** Monte Carlo fan: percentile bands of simulated price paths. */
export function FanChart({ fan, currency = "" }: { fan: FanData; currency?: string }) {
  const H = 230, L = 52, R = 10, T = 10, B = 24;
  const days = [0, ...fan.days];
  const series = (k: keyof FanData["fan"]) => [fan.last, ...fan.fan[k]];
  const all = (["p5", "p25", "p50", "p75", "p95"] as const).flatMap((k) => series(k)).concat(Object.values(fan.touch).map((t) => t.level));
  const lo = Math.min(...all), hi = Math.max(...all), span = hi - lo || 1;
  const x = (i: number) => L + (i / (days.length - 1)) * (W - L - R);
  const y = (v: number) => T + (1 - (v - lo) / span) * (H - T - B);
  const line = (k: keyof FanData["fan"]) => series(k).map((v, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${y(v).toFixed(1)}`).join(" ");
  const band = (a: keyof FanData["fan"], b: keyof FanData["fan"]) =>
    `${line(a)} ${series(b).map((v, i) => [i, v] as const).reverse().map(([i, v]) => `L${x(i).toFixed(1)},${y(v).toFixed(1)}`).join(" ")} Z`;
  const ticks = [lo, lo + span / 2, hi];
  return (
    <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label="Monte Carlo fan chart of simulated price paths" className="w-full">
      <path d={band("p5", "p95")} fill="#6366f1" opacity="0.15" />
      <path d={band("p25", "p75")} fill="#6366f1" opacity="0.28" />
      <path d={line("p50")} fill="none" stroke="#4338ca" strokeWidth="2" />
      <line x1={L} x2={W - R} y1={y(fan.last)} y2={y(fan.last)} stroke="currentColor" opacity="0.35" strokeDasharray="3 3" />
      {Object.values(fan.touch).map((t) => (
        <g key={t.level}>
          <line x1={L} x2={W - R} y1={y(t.level)} y2={y(t.level)} stroke="#f59e0b" strokeWidth="1.2" strokeDasharray="5 3" />
          <text x={W - R - 2} y={y(t.level) - 3} fontSize="10" textAnchor="end" fill="#b45309">{currency}{t.level.toLocaleString("en-IN")} · {(t.probability * 100).toFixed(0)}% chance of touching</text>
        </g>
      ))}
      {ticks.map((v) => <text key={v} x={L - 4} y={y(v) + 3} fontSize="10" textAnchor="end" fill="currentColor" opacity="0.6">{v.toFixed(0)}</text>)}
      <text x={L} y={H - 6} fontSize="10" fill="currentColor" opacity="0.6">today</text>
      <text x={W - R} y={H - 6} fontSize="10" textAnchor="end" fill="currentColor" opacity="0.6">+{days[days.length - 1]} trading days</text>
    </svg>
  );
}

/** Volatility cone: model forecast against the range realised volatility has covered historically. */
export function ConeChart({ cone }: { cone: VolCone }) {
  const H = 210, L = 46, R = 10, T = 10, B = 28;
  const n = cone.horizons.length;
  const all = [...cone.hist_min, ...cone.hist_max, ...cone.forecast, ...cone.current.filter((v) => !Number.isNaN(v))];
  const hi = Math.max(...all) * 1.05, lo = Math.max(0, Math.min(...all) * 0.9);
  const x = (i: number) => L + 30 + (i / (n - 1)) * (W - L - R - 60);
  const y = (v: number) => T + (1 - (v - lo) / (hi - lo || 1)) * (H - T - B);
  const path = (arr: number[]) => arr.map((v, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${y(v).toFixed(1)}`).join(" ");
  const band = (a: number[], b: number[]) => `${path(a)} ${b.map((v, i) => [i, v] as const).reverse().map(([i, v]) => `L${x(i).toFixed(1)},${y(v).toFixed(1)}`).join(" ")} Z`;
  return (
    <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label="Volatility cone" className="w-full">
      <path d={band(cone.hist_min, cone.hist_max)} fill="#94a3b8" opacity="0.2" />
      <path d={band(cone.hist_p25, cone.hist_p75)} fill="#94a3b8" opacity="0.35" />
      <path d={path(cone.hist_p50)} fill="none" stroke="#64748b" strokeDasharray="4 3" />
      <path d={path(cone.forecast)} fill="none" stroke="#dc2626" strokeWidth="2.2" />
      {cone.forecast.map((v, i) => <circle key={`f${i}`} cx={x(i)} cy={y(v)} r="3.5" fill="#dc2626"><title>{`${cone.horizons[i]}-day forecast: ${(v * 100).toFixed(1)}%`}</title></circle>)}
      {cone.current.map((v, i) => !Number.isNaN(v) && <rect key={`c${i}`} x={x(i) - 3} y={y(v) - 3} width="6" height="6" fill="#2563eb"><title>{`${cone.horizons[i]}-day realised now: ${(v * 100).toFixed(1)}%`}</title></rect>)}
      {cone.horizons.map((h, i) => <text key={h} x={x(i)} y={H - 10} fontSize="10" textAnchor="middle" fill="currentColor" opacity="0.7">{h}d</text>)}
      {[lo, (lo + hi) / 2, hi].map((v) => <text key={v} x={L - 4} y={y(v) + 3} fontSize="10" textAnchor="end" fill="currentColor" opacity="0.6">{(v * 100).toFixed(0)}%</text>)}
    </svg>
  );
}

/** Reliability diagram: predicted probability of "up" versus how often it was up. */
export function CalibrationChart({ rows }: { rows: { mean_pred: number; observed: number; n: number }[] }) {
  const S = 190, P = 28;
  const x = (v: number) => P + v * (S - P - 6), y = (v: number) => S - P - v * (S - P - 6);
  const max = Math.max(...rows.map((r) => r.n), 1);
  return (
    <svg viewBox={`0 0 ${S} ${S}`} role="img" aria-label="Calibration curve" className="w-48">
      <line x1={x(0)} y1={y(0)} x2={x(1)} y2={y(1)} stroke="currentColor" opacity="0.4" strokeDasharray="3 3" />
      <polyline fill="none" stroke="#6366f1" strokeWidth="1.5" points={rows.map((r) => `${x(r.mean_pred)},${y(r.observed)}`).join(" ")} />
      {rows.map((r, i) => <circle key={i} cx={x(r.mean_pred)} cy={y(r.observed)} r={3 + 5 * (r.n / max)} fill="#6366f1" opacity="0.6"><title>{`predicted ${(r.mean_pred * 100).toFixed(0)}% / observed ${(r.observed * 100).toFixed(0)}% (n=${r.n})`}</title></circle>)}
      <text x={S / 2} y={S - 6} fontSize="9" textAnchor="middle" fill="currentColor" opacity="0.7">predicted P(up)</text>
      <text x={8} y={S / 2} fontSize="9" fill="currentColor" opacity="0.7" transform={`rotate(-90 8 ${S / 2})`} textAnchor="middle">observed</text>
    </svg>
  );
}

const REGIME_COLOR = ["#dc2626", "#94a3b8", "#16a34a"];
/** One cell per day, coloured by the most likely regime at that time (filtered: no hindsight). */
export function RegimeStrip({ regime, prob, dates, labels }: { regime: number[]; prob: number[]; dates: string[]; labels: string[] }) {
  const h = 26, w = W / regime.length;
  return (
    <div>
      <svg viewBox={`0 0 ${W} ${h + 14}`} role="img" aria-label="Regime timeline" className="w-full">
        {regime.map((r, i) => <rect key={i} x={i * w} y={0} width={w + 0.3} height={h} fill={REGIME_COLOR[r]} opacity={0.35 + 0.65 * prob[i]}><title>{`${dates[i]}: ${labels[r]} (${(prob[i] * 100).toFixed(0)}%)`}</title></rect>)}
        <text x={0} y={h + 11} fontSize="10" fill="currentColor" opacity="0.6">{dates[0]}</text>
        <text x={W} y={h + 11} fontSize="10" textAnchor="end" fill="currentColor" opacity="0.6">{dates[dates.length - 1]}</text>
      </svg>
      <div className="flex gap-3 text-xs">{labels.map((l, i) => <span key={l}><span className="mr-1 inline-block h-2.5 w-2.5 rounded-sm align-middle" style={{ background: REGIME_COLOR[i] }} />{l}</span>)}</div>
    </div>
  );
}

/** Horizontal bars, largest first. Used for mean |SHAP| and permutation importance. */
export function BarList({ items, unit = "", color = "#6366f1", digits = 3 }: { items: { label: string; value: number }[]; unit?: string; color?: string; digits?: number }) {
  const max = Math.max(...items.map((i) => Math.abs(i.value)), 1e-12);
  return (
    <ul className="space-y-1 text-xs">
      {items.map((i) => (
        <li key={i.label} className="grid grid-cols-[9.5rem_1fr_4.5rem] items-center gap-2">
          <span className="truncate" title={i.label}>{i.label}</span>
          <div className="h-3 rounded bg-slate-100 dark:bg-slate-800"><div className="h-3 rounded" style={{ width: `${(Math.abs(i.value) / max) * 100}%`, background: color }} /></div>
          <span className="text-right tabular-nums text-slate-500">{i.value.toFixed(digits)}{unit}</span>
        </li>
      ))}
    </ul>
  );
}

/** Per-prediction contributions: bars to the right push toward UP, to the left toward DOWN. */
export function PushBars({ items }: { items: { label: string; value: number; note?: string }[] }) {
  const max = Math.max(...items.map((i) => Math.abs(i.value)), 1e-12);
  return (
    <ul className="space-y-1 text-xs">
      {items.map((i) => (
        <li key={i.label} className="grid grid-cols-[11rem_1fr_3.5rem] items-center gap-2">
          <span className="truncate" title={i.note ?? i.label}>{i.label}</span>
          <div className="relative h-3 rounded bg-slate-100 dark:bg-slate-800">
            <div className="absolute inset-y-0 left-1/2 w-px bg-slate-400" />
            <div className="absolute inset-y-0.5 rounded" style={i.value >= 0 ? { left: "50%", width: `${(i.value / max) * 50}%`, background: "#16a34a" } : { right: "50%", width: `${(-i.value / max) * 50}%`, background: "#dc2626" }} />
          </div>
          <span className="text-right tabular-nums text-slate-500">{i.value >= 0 ? "+" : ""}{i.value.toFixed(3)}</span>
        </li>
      ))}
    </ul>
  );
}

/** Partial dependence: average P(up) as one feature is swept across its typical range. */
export function PdpChart({ feature, grid, p_up }: { feature: string; grid: number[]; p_up: number[] }) {
  const W2 = 220, H2 = 110, L = 30, R = 6, T = 8, B = 20;
  const lo = Math.min(...p_up), hi = Math.max(...p_up), span = hi - lo || 0.01;
  const x = (i: number) => L + (i / (grid.length - 1)) * (W2 - L - R);
  const y = (v: number) => T + (1 - (v - lo) / span) * (H2 - T - B);
  return (
    <figure>
      <svg viewBox={`0 0 ${W2} ${H2}`} role="img" aria-label={`Partial dependence of P(up) on ${feature}`} className="w-full max-w-[16rem]">
        <polyline fill="none" stroke="#6366f1" strokeWidth="1.8" points={p_up.map((v, i) => `${x(i).toFixed(1)},${y(v).toFixed(1)}`).join(" ")} />
        <text x={L - 3} y={T + 6} fontSize="9" textAnchor="end" fill="currentColor" opacity="0.6">{(hi * 100).toFixed(0)}%</text>
        <text x={L - 3} y={H2 - B} fontSize="9" textAnchor="end" fill="currentColor" opacity="0.6">{(lo * 100).toFixed(0)}%</text>
        <text x={L} y={H2 - 6} fontSize="9" fill="currentColor" opacity="0.6">{grid[0].toPrecision(2)}</text>
        <text x={W2 - R} y={H2 - 6} fontSize="9" textAnchor="end" fill="currentColor" opacity="0.6">{grid[grid.length - 1].toPrecision(2)}</text>
      </svg>
      <figcaption className="text-[11px] text-slate-500">P(up) vs <b>{feature}</b></figcaption>
    </figure>
  );
}

export type Series = { name: string; color: string; points: { date: string; v: number }[]; dashed?: boolean };
const PALETTE = ["#6366f1", "#16a34a", "#f59e0b", "#dc2626", "#0ea5e9", "#a855f7", "#14b8a6", "#ec4899", "#84cc16", "#f97316", "#64748b", "#0891b2"];
export const colorFor = (i: number) => PALETTE[i % PALETTE.length];

/** Several time series on one axis, with a legend. Dates are placed by real time, so series of different lengths line up. */
export function MultiLine({ series, label, fmt = (v: number) => v.toFixed(1), baseline }: { series: Series[]; label: string; fmt?: (v: number) => string; baseline?: number }) {
  const Hh = 200, L = 60, R = 8, T = 8, B = 20;
  const all = series.flatMap((s) => s.points);
  if (all.length < 2) return <p className="text-sm text-slate-500">Not enough data for {label}.</p>;
  const ts = all.map((p) => Date.parse(p.date));
  const t0 = Math.min(...ts), t1 = Math.max(...ts);
  const vals = all.map((p) => p.v).concat(baseline !== undefined ? [baseline] : []);
  const lo = Math.min(...vals), hi = Math.max(...vals), span = hi - lo || 1;
  const x = (d: string) => L + ((Date.parse(d) - t0) / (t1 - t0 || 1)) * (W - L - R);
  const y = (v: number) => T + (1 - (v - lo) / span) * (Hh - T - B);
  return (
    <figure>
      <svg viewBox={`0 0 ${W} ${Hh}`} role="img" aria-label={label} className="w-full">
        {baseline !== undefined && <line x1={L} x2={W - R} y1={y(baseline)} y2={y(baseline)} stroke="currentColor" opacity="0.3" strokeDasharray="3 3" />}
        {series.map((s) => (
          <polyline key={s.name} fill="none" stroke={s.color} strokeWidth={s.dashed ? 1.2 : 1.8} strokeDasharray={s.dashed ? "4 3" : undefined}
            points={s.points.map((p) => `${x(p.date).toFixed(1)},${y(p.v).toFixed(1)}`).join(" ")} />
        ))}
        {[lo, (lo + hi) / 2, hi].map((v) => <text key={v} x={L - 4} y={y(v) + 3} fontSize="10" textAnchor="end" fill="currentColor" opacity="0.6">{fmt(v)}</text>)}
        <text x={L} y={Hh - 5} fontSize="10" fill="currentColor" opacity="0.6">{new Date(t0).toISOString().slice(0, 10)}</text>
        <text x={W - R} y={Hh - 5} fontSize="10" textAnchor="end" fill="currentColor" opacity="0.6">{new Date(t1).toISOString().slice(0, 10)}</text>
      </svg>
      <figcaption className="mt-1 flex flex-wrap gap-x-3 gap-y-0.5 text-[11px]">
        {series.map((s) => <span key={s.name}><span className="mr-1 inline-block h-2 w-3 rounded-sm align-middle" style={{ background: s.color }} />{s.name}</span>)}
      </figcaption>
    </figure>
  );
}
