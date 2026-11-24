"""Fundamentals: statement extraction, ratios, Piotroski F-score, Altman Z, Graham number, 2-stage DCF.

Everything here is a pure function of numbers, so it is unit-testable without any network.
Statement line-item names differ between data vendors and companies, so extraction uses alias lists and
returns None (never 0) when an item is missing; every score reports which criteria it could not evaluate.

Educational use only. Free statement data is often incomplete or restated, and none of these scores is a forecast.
"""
from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field, fields
from typing import Any

import pandas as pd

FINANCIAL_SECTORS = {"financial services", "financials", "banks", "bank", "nbfc", "insurance", "banking"}


@dataclass
class Year:
    revenue: float | None = None
    gross_profit: float | None = None
    operating_income: float | None = None
    ebit: float | None = None
    ebitda: float | None = None
    net_income: float | None = None
    interest_expense: float | None = None
    cfo: float | None = None          # operating cash flow
    capex: float | None = None        # stored as a positive magnitude
    total_assets: float | None = None
    current_assets: float | None = None
    current_liabilities: float | None = None
    total_liabilities: float | None = None
    total_debt: float | None = None
    long_term_debt: float | None = None
    cash: float | None = None
    equity: float | None = None
    retained_earnings: float | None = None
    shares: float | None = None

    @property
    def fcf(self) -> float | None:
        return None if self.cfo is None or self.capex is None else self.cfo - self.capex


@dataclass
class Inputs:
    symbol: str
    sector: str = ""
    currency: str = "INR"
    price: float | None = None
    market_cap: float | None = None
    shares: float | None = None
    eps: float | None = None
    bvps: float | None = None
    dividend_rate: float | None = None     # currency units per share per year
    cur: Year = field(default_factory=Year)
    prev: Year | None = None
    fetched_at: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @staticmethod
    def from_dict(d: dict[str, Any]) -> Inputs:
        yf = {f.name for f in fields(Year)}
        mk = lambda x: Year(**{k: v for k, v in x.items() if k in yf}) if x else None  # noqa: E731
        base = {k: v for k, v in d.items() if k not in ("cur", "prev")}
        return Inputs(**base, cur=mk(d.get("cur")) or Year(), prev=mk(d.get("prev")))


ALIASES: dict[str, list[str]] = {
    "revenue": ["Total Revenue", "Operating Revenue", "Revenue"],
    "gross_profit": ["Gross Profit"],
    "operating_income": ["Operating Income", "Total Operating Income As Reported"],
    "ebit": ["EBIT"],
    "ebitda": ["EBITDA", "Normalized EBITDA"],
    "net_income": ["Net Income", "Net Income Common Stockholders"],
    "interest_expense": ["Interest Expense", "Interest Expense Non Operating"],
    "cfo": ["Operating Cash Flow", "Total Cash From Operating Activities", "Cash Flow From Continuing Operating Activities"],
    "capex": ["Capital Expenditure", "Purchase Of PPE", "Capital Expenditures"],
    "total_assets": ["Total Assets"],
    "current_assets": ["Current Assets", "Total Current Assets"],
    "current_liabilities": ["Current Liabilities", "Total Current Liabilities"],
    "total_liabilities": ["Total Liabilities Net Minority Interest", "Total Liabilities"],
    "total_debt": ["Total Debt"],
    "long_term_debt": ["Long Term Debt", "Long Term Debt And Capital Lease Obligation"],
    "cash": ["Cash And Cash Equivalents", "Cash Cash Equivalents And Short Term Investments"],
    "equity": ["Stockholders Equity", "Common Stock Equity", "Total Equity Gross Minority Interest"],
    "retained_earnings": ["Retained Earnings"],
    "shares": ["Ordinary Shares Number", "Share Issued"],
}
STATEMENT_OF = {k: "income" for k in ("revenue", "gross_profit", "operating_income", "ebit", "ebitda", "net_income", "interest_expense")}
STATEMENT_OF.update({k: "cashflow" for k in ("cfo", "capex")})
STATEMENT_OF.update({k: "balance" for k in ("total_assets", "current_assets", "current_liabilities", "total_liabilities", "total_debt",
                                            "long_term_debt", "cash", "equity", "retained_earnings", "shares")})


def _num(v: Any) -> float | None:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(f) or math.isinf(f) else f


def _pick(df: pd.DataFrame | None, aliases: list[str], col: int) -> float | None:
    if df is None or df.empty or col >= df.shape[1]:
        return None
    cols = sorted(df.columns, reverse=True)       # newest period first
    for name in aliases:
        if name in df.index:
            return _num(df.loc[name, cols[col]])
    return None


def extract_inputs(symbol: str, info: dict[str, Any], income: pd.DataFrame | None, balance: pd.DataFrame | None,
                   cashflow: pd.DataFrame | None, fetched_at: int = 0) -> Inputs:
    """Build Inputs from a yfinance-shaped payload: statements have line items as rows and period-end dates as columns."""
    frames = {"income": income, "balance": balance, "cashflow": cashflow}

    def year(col: int) -> Year:
        y = Year(**{k: _pick(frames[STATEMENT_OF[k]], al, col) for k, al in ALIASES.items()})
        if y.capex is not None:
            y.capex = abs(y.capex)
        if y.total_debt is None and y.long_term_debt is not None:
            y.total_debt = y.long_term_debt
        return y

    cur = year(0)
    prev = year(1) if any(f is not None and f.shape[1] > 1 for f in frames.values()) else None
    price = _num(info.get("currentPrice")) or _num(info.get("regularMarketPrice")) or _num(info.get("previousClose"))
    return Inputs(symbol=symbol, sector=str(info.get("sector") or ""), currency=str(info.get("currency") or "INR"), price=price,
                  market_cap=_num(info.get("marketCap")), shares=_num(info.get("sharesOutstanding")) or cur.shares,
                  eps=_num(info.get("trailingEps")), bvps=_num(info.get("bookValue")), dividend_rate=_num(info.get("dividendRate")),
                  cur=cur, prev=prev, fetched_at=fetched_at)


def _div(a: float | None, b: float | None) -> float | None:
    return None if a is None or b is None or b == 0 else a / b


def _growth(cur: float | None, prev: float | None) -> float | None:
    return None if cur is None or prev is None or prev <= 0 else cur / prev - 1


def is_financial(sector: str) -> bool:
    return sector.strip().lower() in FINANCIAL_SECTORS


def ratios(i: Inputs) -> dict[str, float | None]:
    """Headline ratios. Fractions (0.15 = 15%) for margins/returns/growth; multiples for valuation."""
    c, p = i.cur, i.prev
    ebit = c.ebit if c.ebit is not None else c.operating_income
    ev = None if i.market_cap is None else i.market_cap + (c.total_debt or 0.0) - (c.cash or 0.0)
    cap_employed = None if c.total_assets is None or c.current_liabilities is None else c.total_assets - c.current_liabilities
    pe = _div(i.price, i.eps) if (i.eps or 0) > 0 else None
    eg = _growth(c.net_income, p.net_income if p else None)
    return {
        "pe": pe, "pb": _div(i.price, i.bvps) if (i.bvps or 0) > 0 else None,
        "ev_ebitda": _div(ev, c.ebitda) if (c.ebitda or 0) > 0 else None,
        "roe": _div(c.net_income, c.equity) if (c.equity or 0) > 0 else None,
        "roce": _div(ebit, cap_employed),
        "debt_equity": _div(c.total_debt, c.equity) if (c.equity or 0) > 0 else None,
        "gross_margin": _div(c.gross_profit, c.revenue), "operating_margin": _div(c.operating_income, c.revenue),
        "net_margin": _div(c.net_income, c.revenue),
        "revenue_growth": _growth(c.revenue, p.revenue if p else None), "earnings_growth": eg,
        "dividend_yield": _div(i.dividend_rate, i.price),
        "peg": (pe / (eg * 100)) if pe is not None and eg is not None and eg > 0 else None,
        "fcf_margin": _div(c.fcf, c.revenue), "market_cap": i.market_cap, "ev": ev,
    }


def piotroski(i: Inputs) -> dict[str, Any]:
    """Piotroski F-score: nine yes/no tests of profitability, leverage/liquidity and efficiency (higher = stronger).
    Criteria that cannot be evaluated because data is missing are 'na' and excluded from the score."""
    c, p = i.cur, i.prev
    roa = _div(c.net_income, c.total_assets)
    roa_p = _div(p.net_income, p.total_assets) if p else None
    lev = _div(c.total_debt, c.total_assets)
    lev_p = _div(p.total_debt, p.total_assets) if p else None
    cr = _div(c.current_assets, c.current_liabilities)
    cr_p = _div(p.current_assets, p.current_liabilities) if p else None
    gm = _div(c.gross_profit, c.revenue)
    gm_p = _div(p.gross_profit, p.revenue) if p else None
    at = _div(c.revenue, c.total_assets)
    at_p = _div(p.revenue, p.total_assets) if p else None

    def t(ok: Any) -> str:
        return "na" if ok is None else ("pass" if ok else "fail")

    def gt(a: float | None, b: float | None) -> bool | None:
        return None if a is None or b is None else a > b
    rows = [
        ("roa_positive", "Return on assets is positive", t(None if roa is None else roa > 0)),
        ("cfo_positive", "Operating cash flow is positive", t(None if c.cfo is None else c.cfo > 0)),
        ("roa_improving", "Return on assets improved versus last year", t(gt(roa, roa_p))),
        ("accruals", "Operating cash flow exceeds net income (earnings are backed by cash)",
         t(None if c.cfo is None or c.net_income is None else c.cfo > c.net_income)),
        ("leverage_down", "Debt relative to assets fell", t(gt(lev_p, lev))),
        ("liquidity_up", "Current ratio improved", t(gt(cr, cr_p))),
        ("no_dilution", "No new shares were issued",
         t(None if c.shares is None or p is None or p.shares is None else c.shares <= p.shares * 1.005)),
        ("gross_margin_up", "Gross margin improved", t(gt(gm, gm_p))),
        ("asset_turnover_up", "Asset turnover improved", t(gt(at, at_p))),
    ]
    evaluated = [r for r in rows if r[2] != "na"]
    return {"score": sum(1 for r in evaluated if r[2] == "pass"), "evaluated": len(evaluated), "out_of": 9,
            "criteria": [{"id": a, "label": b, "result": r} for a, b, r in rows],
            "reading": ("not enough data" if len(evaluated) < 6 else "strong (7-9)" if sum(1 for r in evaluated if r[2] == "pass") >= 7
                        else "weak (0-3)" if sum(1 for r in evaluated if r[2] == "pass") <= 3 else "middling (4-6)")}


def altman_z(i: Inputs) -> dict[str, Any]:
    """Altman Z (original public-manufacturer formula). Not meaningful for banks/financials, flagged as not applicable.
    Z = 1.2*WC/TA + 1.4*RE/TA + 3.3*EBIT/TA + 0.6*MarketCap/TotalLiabilities + 1.0*Sales/TA."""
    c = i.cur
    ebit = c.ebit if c.ebit is not None else c.operating_income
    out: dict[str, Any] = {"z": None, "zone": None, "applicable": not is_financial(i.sector), "formula": "original (public manufacturers)"}
    if not out["applicable"]:
        out["note"] = "Altman Z is not meaningful for banks and financial companies."
        return out
    ta = c.total_assets
    parts = {"wc_ta": _div(None if c.current_assets is None or c.current_liabilities is None else c.current_assets - c.current_liabilities, ta),
             "re_ta": _div(c.retained_earnings, ta), "ebit_ta": _div(ebit, ta),
             "mve_tl": _div(i.market_cap, c.total_liabilities), "sales_ta": _div(c.revenue, ta)}
    if any(v is None for v in parts.values()):
        out["note"] = "missing inputs: " + ", ".join(k for k, v in parts.items() if v is None)
        return out
    z = 1.2 * parts["wc_ta"] + 1.4 * parts["re_ta"] + 3.3 * parts["ebit_ta"] + 0.6 * parts["mve_tl"] + 1.0 * parts["sales_ta"]  # type: ignore[operator]
    out.update(z=round(z, 3), zone="safe" if z > 2.99 else "grey" if z >= 1.81 else "distress", components=parts)
    return out


def graham_number(eps: float | None, bvps: float | None, price: float | None) -> dict[str, Any]:
    """Graham number = sqrt(22.5 * EPS * book value per share): a conservative 'fair price' ceiling from his 15x P/E and 1.5x P/B rules."""
    if eps is None or bvps is None or eps <= 0 or bvps <= 0:
        return {"value": None, "note": "needs positive EPS and book value per share"}
    g = math.sqrt(22.5 * eps * bvps)
    return {"value": round(g, 2), "price": price, "price_vs_graham": None if not price else round(price / g - 1, 4)}


def dcf(fcf0: float | None, shares: float | None, price: float | None, r: float = 0.12, g1: float = 0.08,
        g2: float = 0.05, years: int = 5) -> dict[str, Any]:
    """Two-stage discounted cash flow on free cash flow per the latest year.
    Stage 1: FCF grows at g1 for `years` years. Stage 2: Gordon growth at g2 forever. Everything is discounted at r.
    Simplification: treats free cash flow as flowing to shareholders (no net-debt adjustment). Highly assumption-sensitive."""
    if not (0 < years <= 30):
        raise ValueError("years must be between 1 and 30")
    if r <= g2:
        raise ValueError("discount rate must be greater than terminal growth")
    a = {"r": r, "g1": g1, "g2": g2, "years": years}
    if fcf0 is None or fcf0 <= 0 or not shares or shares <= 0:
        return {"assumptions": a, "intrinsic_per_share": None, "reason": "needs positive free cash flow and a share count", "fcf0": fcf0}
    proj, pv = [], 0.0
    f = fcf0
    for t in range(1, years + 1):
        f *= 1 + g1
        d = f / (1 + r) ** t
        pv += d
        proj.append({"year": t, "fcf": f, "pv": d})
    tv = f * (1 + g2) / (r - g2)
    pv_tv = tv / (1 + r) ** years
    equity = pv + pv_tv
    per_share = equity / shares
    return {"assumptions": a, "fcf0": fcf0, "projection": proj, "pv_stage1": pv, "terminal_value": tv, "pv_terminal": pv_tv,
            "terminal_share_pct": round(pv_tv / equity * 100, 1), "equity_value": equity, "intrinsic_per_share": per_share,
            "upside_pct": None if not price else round((per_share / price - 1) * 100, 1),
            "note": "Most of the value usually sits in the terminal term; small changes in r or g2 move the answer a lot."}


def dcf_sensitivity(fcf0: float | None, shares: float | None, price: float | None, r: float, g1: float, g2: float,
                    years: int) -> list[dict[str, Any]]:
    out = []
    for dr in (-0.02, 0.0, 0.02):
        for dg in (-0.03, 0.0, 0.03):
            rr, gg = r + dr, g1 + dg
            if rr > g2:
                res = dcf(fcf0, shares, price, rr, gg, g2, years)
                out.append({"r": round(rr, 4), "g1": round(gg, 4), "intrinsic": res["intrinsic_per_share"]})
    return out


def default_dcf_assumptions(i: Inputs) -> dict[str, float | int]:
    g = ratios(i)["revenue_growth"]
    g1 = 0.08 if g is None else min(0.20, max(0.02, g))
    return {"r": 0.12, "g1": round(g1, 3), "g2": 0.05, "years": 5}


METRIC_DIRECTION = {  # True = higher is better, False = lower is better (used only to word the percentile)
    "pe": False, "pb": False, "ev_ebitda": False, "roe": True, "roce": True, "debt_equity": False,
    "net_margin": True, "operating_margin": True, "revenue_growth": True, "earnings_growth": True, "dividend_yield": True,
}


def sector_percentiles(mine: dict[str, float | None], peers: list[dict[str, float | None]], min_peers: int = 3) -> dict[str, Any]:
    """Percentile rank (0-100) of each metric among same-sector peers' stored snapshots (including this stock).
    Needs at least `min_peers` OTHER companies with the metric, otherwise null (no fake precision)."""
    out: dict[str, Any] = {}
    for k in METRIC_DIRECTION:
        v = mine.get(k)
        others = [p[k] for p in peers if p.get(k) is not None]
        if v is None or len(others) < min_peers:
            out[k] = {"percentile": None, "peers": len(others)}
            continue
        below = sum(1 for o in others if o < v) + 0.5 * sum(1 for o in others if o == v)
        out[k] = {"percentile": round(100 * below / len(others), 1), "peers": len(others),
                  "higher_is_better": METRIC_DIRECTION[k]}
    return out
