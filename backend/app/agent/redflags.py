"""Deterministic red-flag detection per stock from stored data. No LLM: every flag states the rule and the numbers behind it.

A flag is a prompt to look closer, not a verdict. Each carries a severity (high/medium/low) and the facts it was built from.
"""
from __future__ import annotations

import time
from typing import Any

import numpy as np
from sqlalchemy.orm import Session

SEV = {"high": 3, "medium": 2, "low": 1}


def _flag(fid: str, sev: str, message: str, **evidence: Any) -> dict[str, Any]:
    return {"id": fid, "severity": sev, "message": message, "evidence": {k: (round(v, 4) if isinstance(v, float) else v) for k, v in evidence.items()}}


def price_flags(close, volume=None) -> list[dict[str, Any]]:  # type: ignore[no-untyped-def]
    out: list[dict[str, Any]] = []
    c = close.dropna()
    if len(c) < 60:
        return out
    r = c.pct_change().dropna()
    big = r.iloc[-5:]
    if (big.abs() > 0.08).any():
        d = big.abs().idxmax()
        out.append(_flag("big_recent_move", "medium", f"A single-day move of {big[d]:+.1%} in the last 5 sessions ({d.date()}).", day=str(d.date()), move=float(big[d])))
    dd = c / c.cummax() - 1
    if dd.iloc[-1] <= -0.3:
        out.append(_flag("deep_drawdown", "high", f"Trading {dd.iloc[-1]:.0%} below its high.", drawdown=float(dd.iloc[-1])))
    elif dd.iloc[-1] <= -0.2:
        out.append(_flag("drawdown", "medium", f"Trading {dd.iloc[-1]:.0%} below its high.", drawdown=float(dd.iloc[-1])))
    if len(c) >= 200:
        sma200 = c.rolling(200).mean().iloc[-1]
        if c.iloc[-1] < sma200 * 0.9:
            out.append(_flag("below_200dma", "low", f"Price is {c.iloc[-1] / sma200 - 1:.0%} below its 200-day average (long-term downtrend).", vs_sma200=float(c.iloc[-1] / sma200 - 1)))
    v21 = float(r.iloc[-21:].std() * np.sqrt(252))
    v252 = float(r.iloc[-252:].std() * np.sqrt(252)) if len(r) >= 120 else None
    if v252 and v21 > 1.8 * v252:
        out.append(_flag("volatility_spike", "medium", f"Recent volatility ({v21:.0%}) is {v21 / v252:.1f}x its one-year level ({v252:.0%}).", vol_21d=v21, vol_1y=v252))
    if volume is not None and len(volume) >= 60:
        base = float(volume.iloc[-60:-5].mean())
        if base > 0 and float(volume.iloc[-5:].mean()) < 0.3 * base:
            out.append(_flag("volume_dried_up", "low", "Trading volume over the last 5 sessions is under 30% of its 3-month average (illiquidity risk).", ratio=float(volume.iloc[-5:].mean() / base)))
    return out


def fundamental_flags(fv: dict[str, Any] | None) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    if not fv:
        return out
    ra = fv.get("ratios") or {}
    if (d := ra.get("debt_equity")) is not None and d > 2:
        out.append(_flag("high_leverage", "high" if d > 3 else "medium", f"Debt is {d:.1f}x equity.", debt_equity=float(d)))
    if (m := ra.get("net_margin")) is not None and m < 0:
        out.append(_flag("loss_making", "high", f"Net margin is negative ({m:.1%}): the company is losing money.", net_margin=float(m)))
    if (g := ra.get("earnings_growth")) is not None and g < -0.3:
        out.append(_flag("earnings_falling", "medium", f"Earnings fell {abs(g):.0%} year on year.", earnings_growth=float(g)))
    if (rg := ra.get("revenue_growth")) is not None and rg < -0.1:
        out.append(_flag("revenue_falling", "medium", f"Revenue fell {abs(rg):.0%} year on year.", revenue_growth=float(rg)))
    if (cf := ra.get("fcf_margin")) is not None and cf < -0.05:
        out.append(_flag("negative_free_cash_flow", "medium", f"Free cash flow margin is {cf:.1%}.", fcf_margin=float(cf)))
    p = fv.get("piotroski") or {}
    if p.get("evaluated", 0) >= 6 and p.get("score", 9) <= 3:
        out.append(_flag("weak_piotroski", "medium", f"Piotroski F-score {p['score']} of {p['out_of']}: weak financial health on most tests.", piotroski=p["score"]))
    a = fv.get("altman") or {}
    if a.get("applicable") and a.get("zone") == "distress":
        out.append(_flag("altman_distress", "high", f"Altman Z-score {a.get('z')} is in the distress zone.", altman_z=a.get("z")))
    if (sd := fv.get("stale_days")) is not None and sd > 120:
        out.append(_flag("stale_fundamentals", "low", f"Fundamentals are {sd:.0f} days old; ratios may not reflect the latest results.", stale_days=float(sd)))
    return out


def news_flags(db: Session, symbol: str, days: int = 14) -> list[dict[str, Any]]:
    from sqlalchemy import select

    from app.data.models import Article, ArticleEnrichment, ArticleTicker
    out: list[dict[str, Any]] = []
    since = int(time.time()) - days * 86400
    q = (select(Article, ArticleEnrichment).join(ArticleTicker, ArticleTicker.article_id == Article.id)
         .join(ArticleEnrichment, ArticleEnrichment.article_id == Article.id)
         .where(ArticleTicker.symbol == symbol, Article.published >= since))
    seen: set[str] = set()
    for a, e in db.execute(q):
        key = a.title.strip().lower()
        if key in seen:
            continue
        seen.add(key)
        if e.materiality == "high" and e.direction == "negative" and e.event_type in ("litigation", "regulatory", "management_change", "guidance", "earnings"):
            out.append(_flag(f"news_{e.event_type}", "medium", f"High-materiality negative {e.event_type.replace('_', ' ')} news: {a.title[:110]}", article=a.id, source=a.source))
    return out[:4]


def stale_data_flag(close) -> list[dict[str, Any]]:  # type: ignore[no-untyped-def]
    from app.data import calendar as cal
    last = close.dropna().index[-1].date()
    expected = cal.last_completed_session()
    gap = len(cal.trading_days(last, expected)) - 1
    if gap >= 3:
        return [_flag("stale_prices", "low", f"Stored prices end {last}, {gap} trading days before the latest session ({expected}). Data may be outdated.", last_bar=str(last), sessions_behind=gap)]
    return []


def red_flags(db: Session, symbol: str) -> dict[str, Any]:
    from app.data.analysis import close_series, fundamentals_view
    from app.data.prices import apply_adjustment, load_prices
    from app.features.pipeline import to_frame
    p = load_prices(db, symbol, "1d")
    flags: list[dict[str, Any]] = []
    if not p.empty:
        df = to_frame(apply_adjustment(p))
        flags += price_flags(df["close"], df["volume"])
        c = close_series(db, symbol)
        if c is not None:
            flags += stale_data_flag(c)
    flags += fundamental_flags(fundamentals_view(db, symbol))
    flags += news_flags(db, symbol)
    flags.sort(key=lambda f: -SEV[f["severity"]])
    has_fund = fundamentals_view(db, symbol) is not None
    checked = (["price"] if not p.empty else []) + (["fundamentals"] if has_fund else [])
    if checked:
        checked.append("news")
    return {"symbol": symbol, "flags": flags, "count": len(flags), "checked": checked,
            "note": "Flags are rule-based prompts to look closer, not verdicts. Missing data produces no flag, so no flags does not mean no problems."}
