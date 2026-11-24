"use client";
import type { RedFlags } from "@/lib/api";

const bar = { high: "border-red-600", medium: "border-amber-500", low: "border-slate-400" } as const;

export default function RedFlagList({ d }: { d: RedFlags }) {
  return (
    <div>
      {d.flags.length === 0 ? <p className="text-sm text-green-700 dark:text-green-400">No rule fired. Checked: {d.checked.join(", ")}. That is not a clean bill of health.</p> : (
        <ul className="space-y-1.5">{d.flags.map((f) => (
          <li key={f.id} className={`border-l-2 pl-2 text-sm ${bar[f.severity]}`} title={JSON.stringify(f.evidence)}>
            <span className={`mr-1 rounded px-1 text-[10px] uppercase text-white ${f.severity === "high" ? "bg-red-600" : f.severity === "medium" ? "bg-amber-500" : "bg-slate-500"}`}>{f.severity}</span>{f.message}</li>))}</ul>)}
      <p className="mt-1 text-xs text-slate-500">{d.note}</p>
    </div>
  );
}
