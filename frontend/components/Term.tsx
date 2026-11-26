"use client";
import { useId, useState } from "react";

/** Plain-English meanings for the jargon a newcomer will meet. Add terms here and use <Term k="..."> anywhere. */
export const GLOSSARY: Record<string, { label: string; text: string }> = {
  pe: { label: "P/E ratio", text: "How many rupees you pay for each ₹1 of the company's yearly profit. 20 means it would take about 20 years of today's profit to 'pay back' the price. Lower is cheaper, but a low number can also mean investors expect trouble." },
  roe: { label: "Return on equity", text: "Yearly profit as a share of the money shareholders have put into the company. 15% or more is generally considered good." },
  debt: { label: "Debt to equity", text: "How much the company has borrowed compared with its own money. 0.5 means 50 paise of debt for every ₹1 of its own money. High debt is risky when business slows." },
  dividend: { label: "Dividend", text: "A share of profit the company pays out to shareholders in cash, usually once or twice a year. Yield is that payment as a percentage of the share price." },
  rsi: { label: "RSI", text: "A 0 to 100 gauge of how fast a price has recently risen or fallen. Above 70 often means 'stretched after a big run-up', below 30 means 'fallen hard'. It says nothing about the company itself." },
  volatility: { label: "Volatility", text: "How much the price jumps around. A highly volatile stock can swing 10% in a month either way, so it is a bumpier ride." },
  drawdown: { label: "Drawdown", text: "How far a price has fallen from its highest point. A 40% drawdown means ₹100 became ₹60 at the worst moment." },
  average: { label: "Moving average", text: "The average price over the last 50 or 200 days. Price above its average means the recent direction is up; below means down." },
  sector: { label: "Sector", text: "The industry a company belongs to, such as banks, IT or pharma. Companies in one sector often rise and fall together." },
  diversification: { label: "Diversification", text: "Spreading your money across different companies and industries so that one bad outcome does not sink everything." },
  xirr: { label: "Yearly return", text: "Your average return per year, worked out from when you actually put money in. Only meaningful after a few months of holding." },
  avgcost: { label: "Average buy price", text: "What you paid per share on average across all your purchases, including charges." },
  pl: { label: "Profit or loss", text: "Today's value of what you hold minus what you paid for it. It is only 'real' when you sell." },
  marketcap: { label: "Market cap", text: "The total price of the whole company: share price times number of shares. Large caps are big, established companies; small caps are riskier and move more." },
  sip: { label: "SIP", text: "Systematic Investment Plan: putting in a fixed amount regularly (say monthly) instead of all at once. It spreads out the risk of buying at a bad moment." },
  index: { label: "Index fund", text: "A fund that simply holds all the stocks in an index such as the Nifty 50, at very low cost. Many beginners use it as a simple way to own a broad slice of the market." },
  high52: { label: "52-week high", text: "The highest price in the last year." },
  piotroski: { label: "Financial health score", text: "Nine yes/no checks of a company's finances (is it profitable, is debt falling, is cash flow positive...). 7 to 9 is strong, 0 to 3 is weak." },
  rank: { label: "Strength rank", text: "How a stock's recent price performance compares with the other stocks being tracked. 90 means it did better than 90% of them." },
  shortterm: { label: "Short term", text: "A few weeks to a few months. Prices over short periods are driven a lot by mood and news, so they are hard to predict." },
  longterm: { label: "Long term", text: "Several years. Over long periods, a company's actual earnings matter much more than day-to-day moves." },
};

export default function Term({ k, children }: { k: keyof typeof GLOSSARY | string; children?: React.ReactNode }) {
  const [open, setOpen] = useState(false);
  const id = useId();
  const g = GLOSSARY[k];
  if (!g) return <>{children ?? k}</>;
  return (
    <span className="relative inline-block">
      <button type="button" aria-describedby={open ? id : undefined} aria-expanded={open} onClick={() => setOpen((o) => !o)} onBlur={() => setOpen(false)}
        onMouseEnter={() => setOpen(true)} onMouseLeave={() => setOpen(false)}
        className="cursor-help border-b border-dotted border-slate-500 text-left dark:border-slate-400">{children ?? g.label}</button>
      {open && (
        <span id={id} role="tooltip" className="absolute left-0 top-full z-40 mt-1 w-64 rounded border border-slate-300 bg-white p-2 text-xs font-normal normal-case leading-snug text-slate-800 shadow-lg dark:border-slate-600 dark:bg-slate-900 dark:text-slate-100">
          <b>{g.label}.</b> {g.text}
        </span>)}
    </span>
  );
}
