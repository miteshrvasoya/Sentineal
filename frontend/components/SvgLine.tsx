/** Small dependency-free line/area chart with min/max labels and an optional zero line. */
export default function SvgLine({ dates, values, color = "#6366f1", area = false, fmt = (v: number) => v.toFixed(2), zero = true, height = 140, label }: {
  dates: string[]; values: (number | null)[]; color?: string; area?: boolean; fmt?: (v: number) => string; zero?: boolean; height?: number; label: string;
}) {
  const W = 640, H = height, L = 8, R = 8, T = 8, B = 18;
  const vs = values.filter((v): v is number => v !== null);
  if (vs.length < 2) return <p className="text-sm text-slate-500">Not enough data for {label}.</p>;
  const lo = Math.min(...vs, zero ? 0 : Infinity), hi = Math.max(...vs, zero ? 0 : -Infinity);
  const span = hi - lo || 1;
  const x = (i: number) => L + (i / (values.length - 1)) * (W - L - R);
  const y = (v: number) => T + (1 - (v - lo) / span) * (H - T - B);
  let path = "";
  let pen = false;
  let firstI = -1, lastI = -1;
  values.forEach((v, i) => {
    if (v === null) { pen = false; return; }          // gaps break the line instead of being bridged
    path += `${pen ? "L" : "M"}${x(i).toFixed(1)},${y(v).toFixed(1)} `;
    pen = true;
    if (firstI < 0) firstI = i;
    lastI = i;
  });
  path = path.trim();
  const areaPath = area && firstI >= 0 ? `${path} L${x(lastI).toFixed(1)},${y(0).toFixed(1)} L${x(firstI).toFixed(1)},${y(0).toFixed(1)} Z` : "";
  return (
    <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label={label} className="w-full">
      {zero && lo <= 0 && hi >= 0 && <line x1={L} x2={W - R} y1={y(0)} y2={y(0)} stroke="currentColor" opacity="0.25" strokeDasharray="3 3" />}
      {area && <path d={areaPath} fill={color} opacity="0.2" />}
      <path d={path} fill="none" stroke={color} strokeWidth="1.5" />
      <text x={L + 2} y={T + 8} fontSize="10" fill="currentColor" opacity="0.6">{fmt(hi)}</text>
      <text x={L + 2} y={H - B - 2} fontSize="10" fill="currentColor" opacity="0.6">{fmt(lo)}</text>
      <text x={L} y={H - 4} fontSize="10" fill="currentColor" opacity="0.6">{dates[0]}</text>
      <text x={W - R} y={H - 4} fontSize="10" textAnchor="end" fill="currentColor" opacity="0.6">{dates[dates.length - 1]}</text>
    </svg>
  );
}
