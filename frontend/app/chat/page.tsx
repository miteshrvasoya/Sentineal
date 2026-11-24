"use client";
import { useMutation } from "@tanstack/react-query";
import { Suspense, useEffect, useRef, useState } from "react";
import { api, type ChatOut } from "@/lib/api";

type Msg = { role: "user" | "assistant"; content: string; out?: ChatOut };
const EXAMPLES = ["Which stocks have an RSI below 40?", "How is the market breadth?", "Any warning signs for TCS?", "Compare INFY and TCS", "What does volatility mean?"];

function Turn({ m, onAsk }: { m: Msg; onAsk: (q: string) => void }) {
  if (m.role === "user") return <div className="ml-auto max-w-[80%] rounded-lg bg-indigo-600 px-3 py-2 text-sm text-white">{m.content}</div>;
  const o = m.out;
  const steps = o?.steps ?? [], cites = o?.citations ?? [], follow = o?.follow_ups ?? [], problems = o?.problems ?? [];
  return (
    <div className="max-w-[90%] space-y-2 rounded-lg border border-slate-200 px-3 py-2 text-sm dark:border-slate-800">
      {o && !o.available && <p className="text-slate-600 dark:text-slate-400" role="status">{o.reason}</p>}
      {o?.error && <p className="text-amber-700 dark:text-amber-400" role="alert">{o.error}</p>}
      {o?.withheld && <p className="text-amber-700 dark:text-amber-400" role="alert">I produced an answer that broke a safety rule even after a retry, so I am not showing it ({problems.join("; ")}). Try rephrasing, or ask what data I can look at.</p>}
      {o?.answer && <p className="whitespace-pre-wrap">{m.content}</p>}
      {steps.length > 0 && (
        <details data-tour="chat-steps"><summary className="cursor-pointer text-xs text-slate-500">What I looked up ({steps.length})</summary>
          <ul className="mt-1 space-y-1 text-xs">{steps.map((s) => (
            <li key={s.id} className="rounded bg-slate-100 p-1.5 dark:bg-slate-800"><b>{s.id}</b> {s.tool}({JSON.stringify(s.args)}) {s.reason && <span className="text-slate-500">: {s.reason}</span>}
              {s.error ? <div className="text-amber-600">{s.error}</div> : <div className="mt-0.5 line-clamp-3 break-all font-mono text-[10px] text-slate-500">{s.result}</div>}</li>))}</ul></details>)}
      {cites.length > 0 && <p className="text-[11px] text-slate-500">Based on: {cites.map((c) => <span key={c} className="mr-1 rounded bg-slate-200 px-1 dark:bg-slate-800">{c}</span>)}</p>}
      {follow.length > 0 && <div className="flex flex-wrap gap-1">{follow.map((f) => <button key={f} onClick={() => onAsk(f)} className="rounded border border-slate-300 px-2 py-0.5 text-xs hover:bg-slate-100 dark:border-slate-700 dark:hover:bg-slate-800">{f}</button>)}</div>}
      {o?.available && o.answer && <p className="text-[11px] text-slate-500">{o.badge}. {o.meta?.model ? `${o.meta.provider}/${o.meta.model}. ` : ""}Read-only: I cannot trade or change anything.</p>}
    </div>
  );
}

function View() {
  const [msgs, setMsgs] = useState<Msg[]>([]);
  const [text, setText] = useState("");
  const end = useRef<HTMLDivElement>(null);
  const m = useMutation({
    mutationFn: (q: string) => api.chat(q, msgs.filter((x) => x.content).map((x) => ({ role: x.role, content: x.content }))),
    onSuccess: (out) => setMsgs((c) => [...c, { role: "assistant", content: out.answer ?? "", out }]),
  });
  useEffect(() => { end.current?.scrollIntoView({ behavior: "smooth" }); }, [msgs, m.isPending]);
  const ask = (q: string) => { if (!q.trim() || m.isPending) return; setMsgs((c) => [...c, { role: "user", content: q }]); setText(""); m.mutate(q); };
  return (
    <div className="mx-auto flex max-w-3xl flex-col gap-3">
      <div className="flex flex-wrap items-center gap-3"><h1 className="text-2xl font-semibold">Ask QuantLens</h1>
        <span className="rounded bg-violet-600 px-2 py-0.5 text-xs text-white">AI-generated, may be wrong, not investment advice</span></div>
      <p className="text-sm text-slate-600 dark:text-slate-400">A read-only assistant. It looks things up in the data stored here (screens, red flags, facts, models, headlines) and explains what it finds, citing each lookup. It cannot trade, cannot change settings, and will not tell you what to buy.</p>
      <div className="space-y-3" aria-live="polite">
        {msgs.length === 0 && <div className="flex flex-wrap gap-2" data-tour="chat-examples">{EXAMPLES.map((e) => <button key={e} onClick={() => ask(e)} className="rounded border border-slate-300 px-2 py-1 text-sm hover:bg-slate-100 dark:border-slate-700 dark:hover:bg-slate-800">{e}</button>)}</div>}
        {msgs.map((x, i) => <Turn key={i} m={x} onAsk={ask} />)}
        {m.isPending && <p className="text-sm text-slate-500" role="status">Looking things up…</p>}
        {m.error && <p className="text-sm text-red-600" role="alert">{(m.error as Error).message}</p>}
        <div ref={end} />
      </div>
      <form onSubmit={(e) => { e.preventDefault(); ask(text); }} className="flex gap-2" data-tour="chat-box">
        <input value={text} onChange={(e) => setText(e.target.value)} maxLength={600} placeholder="Ask about the stored stocks…" aria-label="Your question"
          className="flex-1 rounded border border-slate-300 bg-white px-3 py-2 text-sm dark:border-slate-700 dark:bg-slate-900" />
        <button disabled={m.isPending || !text.trim()} className="rounded bg-indigo-600 px-4 py-2 text-sm text-white disabled:opacity-50">Ask</button>
      </form>
      <p className="text-xs text-slate-500">Educational tool, not investment advice. Answers are checked for advice, invented numbers and fake citations; anything that fails is withheld.</p>
    </div>
  );
}

export default function Page() { return <Suspense fallback={<div className="skeleton h-96" />}><View /></Suspense>; }
