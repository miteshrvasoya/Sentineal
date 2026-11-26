"""Stock ideas for a beginner: transparent rule-based scores for a SHORT-term (weeks to months) and a LONG-term (years) view.

Every point of a score comes from a named, plain-English check, and every check is shown. Missing data is skipped, never guessed,
and the result says how many checks it was based on. These are starting points for your own research, not recommendations:
the rules describe the past, and the past does not guarantee the future.
"""
from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session

STRONG, MIXED = 65, 45
MIN_CONFIDENCE_LONG = 0.55
HORIZONS = {"short": "weeks to a few months", "long": "several years"}


@dataclass
class Check:
    name: str
    max: float
    fn: Callable[[dict[str, Any]], tuple[float, str | None, str | None] | None]   # -> (points, good_text, watch_text) or None when data is missing


def _pct(x: float, d: int = 0) -> str:
    return f"{x * 100:.{d}f}%"


def _rupees(x: float) -> str:
    return f"₹{x:,.0f}" if x >= 100 else f"₹{x:,.2f}"


# ---------------- short term ----------------

def c_rs126(r):  # type: ignore[no-untyped-def]
    v = r.get("rs_rank_126")
    if v is None:
        return None
    pts = v / 100 * 30
    top = "Among the very strongest of the stocks tracked over the last 6 months" if v >= 97 else f"Stronger than {v:.0f}% of the stocks tracked over the last 6 months"
    return pts, (top if v >= 75 else None), (f"Weaker than most stocks tracked over 6 months (ahead of only {v:.0f}%)" if v <= 30 else None)


def c_rs63(r):  # type: ignore[no-untyped-def]
    v = r.get("rs_rank_63")
    if v is None:
        return None
    return v / 100 * 15, (("Still among the strongest over the last 3 months" if v >= 97 else f"Still strong over the last 3 months (ahead of {v:.0f}% of stocks)") if v >= 75 else None), (f"Lagging over the last 3 months (ahead of only {v:.0f}%)" if v <= 25 else None)


def c_trend(r):  # type: ignore[no-untyped-def]
    a50, a200 = r.get("above_sma50"), r.get("above_sma200")
    if a50 is None and a200 is None:
        return None
    pts = (8 if a50 else 0) + (8 if a200 else 0)
    good = "Trading above both its 50-day and 200-day average prices, which is an uptrend" if a50 and a200 else None
    bad = "Trading below its 200-day average price, which is a long-term downtrend" if a200 is False else ("Below its 50-day average: the recent trend is down" if a50 is False else None)
    return pts, good, bad


def c_rsi(r):  # type: ignore[no-untyped-def]
    v = r.get("rsi")
    if v is None:
        return None
    if 45 <= v <= 68:
        return 10, f"Not overheated: momentum gauge (RSI) is a healthy {v:.0f}", None
    if 68 < v <= 75:
        return 4, None, f"Getting stretched: RSI {v:.0f}. Stocks this far ahead of their average often pause"
    if v > 75:
        return -8, None, f"Already very stretched: RSI {v:.0f}. A pullback is more likely than usual"
    if v < 35:
        return 0, None, f"Falling hard: RSI {v:.0f} is in 'oversold' territory, which can mean opportunity or a falling knife"
    return 3, None, None


def c_high(r):  # type: ignore[no-untyped-def]
    v = r.get("pct_from_52w_high")
    if v is None:
        return None
    return (8, ("At its 1-year high" if v > -0.005 else f"Within {_pct(abs(v))} of its 1-year high"), None) if v >= -0.10 else ((0, None, f"Far below its 1-year high ({_pct(v)})") if v <= -0.30 else (2, None, None))


def c_volume(r):  # type: ignore[no-untyped-def]
    v = r.get("rvol")
    if v is None:
        return None
    return (4, f"Trading volume is {v:.1f}x its recent average, so more people are taking part", None) if v >= 1.0 else (0, None, None)


def c_calm(r):  # type: ignore[no-untyped-def]
    v = r.get("vol_21d_annual")
    if v is None:
        return None
    month = v / math.sqrt(12)
    if v < 0.25:
        return 6, f"Moves gently: typically within about ±{_pct(month)} in a month", None
    if v > 0.60:
        return -8, None, f"Swings a lot: typically ±{_pct(month)} in a month, so expect a bumpy ride"
    return 3, None, (f"Moderately volatile: about ±{_pct(month)} in a typical month" if v > 0.40 else None)


SHORT = [Check("6-month strength vs other stocks", 30, c_rs126), Check("3-month strength", 15, c_rs63), Check("Trend", 16, c_trend), Check("Not overheated", 10, c_rsi),
         Check("Near 1-year high", 8, c_high), Check("Volume", 4, c_volume), Check("Calm price moves", 6, c_calm)]


# ---------------- long term ----------------

def c_roe(r):  # type: ignore[no-untyped-def]
    v = r.get("roe")
    if v is None:
        return None
    if v >= 0.15:
        return 14, f"Earns a high return on shareholders' money ({_pct(v)} a year)", None
    if v >= 0.10:
        return 7, None, None
    return (0, None, f"Low return on shareholders' money ({_pct(v)})") if v < 0.05 else (2, None, None)


def c_margin(r):  # type: ignore[no-untyped-def]
    v = r.get("net_margin")
    if v is None:
        return None
    if v > 0.10:
        return 6, f"Keeps {_pct(v)} of its sales as profit", None
    return (-15, None, "Losing money: sales do not cover costs") if v < 0 else (2, None, None)


def c_debt(r):  # type: ignore[no-untyped-def]
    v = r.get("debt_equity")
    if v is None:
        return None
    if v < 0.5:
        return 10, f"Low debt (borrowings are {v:.1f}x its own money)", None
    if v < 1:
        return 6, None, None
    return (-10, None, f"Heavy debt: borrowings are {v:.1f}x its own money, which is risky if profits dip") if v > 2 else (2, None, f"Fairly high debt ({v:.1f}x its own money)")


def c_piotroski(r):  # type: ignore[no-untyped-def]
    v = r.get("piotroski")
    if v is None:
        return None
    if v >= 7:
        return 12, f"Strong financial health score ({v:.0f} of 9 simple checks passed)", None
    if v >= 5:
        return 6, None, None
    return (-10, None, f"Weak financial health score (only {v:.0f} of 9 checks passed)") if v <= 3 else (1, None, None)


def c_altman(r):  # type: ignore[no-untyped-def]
    z = r.get("altman_zone")
    if z is None:
        return None
    return (5, "Low risk of financial distress", None) if z == "safe" else ((-20, None, "In the 'distress zone' for bankruptcy risk") if z == "distress" else (0, None, None))


def c_revenue(r):  # type: ignore[no-untyped-def]
    v = r.get("revenue_growth")
    if v is None:
        return None
    if v > 0.10:
        return 8, f"Sales grew {_pct(v)} in the latest year", None
    if v > 0:
        return 3, None, None
    return (-8, None, f"Sales fell {_pct(abs(v))} in the latest year") if v < -0.05 else (0, None, None)


def c_earnings(r):  # type: ignore[no-untyped-def]
    v = r.get("earnings_growth")
    if v is None:
        return None
    return (6, f"Profit grew {_pct(v)} in the latest year", None) if v > 0.10 else ((-4, None, f"Profit fell {_pct(abs(v))} in the latest year") if v < -0.2 else (1, None, None))


def c_pe(r):  # type: ignore[no-untyped-def]
    v = r.get("pe")
    if v is None:
        return None
    if v <= 0:
        return -5, None, "No profit to measure the price against (P/E not meaningful)"
    if v <= 25:
        return 10, f"Reasonably priced: you pay ₹{v:.0f} for each ₹1 of yearly profit", None
    if v <= 40:
        return 5, None, None
    return (-8, None, f"Expensive: you pay ₹{v:.0f} for each ₹1 of yearly profit, so a lot of good news is already priced in") if v > 60 else (0, None, f"On the pricey side (₹{v:.0f} per ₹1 of yearly profit)")


def c_div(r):  # type: ignore[no-untyped-def]
    v = r.get("dividend_yield")
    if v is None:
        return None
    return (3, f"Pays a dividend ({_pct(v, 1)} of its price each year)", None) if v > 0.01 else (0, None, None)


def c_cagr(r):  # type: ignore[no-untyped-def]
    v = r.get("cagr_3y")
    if v is None:
        return None
    if v >= 0.12:
        return 8, f"Share price has grown about {_pct(v)} a year for 3 years", None
    if v >= 0.08:
        return 4, None, None
    return (-6, None, f"Share price has fallen about {_pct(abs(v))} a year for 3 years") if v < 0 else (0, None, None)


def c_dd(r):  # type: ignore[no-untyped-def]
    v = r.get("max_dd_3y")
    if v is None:
        return None
    return (4, f"Its worst fall in 3 years was a mild {_pct(abs(v))}", None) if v > -0.30 else ((-6, None, f"It fell {_pct(abs(v))} at its worst in the last 3 years: could you sit through that?") if v <= -0.45 else (0, None, None))


def c_steady(r):  # type: ignore[no-untyped-def]
    v = r.get("vol_21d_annual")
    if v is None:
        return None
    return (4, "Price moves are relatively steady", None) if v < 0.30 else (0, None, None)


LONG = [Check("Return on equity", 14, c_roe), Check("Profit margin", 6, c_margin), Check("Debt", 10, c_debt), Check("Financial health score", 12, c_piotroski),
        Check("Bankruptcy risk", 5, c_altman), Check("Sales growth", 8, c_revenue), Check("Profit growth", 6, c_earnings), Check("Price vs profit", 10, c_pe),
        Check("Dividend", 3, c_div), Check("3-year track record", 8, c_cagr), Check("Worst fall", 4, c_dd), Check("Steadiness", 4, c_steady)]


def evaluate(row: dict[str, Any], checks: list[Check]) -> dict[str, Any]:
    pts = mx = total = 0.0
    good: list[str] = []
    watch: list[str] = []
    used = 0
    for c in checks:
        total += c.max
        res = c.fn(row)
        if res is None:
            continue
        used += 1
        p, g, w = res
        pts += p
        mx += c.max
        if g:
            good.append(g)
        if w:
            watch.append(w)
    score = max(0.0, min(100.0, pts / mx * 100)) if mx > 0 else None
    return {"score": score, "good": good, "watch": watch, "checks_used": used, "checks_total": len(checks), "confidence": mx / total if total else 0.0}


def label(score: float | None) -> str:
    return "Not enough data" if score is None else "Looks strong" if score >= STRONG else "Mixed" if score >= MIXED else "Looks weak"


def risk_label(row: dict[str, Any]) -> str:
    v = row.get("vol_21d_annual")
    return "Unknown" if v is None else "Lower" if v < 0.22 else "Medium" if v < 0.35 else "Higher"


def numbers(row: dict[str, Any]) -> dict[str, Any]:
    return {k: row.get(k) for k in ("price", "ret_21d", "ret_126d", "ret_252d", "pe", "roe", "debt_equity", "dividend_yield", "rsi", "pct_from_52w_high", "cagr_3y")}


def _flag_penalty(db: Session, symbol: str) -> tuple[float, list[str]]:
    from app.agent.redflags import red_flags
    try:
        fl = red_flags(db, symbol)["flags"]
    except Exception:  # noqa: BLE001
        return 0.0, []
    pen = -sum(20 if f["severity"] == "high" else 6 if f["severity"] == "medium" else 0 for f in fl)
    return max(pen, -30.0), [f["message"] for f in fl if f["severity"] in ("high", "medium")][:3]


def assess_row(db: Session | None, row: dict[str, Any], horizon: str, with_flags: bool = True) -> dict[str, Any]:
    checks = SHORT if horizon == "short" else LONG
    e = evaluate(row, checks)
    watch, flags = list(e["watch"]), []
    if with_flags and db is not None:
        pen, flags = _flag_penalty(db, row["symbol"])
        if e["score"] is not None and pen:
            e["score"] = max(0.0, e["score"] + pen)
        watch = flags + watch
    change: list[str] = []
    if horizon == "short" and row.get("price") and row.get("close_vs_sma50") is not None:
        sma50 = row["price"] / (1 + row["close_vs_sma50"])
        change.append(f"The short-term trend turns negative if it closes below its 50-day average, about {_rupees(sma50)}.")
    if horizon == "long":
        change.append("Re-check after each quarterly result: is profit still growing and debt still low?")
        if not row.get("has_fundamentals"):
            watch.append("Company financials are not loaded yet, so this view uses price history only. Press Load more stocks to fetch them.")
    ranked = e["score"] is not None and (horizon == "short" or e["confidence"] >= MIN_CONFIDENCE_LONG)
    return {"symbol": row["symbol"], "sector": row.get("sector", ""), "horizon": horizon, "score": None if e["score"] is None else round(e["score"]), "label": label(e["score"]) if ranked or e["score"] is None else "Not enough data",
            "ranked": ranked, "confidence": round(e["confidence"], 2), "checks": f"{e['checks_used']} of {e['checks_total']} checks", "risk": risk_label(row), "why": e["good"][:8],
            "watch_out": watch[:8], "change_my_mind": change, "numbers": numbers(row)}


def eligible(row: dict[str, Any], horizon: str) -> bool:
    return row.get("bars", 0) >= (126 if horizon == "short" else 250)


def top_ideas(db: Session, rows: list[dict[str, Any]], horizon: str, limit: int = 8, risk: str = "any", sector: str | None = None) -> dict[str, Any]:
    if horizon not in HORIZONS:
        raise ValueError("horizon must be 'short' or 'long'")
    pool = [r for r in rows if eligible(r, horizon) and (not sector or r.get("sector", "").lower() == sector.lower())]
    if risk in ("low", "medium"):
        allowed = {"low": {"Lower"}, "medium": {"Lower", "Medium"}}[risk]
        pool = [r for r in pool if risk_label(r) in allowed]
    pre = sorted(((evaluate(r, SHORT if horizon == "short" else LONG), r) for r in pool), key=lambda x: -(x[0]["score"] or -1))
    cand = [assess_row(db, r, horizon) for _, r in pre[: max(limit * 3, 12)]]
    ranked = sorted((c for c in cand if c["ranked"]), key=lambda c: -(c["score"] or 0))[:limit]
    return {"horizon": horizon, "horizon_text": HORIZONS[horizon], "ideas": ranked, "considered": len(pool), "universe": len(rows),
            "unranked": len([c for c in cand if not c["ranked"]]), "disclaimer": DISCLAIMER}


DISCLAIMER = ("These are starting points for your own research, not recommendations. The rules look at the past, and the past does not guarantee the future. "
              "Never invest money you cannot afford to lose, and avoid putting everything into one idea.")
