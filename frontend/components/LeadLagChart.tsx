import type { LeadLag } from "@/lib/api";

/** Correlation of sentiment(t) with return(t+lag). Solid bar = significant after Bonferroni correction. */
export default function LeadLagChart({ rows }: { rows: LeadLag[] }) {
  const W = 520, H = 150, mid = H / 2;
  const max = Math.max(0.3, ...rows.map((r) => Math.abs(r.corr ?? 0)));
  const bw = W / rows.length;
  const enough = rows.some((r) => r.corr !== null);
  return (
    <figure>
      <svg viewBox={`0 0 ${W} ${H + 24}`} role="img" aria-label="Sentiment to return lead-lag correlation" className="w-full max-w-xl">
        <line x1="0" x2={W} y1={mid} y2={mid} stroke="currentColor" opacity="0.3" />
        {rows.map((r, i) => {
          const v = r.corr ?? 0, h = (Math.abs(v) / max) * (mid - 6), sig = (r.p_bonferroni ?? 1) < 0.05;
          return (
            <g key={r.lag}>
              <rect x={i * bw + 6} width={bw - 12} y={v >= 0 ? mid - h : mid} height={Math.max(h, r.corr === null ? 0 : 1)}
                fill={v >= 0 ? "#16a34a" : "#dc2626"} opacity={sig ? 1 : 0.35}><title>{`lag ${r.lag}: corr ${r.corr ?? "n/a"}, n=${r.n}, p(bonf)=${r.p_bonferroni ?? "n/a"}`}</title></rect>
              <text x={i * bw + bw / 2} y={H + 14} textAnchor="middle" fontSize="11" fill="currentColor">{r.lag > 0 ? `+${r.lag}` : r.lag}</text>
            </g>
          );
        })}
      </svg>
      <figcaption className="text-xs text-slate-500">
        {enough ? "x = lag in days. Positive lag: sentiment today vs return that many days later (sentiment leads). Negative lag: price leads sentiment."
          : "Not enough overlapping days yet (needs 30) to estimate this."}
      </figcaption>
    </figure>
  );
}
