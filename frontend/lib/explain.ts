// Plain-English explanations for an engineer who is not a trader. Shown next to every number.

export type Fmt = "x" | "pct" | "num" | "ratio";

export const RATIOS: { key: string; label: string; fmt: Fmt; meaning: string; good?: string }[] = [
  { key: "pe", label: "P/E (price / earnings)", fmt: "x", meaning: "Rupees you pay for one rupee of yearly profit. Like a 'payback period' in years if profit stayed flat.", good: "Lower is cheaper, but low can mean the market expects profits to fall." },
  { key: "pb", label: "P/B (price / book value)", fmt: "x", meaning: "Price versus the accounting value of what the company owns minus what it owes, per share.", good: "Lower is cheaper. Not meaningful for asset-light businesses like software." },
  { key: "ev_ebitda", label: "EV / EBITDA", fmt: "x", meaning: "Whole-business price (market value plus debt minus cash) divided by operating profit before interest, tax and depreciation.", good: "Lower is cheaper; useful for comparing companies with different debt levels." },
  { key: "roe", label: "ROE (return on equity)", fmt: "pct", meaning: "Profit divided by shareholders' money. How efficiently owners' capital is turned into profit.", good: "Higher is better. Be wary if it is high only because of heavy debt." },
  { key: "roce", label: "ROCE (return on capital employed)", fmt: "pct", meaning: "Operating profit divided by all capital in the business (equity plus debt). Debt-neutral version of ROE.", good: "Higher is better; compare with the company's borrowing cost." },
  { key: "debt_equity", label: "Debt / equity", fmt: "ratio", meaning: "Borrowings relative to owners' money. Like a leverage ratio: how much of the business runs on borrowed capital.", good: "Lower is safer; banks and utilities normally run higher." },
  { key: "gross_margin", label: "Gross margin", fmt: "pct", meaning: "Share of revenue left after the direct cost of making the product.", good: "Higher and stable is better." },
  { key: "operating_margin", label: "Operating margin", fmt: "pct", meaning: "Share of revenue left after running costs, before interest and tax.", good: "Higher is better." },
  { key: "net_margin", label: "Net margin", fmt: "pct", meaning: "Final profit as a share of revenue.", good: "Higher is better." },
  { key: "revenue_growth", label: "Revenue growth (YoY)", fmt: "pct", meaning: "Change in sales versus the previous financial year.", good: "Positive and steady is healthy." },
  { key: "earnings_growth", label: "Earnings growth (YoY)", fmt: "pct", meaning: "Change in net profit versus the previous financial year.", good: "Positive is better; one-off items can distort it." },
  { key: "dividend_yield", label: "Dividend yield", fmt: "pct", meaning: "Yearly dividend per share divided by price: the cash payout you would receive as a percentage of what you pay.", good: "Higher pays more now; very high can signal trouble." },
  { key: "peg", label: "PEG", fmt: "ratio", meaning: "P/E divided by earnings growth (in percent). Tries to adjust 'cheap' for how fast profits are growing.", good: "Around or below 1 is often called reasonable." },
];

export const RISK_TIPS: Record<string, string> = {
  cagr: "Compound annual growth rate: the steady yearly return that would give the same end result.",
  volatility: "Annualised standard deviation of daily returns: how wildly the price swings.",
  sharpe: "Return above the risk-free rate per unit of volatility. Roughly: above 1 is decent, above 2 is rare. Depends on the risk-free rate you set.",
  sortino: "Like Sharpe but only counts downside swings as risk.",
  calmar: "Yearly return divided by the worst peak-to-trough fall.",
  maxdd: "Worst fall from a previous high to a later low.",
  beta: "Typical move of the stock per 1% move of the Nifty. 1.5 means it tends to swing 50% more than the market.",
  alpha: "Average yearly return not explained by beta (Jensen's alpha). Noisy; do not over-read it.",
  corr: "How closely daily moves track the Nifty, from -1 to +1.",
  var: "Value at Risk: a one-day loss that was exceeded on only (1 - confidence) of days.",
  cvar: "Conditional VaR (expected shortfall): the average loss on those worst days.",
};

export const fmtVal = (v: number | null | undefined, f: Fmt): string => {
  if (v === null || v === undefined || Number.isNaN(v)) return "n/a";
  if (f === "pct") return `${(v * 100).toFixed(1)}%`;
  if (f === "x") return `${v.toFixed(1)}x`;
  if (f === "ratio") return v.toFixed(2);
  return v.toLocaleString("en-IN", { maximumFractionDigits: 2 });
};
export const pct = (v: number | null | undefined, d = 1) => (v === null || v === undefined ? "n/a" : `${(v * 100).toFixed(d)}%`);
export const num = (v: number | null | undefined, d = 2) => (v === null || v === undefined ? "n/a" : v.toFixed(d));
