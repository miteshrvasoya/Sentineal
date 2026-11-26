"use client";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useRef, useState } from "react";
import AngelOneCard from "@/components/AngelOneCard";
import InteractiveChart, { type Marker } from "@/components/InteractiveChart";
import SearchBox from "@/components/SearchBox";
import Term from "@/components/Term";
import { api, type Idea, type PfTxnIn, type Portfolio } from "@/lib/api";
import { inr, inrShort, pct0, pctS, today, tone } from "@/lib/format";

const card = "rounded-lg border border-slate-200 p-4 dark:border-slate-800";
const input = "rounded border border-slate-300 bg-white px-2 py-1 text-sm dark:border-slate-700 dark:bg-slate-900";
const lvl = { high: "border-red-500 bg-red-50 dark:bg-red-950/40", medium: "border-amber-500 bg-amber-50 dark:bg-amber-950/40", info: "border-slate-300 bg-slate-50 dark:border-slate-700 dark:bg-slate-900", good: "border-green-500 bg-green-50 dark:bg-green-950/40" } as const;
const lvlIcon = { high: "⚠️", medium: "⚠️", info: "ℹ️", good: "✅" } as const;

function Stat({ label, value, sub, cls = "", tip }: { label: React.ReactNode; value: string; sub?: string; cls?: string; tip?: string }) {
  return (
    <div className={card} title={tip}>
      <div className="text-xs text-slate-500">{label}</div>
      <div className={`mt-1 text-2xl font-semibold tabular-nums ${cls}`}>{value}</div>
      {sub && <div className={`text-xs tabular-nums ${cls || "text-slate-500"}`}>{sub}</div>}
    </div>
  );
}

function AddForm({ prefill, onDone }: { prefill: string; onDone: () => void }) {
  const [symbol, setSymbol] = useState(prefill);
  const [side, setSide] = useState<"buy" | "sell">("buy");
  const [qty, setQty] = useState("");
  const [price, setPrice] = useState("");
  const [date, setDate] = useState(today());
  const [fees, setFees] = useState("");
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  useEffect(() => { if (prefill) setSymbol(prefill); }, [prefill]);
  const latest = useMutation({ mutationFn: () => api.quote(symbol), onSuccess: (q) => setPrice(String(q.last)) , onError: () => setMsg({ ok: false, text: "Could not get the latest price. Type the price you paid." }) });
  const save = useMutation({
    mutationFn: (t: PfTxnIn) => api.pfAdd(t),
    onSuccess: (r) => { setMsg({ ok: true, text: r.message }); setQty(""); setPrice(""); setFees(""); onDone(); },
    onError: (e: Error) => setMsg({ ok: false, text: e.message }),
  });
  const total = Number(qty) * Number(price);
  return (
    <form data-tour="pf-add" onSubmit={(e) => { e.preventDefault(); setMsg(null); if (!symbol) { setMsg({ ok: false, text: "Pick a stock first." }); return; }
      save.mutate({ symbol, side, qty: Number(qty), price: Number(price), date, fees: fees ? Number(fees) : 0 }); }} className={`${card} space-y-3`}>
      <h2 className="text-lg font-semibold">Add a purchase or sale</h2>
      <div className="flex flex-wrap items-end gap-3">
        <div><div className="mb-1 text-xs text-slate-500">Stock</div>
          {symbol ? <div className="flex items-center gap-2 rounded border border-slate-300 px-2 py-1 text-sm dark:border-slate-700"><b>{symbol}</b><button type="button" onClick={() => setSymbol("")} className="text-slate-500 hover:text-red-600" aria-label="Change stock">×</button></div>
            : <SearchBox onPick={setSymbol} />}</div>
        <div role="group" aria-label="Buy or sell" className="flex overflow-hidden rounded border border-slate-300 text-sm dark:border-slate-700">
          <button type="button" onClick={() => setSide("buy")} aria-pressed={side === "buy"} className={`px-3 py-1 ${side === "buy" ? "bg-green-600 text-white" : ""}`}>I bought</button>
          <button type="button" onClick={() => setSide("sell")} aria-pressed={side === "sell"} className={`px-3 py-1 ${side === "sell" ? "bg-red-600 text-white" : ""}`}>I sold</button></div>
        <label className="text-sm"><div className="mb-1 text-xs text-slate-500">How many shares</div><input type="number" min="0" step="any" value={qty} onChange={(e) => setQty(e.target.value)} className={`${input} w-28`} required /></label>
        <label className="text-sm"><div className="mb-1 flex items-center gap-1 text-xs text-slate-500">Price per share ₹
          {symbol && <button type="button" onClick={() => latest.mutate()} className="text-indigo-600 underline dark:text-indigo-300">use latest</button>}</div>
          <input type="number" min="0" step="any" value={price} onChange={(e) => setPrice(e.target.value)} className={`${input} w-32`} required /></label>
        <label className="text-sm"><div className="mb-1 text-xs text-slate-500">Date</div><input type="date" max={today()} value={date} onChange={(e) => setDate(e.target.value)} className={input} required /></label>
        <label className="text-sm"><div className="mb-1 text-xs text-slate-500">Charges ₹ (optional)</div><input type="number" min="0" step="any" value={fees} onChange={(e) => setFees(e.target.value)} className={`${input} w-24`} placeholder="0" /></label>
        <button disabled={save.isPending} className="rounded bg-indigo-600 px-4 py-1.5 text-sm font-medium text-white disabled:opacity-50">{save.isPending ? "Saving…" : "Save"}</button>
      </div>
      {total > 0 && <p className="text-xs text-slate-500">{side === "buy" ? "You paid" : "You received"} about {inr(total)} before charges.</p>}
      {msg && <p role={msg.ok ? "status" : "alert"} className={`text-sm ${msg.ok ? "text-green-700 dark:text-green-400" : "text-red-600"}`}>{msg.text}</p>}
      <BulkImport onDone={onDone} />
    </form>
  );
}

function BulkImport({ onDone }: { onDone: () => void }) {
  const [text, setText] = useState("");
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const imp = useMutation({ mutationFn: (t: PfTxnIn[]) => api.pfAdd({ transactions: t }), onSuccess: (r) => { setMsg({ ok: true, text: `Imported ${r.added} transactions. ${r.message}` }); setText(""); onDone(); }, onError: (e: Error) => setMsg({ ok: false, text: e.message }) });
  const parse = (): PfTxnIn[] | string => {
    const out: PfTxnIn[] = [];
    for (const [i, line] of text.split("\n").map((l) => l.trim()).filter(Boolean).entries()) {
      const c = line.split(/[,\t]/).map((x) => x.trim());
      if (i === 0 && /symbol|stock/i.test(c[0])) continue;
      const [symbol, side, qty, price, date, fees] = c;
      if (!symbol || !/^(buy|sell)$/i.test(side ?? "") || !(Number(qty) > 0) || !(Number(price) > 0) || !/^\d{4}-\d{2}-\d{2}$/.test(date ?? "")) return `Line ${i + 1} is not in the format: SYMBOL, buy or sell, shares, price, YYYY-MM-DD`;
      out.push({ symbol: symbol.toUpperCase(), side: side.toLowerCase() as "buy" | "sell", qty: Number(qty), price: Number(price), date, fees: fees ? Number(fees) : 0 });
    }
    return out.length ? out : "Paste at least one line.";
  };
  return (
    <details className="text-sm"><summary className="cursor-pointer text-slate-600 dark:text-slate-400">Have many trades? Paste them all at once</summary>
      <p className="my-1 text-xs text-slate-500">One per line: SYMBOL, buy or sell, shares, price, date (YYYY-MM-DD), optional charges. Example: <code>TCS, buy, 10, 3450.5, 2024-06-12</code>. You can copy rows from a spreadsheet.</p>
      <textarea value={text} onChange={(e) => setText(e.target.value)} rows={4} aria-label="Trades to import" className={`${input} w-full font-mono text-xs`} />
      <button type="button" onClick={() => { const r = parse(); if (typeof r === "string") setMsg({ ok: false, text: r }); else { setMsg(null); imp.mutate(r); } }} disabled={imp.isPending}
        className="mt-1 rounded border border-slate-300 px-3 py-1 text-sm dark:border-slate-700">Import</button>
      {msg && <p role={msg.ok ? "status" : "alert"} className={`mt-1 text-sm ${msg.ok ? "text-green-700 dark:text-green-400" : "text-red-600"}`}>{msg.text}</p>}
    </details>
  );
}

function Dashboard({ p }: { p: Portfolio }) {
  const s = p.summary;
  const hist = useQuery({ queryKey: ["pfhist"], queryFn: api.pfHistory });
  const [days, setDays] = useState(100000);
  const txq = useQuery({ queryKey: ["pftx"], queryFn: api.pfTxns, retry: false });
  const all = hist.data?.points ?? [];
  const cutoff = days >= 100000 || !all.length ? "" : new Date(new Date(all[all.length - 1].date).getTime() - days * 864e5).toISOString().slice(0, 10);
  const pts = all.filter((x) => x.date >= cutoff);
  const markers: Marker[] = (txq.data ?? []).map((t) => ({ date: t.date, kind: t.side, label: t.symbol, detail: `${t.qty} ${t.symbol} at ${inr(t.price, 2)}` }));
  const flagged = new Map<string, "high" | "medium">();
  p.checkup.forEach((c) => c.symbols.forEach((x) => { if (c.level === "high" || (c.level === "medium" && flagged.get(x) !== "high")) flagged.set(x, c.level as "high" | "medium"); }));
  return (
    <>
      <div data-tour="pf-summary" className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Stat label="What it is worth today" value={inrShort(s.value)} sub={`${s.holdings} stock${s.holdings === 1 ? "" : "s"}`} />
        <Stat label="What you put in" value={inrShort(s.invested)} />
        <Stat label={<Term k="pl">Profit or loss</Term>} value={`${s.pl >= 0 ? "+" : ""}${inrShort(s.pl)}`} sub={pctS(s.pl_pct)} cls={tone(s.pl)} />
        <Stat label="Today" value={`${s.day_change >= 0 ? "+" : ""}${inrShort(s.day_change)}`} sub={pctS(s.day_change_pct, 2)} cls={tone(s.day_change)} />
      </div>
      <p className="text-xs text-slate-500">
        {s.annual_return !== null ? <>Your <Term k="xirr">average yearly return</Term> so far: <b className={tone(s.annual_return)}>{pctS(s.annual_return)}</b>. </> : <>{s.annual_return_note ?? ""} </>}
        {s.realised !== 0 && <>Profit already locked in from sales: <b className={tone(s.realised)}>{inrShort(s.realised)}</b>. </>}
        {s.unpriced.length > 0 && <span className="text-amber-600">No price yet for {s.unpriced.join(", ")}.</span>}
      </p>

      {p.checkup.length > 0 && (
        <section data-tour="pf-checkup" className={card}>
          <h2 className="mb-2 text-lg font-semibold">Portfolio check-up</h2>
          <ul className="space-y-2">{p.checkup.map((c, i) => (
            <li key={i} className={`rounded border-l-4 p-2 text-sm ${lvl[c.level]}`}><span className="mr-1">{lvlIcon[c.level]}</span><b>{c.title}.</b> {c.text}
              {c.symbols.length > 0 && <span className="ml-1">{c.symbols.slice(0, 5).map((x) => <Link key={x} href={`/s/${x}`} className="mr-1 text-indigo-600 underline dark:text-indigo-300">{x}</Link>)}</span>}</li>))}</ul>
          <p className="mt-2 text-xs text-slate-500">These are observations about how your money is spread, not instructions. What is right depends on your goals and how much risk you can accept.</p>
        </section>)}

      {all.length > 1 && (
        <section data-tour="pf-chart" className={card}>
          <div className="mb-1 flex flex-wrap items-center gap-2"><h2 className="text-lg font-semibold">How your money has grown</h2>
            <span className="ml-auto flex gap-1 text-xs">{([["3M", 92], ["6M", 183], ["1Y", 365], ["All", 100000]] as const).map(([l, d]) => <button key={l} onClick={() => setDays(d)} aria-pressed={days === d} className={`rounded px-2 py-0.5 ${days === d ? "bg-indigo-600 text-white" : "bg-slate-200 dark:bg-slate-800"}`}>{l}</button>)}</span></div>
          {pts.length > 1 && <InteractiveChart series={[{ name: "Worth today", color: "#6366f1", area: true, points: pts.map((x) => ({ date: x.date, v: x.value })) }, { name: "Money you put in", color: "#64748b", dashed: true, points: pts.map((x) => ({ date: x.date, v: x.put_in })) }]}
            markers={markers} fmt={(v) => inrShort(v)} label="Portfolio value and money put in" valueName="Worth" />}
          <p className="text-xs text-slate-500">When the purple line is above the dashed grey line you are in profit. Hover to read any day; green and red triangles are your purchases and sales. {hist.data?.note}</p>
        </section>)}

      <section data-tour="pf-holdings" className={card}>
        <h2 className="mb-2 text-lg font-semibold">What you own</h2>
        <div className="overflow-x-auto"><table className="w-full text-sm tabular-nums">
          <thead className="text-left text-xs text-slate-500"><tr><th>Stock</th><th>Shares</th><th><Term k="avgcost">Avg buy price</Term></th><th>Price now</th><th>Worth</th><th><Term k="pl">Profit / loss</Term></th><th>Today</th><th>Share of total</th></tr></thead>
          <tbody>{p.positions.map((r) => (
            <tr key={r.symbol} className="border-t border-slate-200 dark:border-slate-800">
              <td className="py-1.5"><Link href={`/s/${r.symbol}`} className="font-medium text-indigo-600 hover:underline dark:text-indigo-300">{r.symbol}</Link>
                {flagged.has(r.symbol) && <span title="See the check-up above" className="ml-1">⚠️</span>}
                {r.source === "angelone" && <span title="Imported from Angel One. No purchase date is known." className="ml-1 rounded bg-sky-100 px-1 text-[10px] text-sky-800 dark:bg-sky-950 dark:text-sky-300">Angel One</span>}<div className="max-w-[14rem] truncate text-xs text-slate-500">{r.name}</div></td>
              <td>{r.qty.toLocaleString("en-IN", { maximumFractionDigits: 4 })}</td><td>{inr(r.avg_cost, 2)}</td><td>{r.price === null ? "n/a" : inr(r.price, 2)}</td><td>{inr(r.value)}</td>
              <td className={tone(r.pl)}>{r.pl === undefined ? "n/a" : `${r.pl >= 0 ? "+" : ""}${inr(r.pl)}`}<div className="text-xs">{pctS(r.pl_pct)}</div></td>
              <td className={tone(r.day_change_pct)}>{pctS(r.day_change_pct, 2)}</td>
              <td>{pct0(r.weight)}<div className="mt-0.5 h-1.5 w-16 rounded bg-slate-200 dark:bg-slate-800"><div className="h-1.5 rounded bg-indigo-500" style={{ width: `${Math.min(100, (r.weight ?? 0) * 100)}%` }} /></div></td></tr>))}</tbody></table></div>
        {p.allocation.by_sector.length > 0 && (
          <div className="mt-3"><h3 className="mb-1 text-sm font-semibold">Spread across <Term k="sector">industries</Term></h3>
            <div className="space-y-1">{p.allocation.by_sector.map((a) => (
              <div key={a.sector} className="flex items-center gap-2 text-xs"><span className="w-28 truncate">{a.sector}</span><div className="h-2 flex-1 rounded bg-slate-200 dark:bg-slate-800"><div className="h-2 rounded bg-indigo-500" style={{ width: `${a.weight * 100}%` }} /></div><span className="w-10 text-right tabular-nums">{pct0(a.weight)}</span></div>))}</div></div>)}
      </section>
      {p.closed.length > 0 && (
        <details className={card}><summary className="cursor-pointer font-semibold">Stocks you have sold ({p.closed.length})</summary>
          <table className="mt-2 w-full text-sm tabular-nums"><thead className="text-left text-xs text-slate-500"><tr><th>Stock</th><th>You paid</th><th>You received</th><th>Profit / loss</th></tr></thead>
            <tbody>{p.closed.map((c) => <tr key={c.symbol} className="border-t border-slate-200 dark:border-slate-800"><td className="py-1">{c.symbol}</td><td>{inr(c.bought)}</td><td>{inr(c.sold)}</td><td className={tone(c.realised)}>{inr(c.realised)}</td></tr>)}</tbody></table></details>)}
    </>
  );
}

function History() {
  const qc = useQueryClient();
  const tx = useQuery({ queryKey: ["pftx"], queryFn: api.pfTxns });
  const del = useMutation({ mutationFn: (id: number) => api.pfDelete(id), onSuccess: () => { qc.invalidateQueries({ queryKey: ["portfolio"] }); qc.invalidateQueries({ queryKey: ["pftx"] }); qc.invalidateQueries({ queryKey: ["pfhist"] }); } });
  if (!tx.data?.length) return null;
  return (
    <details className={card}><summary className="cursor-pointer font-semibold">Everything you have entered ({tx.data.length})</summary>
      {del.error && <p role="alert" className="mt-1 text-sm text-red-600">{(del.error as Error).message}</p>}
      <div className="mt-2 max-h-72 overflow-auto"><table className="w-full text-sm tabular-nums"><thead className="sticky top-0 bg-white text-left text-xs text-slate-500 dark:bg-slate-950"><tr><th>Date</th><th>Stock</th><th></th><th>Shares</th><th>Price</th><th>Amount</th><th></th></tr></thead>
        <tbody>{tx.data.map((t) => (
          <tr key={t.id} className="border-t border-slate-200 dark:border-slate-800"><td className="py-1">{t.date}</td><td>{t.symbol}</td><td className={t.side === "buy" ? "text-green-700 dark:text-green-400" : "text-red-600"}>{t.side === "buy" ? "Bought" : "Sold"}</td><td>{t.qty}</td><td>{inr(t.price, 2)}</td><td>{inr(t.amount)}</td>
            <td><button onClick={() => { if (confirm(`Delete this ${t.side} of ${t.symbol}?`)) del.mutate(t.id); }} className="text-xs text-slate-500 hover:text-red-600">delete</button></td></tr>))}</tbody></table></div></details>
  );
}

const chip = { "Looks strong": "bg-green-600", Mixed: "bg-amber-500", "Looks weak": "bg-red-600", "Not enough data": "bg-slate-400" } as Record<string, string>;
const Chip = ({ i }: { i?: Idea }) => (i ? <span className={`whitespace-nowrap rounded px-1.5 py-0.5 text-xs text-white ${chip[i.label] ?? chip["Not enough data"]}`}>{i.label}</span> : <span className="text-xs text-slate-400">n/a</span>);

/** The stocks you own get the same scrutiny as new ideas. */
function HoldingsReview() {
  const q = useQuery({ queryKey: ["holdreview"], queryFn: api.holdingsReview, retry: false });
  if (!q.data?.holdings.length) return null;
  return (
    <section data-tour="pf-review" className={card}>
      <h2 className="mb-1 text-lg font-semibold">How the stocks you own look right now</h2>
      <p className="mb-2 text-xs text-slate-500">The same checklists used on Find stocks, applied to your own holdings. A weak label is a prompt to look closer, not a reason to sell.</p>
      <div className="overflow-x-auto"><table className="w-full text-sm"><thead className="text-left text-xs text-slate-500"><tr><th>Stock</th><th>Short term</th><th>Long term</th><th>Worth a look</th></tr></thead>
        <tbody>{q.data.holdings.map((h) => (
          <tr key={h.symbol} className="border-t border-slate-200 align-top dark:border-slate-800">
            <td className="py-1.5"><Link href={`/s/${h.symbol}`} className="font-medium text-indigo-600 hover:underline dark:text-indigo-300">{h.symbol}</Link></td>
            <td><Chip i={h.short} /></td><td><Chip i={h.long} /></td>
            <td className="text-xs text-slate-600 dark:text-slate-400">{h.available ? ((h.short?.watch_out[0] ?? h.long?.watch_out[0]) ?? "Nothing flagged") : "Prices not loaded yet. Press Refresh prices."}</td></tr>))}</tbody></table></div>
    </section>
  );
}

function Welcome() {
  return (
    <section className={`${card} space-y-3`} data-tour="pf-welcome">
      <h2 className="text-xl font-semibold">Welcome 👋 Let&apos;s track your investments</h2>
      <p className="text-sm text-slate-600 dark:text-slate-400">This is a place to see what you own, how it is doing, and to look for new ideas. It does not buy or sell anything: it only reads prices and does the sums. Start with whichever fits you:</p>
      <ol className="grid gap-3 text-sm sm:grid-cols-2 lg:grid-cols-4">
        <li className="rounded border border-slate-200 p-3 dark:border-slate-800"><b>1. I already own stocks</b><br />Add them below (what you bought, how many, at what price, when). You will see profit, loss and a health check of how your money is spread.</li>
        <li className="rounded border border-slate-200 p-3 dark:border-slate-800"><b>2. I want ideas</b><br />Go to <Link className="text-indigo-600 underline dark:text-indigo-300" href="/discover">Find stocks</Link> for short-term and long-term ideas, each explained in plain words with the risks.</li>
        <li className="rounded border border-slate-200 p-3 dark:border-slate-800"><b>3. I use Angel One</b><br />Connect it (read-only) and your holdings are imported automatically. Set it up with the Angel One card below.</li>
        <li className="rounded border border-slate-200 p-3 dark:border-slate-800"><b>4. I am brand new</b><br />Read <Link className="text-indigo-600 underline dark:text-indigo-300" href="/learn">Learn</Link>, starting with the basics, then take the Tour (top right).</li>
      </ol>
    </section>
  );
}

function Home() {
  const qc = useQueryClient();
  const sp = useSearchParams();
  const router = useRouter();
  const prefill = (sp.get("add") ?? "").toUpperCase();
  const pf = useQuery({ queryKey: ["portfolio"], queryFn: api.portfolio });
  const refresh = useMutation({ mutationFn: api.pfRefresh, onSuccess: () => { ["portfolio", "pfhist"].forEach((k) => qc.invalidateQueries({ queryKey: [k] })); qc.invalidateQueries({ queryKey: ["watchsummary"] }); } });
  const refreshed = useRef(false);
  useEffect(() => {   // once per visit, bring prices up to date if any holding is stale
    const stale = pf.data?.positions.some((r) => r.stale_days === null || r.stale_days > 1);
    if (!refreshed.current && stale) { refreshed.current = true; refresh.mutate(); }
  }, [pf.data]); // eslint-disable-line react-hooks/exhaustive-deps
  const changed = () => { ["portfolio", "pftx", "pfhist"].forEach((k) => qc.invalidateQueries({ queryKey: [k] })); if (prefill) router.replace("/"); };
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-3"><h1 className="text-2xl font-semibold">My investments</h1>
        {!pf.data?.empty && <button onClick={() => refresh.mutate()} disabled={refresh.isPending} className="rounded border border-slate-300 px-3 py-1 text-sm dark:border-slate-700">{refresh.isPending ? "Updating prices…" : "Refresh prices"}</button>}
        {refresh.data && refresh.data.problems.length > 0 && <span className="text-xs text-amber-600">Could not update: {refresh.data.problems.map((x) => x.symbol).join(", ")}</span>}</div>
      {pf.isLoading && <div className="skeleton h-40" />}
      {pf.error && <p role="alert" className="text-sm text-red-600">{(pf.error as Error).message}</p>}
      {pf.data?.empty && <Welcome />}
      {pf.data && !pf.data.empty && <Dashboard p={pf.data} />}
      {pf.data && !pf.data.empty && <HoldingsReview />}
      {pf.data && <AngelOneCard compact={!pf.data.empty} onlyCount={pf.data.broker?.only.length ?? 0} />}
      {pf.data && <AddForm prefill={prefill} onDone={changed} />}
      <History />
      <p className="text-xs text-slate-500">Educational tool, not investment advice. Prices come from free public sources and can be delayed or wrong; check your broker for the real numbers. Profit and loss use the average price you paid; taxes are not included.</p>
    </div>
  );
}

export default function Page() { return <Suspense fallback={<div className="skeleton h-96" />}><Home /></Suspense>; }
