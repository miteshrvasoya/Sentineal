"""Stock screener over stored data: a snapshot table (one row per stock), filters on it, relative strength, breadth, sectors.

A screen is a FILTER on today's numbers, not a forecast. Whether a screen has ever selected stocks that did better is a
separate question that the backtester and model lab exist to answer.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.data.models import Price, Symbol

MIN_BARS = 60
CACHE_TTL = 120.0
_cache: dict[str, tuple[float, list[dict]]] = {}


@dataclass(frozen=True)
class Field:
    key: str
    label: str
    group: str
    kind: str          # number | text | bool
    unit: str          # pct | ratio | price | score | x | none
    desc: str


FIELDS: list[Field] = [
    Field("sector", "Sector", "Basics", "text", "none", "Sector from the symbol list."),
    Field("price", "Price", "Basics", "number", "price", "Last stored close (adjusted)."),
    Field("ret_5d", "5-day return", "Momentum", "number", "pct", "Return over 5 trading days."),
    Field("ret_21d", "1-month return", "Momentum", "number", "pct", "Return over 21 trading days."),
    Field("ret_63d", "3-month return", "Momentum", "number", "pct", "Return over 63 trading days."),
    Field("ret_126d", "6-month return", "Momentum", "number", "pct", "Return over 126 trading days."),
    Field("ret_252d", "12-month return", "Momentum", "number", "pct", "Return over 252 trading days."),
    Field("rs_rank_63", "Relative strength rank (3m)", "Momentum", "number", "score", "Percentile (0-100) of the 3-month return within the stored universe. 90 = better than 90% of the stocks."),
    Field("rs_rank_126", "Relative strength rank (6m)", "Momentum", "number", "score", "Percentile (0-100) of the 6-month return within the stored universe."),
    Field("rsi", "RSI (14)", "Momentum", "number", "score", "Relative Strength Index. Below 30 is conventionally 'oversold', above 70 'overbought'."),
    Field("adx", "ADX", "Trend", "number", "score", "Trend strength regardless of direction. Above 25 is conventionally a trending market."),
    Field("close_vs_sma50", "Price vs 50-day average", "Trend", "number", "pct", "How far the price is above (+) or below (-) its 50-day average."),
    Field("close_vs_sma200", "Price vs 200-day average", "Trend", "number", "pct", "How far the price is above (+) or below (-) its 200-day average."),
    Field("above_sma50", "Above 50-day average", "Trend", "bool", "none", "Price is above its 50-day simple moving average."),
    Field("above_sma200", "Above 200-day average", "Trend", "bool", "none", "Price is above its 200-day simple moving average."),
    Field("pct_from_52w_high", "Distance from 52-week high", "Trend", "number", "pct", "0% = at the high; -20% = 20% below it."),
    Field("pct_from_52w_low", "Distance above 52-week low", "Trend", "number", "pct", "How far above the 52-week low."),
    Field("vol_21d_annual", "Volatility (21d, annualised)", "Risk", "number", "pct", "Annualised standard deviation of daily returns over 21 days."),
    Field("atr_pct", "ATR as % of price", "Risk", "number", "pct", "Average true range relative to price: typical daily swing."),
    Field("rvol", "Relative volume", "Volume", "number", "x", "Today's volume divided by its recent average. 2 = twice normal."),
    Field("composite", "Scorecard", "Signals", "number", "score", "The transparent rules-based scorecard, -100 to +100."),
    Field("sentiment", "News sentiment", "Signals", "number", "score", "Latest daily news sentiment score, if news is stored."),
    Field("pe", "P/E", "Fundamentals", "number", "x", "Price to earnings. Stored fundamentals only."),
    Field("pb", "P/B", "Fundamentals", "number", "x", "Price to book."),
    Field("roe", "Return on equity", "Fundamentals", "number", "pct", "Net income / equity."),
    Field("debt_equity", "Debt / equity", "Fundamentals", "number", "x", "Leverage."),
    Field("revenue_growth", "Revenue growth", "Fundamentals", "number", "pct", "Latest year-on-year revenue growth."),
    Field("earnings_growth", "Profit growth", "Fundamentals", "number", "pct", "Latest year-on-year growth in profit."),
    Field("net_margin", "Profit margin", "Fundamentals", "number", "pct", "Share of each rupee of sales that becomes profit."),
    Field("piotroski", "Financial health score (0-9)", "Fundamentals", "number", "score", "Piotroski F-score: 9 simple yes/no checks of a company's finances. 7 or more is strong."),
    Field("cagr_3y", "Yearly growth, 3 years", "Momentum", "number", "pct", "Average yearly price growth over the last 3 years (needs 3 years of stored prices)."),
    Field("dividend_yield", "Dividend yield", "Fundamentals", "number", "pct", "Annual dividend / price."),
]
FIELD_MAP = {f.key: f for f in FIELDS}
OPS = {">", ">=", "<", "<=", "==", "!=", "between", "in"}

PRESETS = [
    {"id": "oversold_uptrend", "title": "Oversold in an uptrend", "idea": "A short-term dip inside a long-term uptrend (a 'buy the dip' setup).",
     "conditions": [{"field": "rsi", "op": "<", "value": 40}, {"field": "above_sma200", "op": "==", "value": True}]},
    {"id": "near_high_volume", "title": "Near 52-week high on strong volume", "idea": "Breakout candidates: price pressing its high while volume is unusually high.",
     "conditions": [{"field": "pct_from_52w_high", "op": ">=", "value": -0.03}, {"field": "rvol", "op": ">", "value": 1.3}]},
    {"id": "rs_leaders", "title": "Relative-strength leaders", "idea": "Stocks outperforming most of the universe and holding above their 50-day average.",
     "conditions": [{"field": "rs_rank_126", "op": ">=", "value": 80}, {"field": "above_sma50", "op": "==", "value": True}]},
    {"id": "cheap_and_healthy", "title": "Cheap and financially healthy", "idea": "Moderate valuation with high returns on equity and low debt (needs stored fundamentals).",
     "conditions": [{"field": "pe", "op": "<", "value": 25}, {"field": "roe", "op": ">", "value": 0.15}, {"field": "debt_equity", "op": "<", "value": 1}]},
    {"id": "laggards_oversold", "title": "Laggards and oversold", "idea": "The weakest stocks that have also fallen hard: a value-trap hunting list, not a buy list.",
     "conditions": [{"field": "rs_rank_126", "op": "<=", "value": 20}, {"field": "rsi", "op": "<", "value": 35}]},
]


def _num(v: Any) -> float | None:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if np.isfinite(f) else None


def snapshot_row(db: Session, symbol: str, sector: str) -> dict[str, Any] | None:
    from app.data.analysis import fundamentals_view, scorecard_for, sentiment_latest
    from app.data.prices import apply_adjustment, load_prices
    from app.features.pipeline import compute_features, to_frame

    p = load_prices(db, symbol, "1d")
    if len(p) < MIN_BARS:
        return None
    df = to_frame(apply_adjustment(p)).iloc[-600:]
    f = compute_features(df)
    last = f.iloc[-1]
    c = df["close"]
    row: dict[str, Any] = {"symbol": symbol, "sector": sector or "", "price": _num(c.iloc[-1]), "bars": len(c), "as_of": str(df.index[-1].date())}
    for n in (5, 21, 63, 126, 252):
        row[f"ret_{n}d"] = _num(c.iloc[-1] / c.iloc[-1 - n] - 1) if len(c) > n else None
    for n in (50, 200):
        sma = c.rolling(n).mean().iloc[-1]
        ok = np.isfinite(sma) and sma > 0
        row[f"close_vs_sma{n}"] = _num(c.iloc[-1] / sma - 1) if ok else None
        row[f"above_sma{n}"] = bool(c.iloc[-1] > sma) if ok else None
    w = c.iloc[-252:]
    row["pct_from_52w_high"] = _num(c.iloc[-1] / w.max() - 1)
    row["pct_from_52w_low"] = _num(c.iloc[-1] / w.min() - 1)
    lr = np.log(c).diff().dropna()
    row["vol_21d_annual"] = _num(lr.iloc[-21:].std() * np.sqrt(252)) if len(lr) >= 21 else None
    for k, src in (("rsi", "rsi"), ("adx", "adx"), ("atr_pct", "atr_pct"), ("rvol", "rvol")):
        row[k] = _num(last.get(src))
    try:
        card = scorecard_for(db, symbol)
        row["composite"] = _num(card["composite"]) if card else None
    except Exception:  # noqa: BLE001
        row["composite"] = None
    try:
        s = sentiment_latest(db, symbol)
        row["sentiment"] = _num(s.get("recency_weighted") if isinstance(s, dict) else None)
    except Exception:  # noqa: BLE001
        row["sentiment"] = None
    fv = fundamentals_view(db, symbol)
    ratios = (fv or {}).get("ratios") or {}
    for k in ("pe", "pb", "roe", "debt_equity", "revenue_growth", "dividend_yield", "earnings_growth", "net_margin"):
        row[k] = _num(ratios.get(k))
    row["piotroski"] = _num(((fv or {}).get("piotroski") or {}).get("score")) if ((fv or {}).get("piotroski") or {}).get("evaluated", 0) >= 6 else None
    altman = (fv or {}).get("altman") or {}
    row["altman_zone"] = altman.get("zone") if altman.get("applicable") else None
    row["has_fundamentals"] = fv is not None
    from app.data.analysis import close_series
    full = close_series(db, symbol)
    if full is not None and len(full) >= 3 * 252 - 20:
        w3 = full.iloc[-3 * 252:]
        row["cagr_3y"] = _num((w3.iloc[-1] / w3.iloc[0]) ** (1 / 3) - 1)
        row["max_dd_3y"] = _num((w3 / w3.cummax() - 1).min())
    else:
        row["cagr_3y"] = row["max_dd_3y"] = None
    row["history_days"] = int(len(full)) if full is not None else 0
    return row


def add_ranks(rows: list[dict]) -> None:
    """Percentile ranks (0-100) of the 3- and 6-month returns within the universe."""
    for n in (63, 126):
        vals = [(r["symbol"], r.get(f"ret_{n}d")) for r in rows if r.get(f"ret_{n}d") is not None]
        s = pd.Series({k: v for k, v in vals})
        ranks = (s.rank(pct=True, method="average") * 100).round(1) if len(s) >= 2 else pd.Series(dtype=float)
        for r in rows:
            r[f"rs_rank_{n}"] = float(ranks[r["symbol"]]) if r["symbol"] in ranks.index else None


def universe(db: Session, symbols: list[str] | None = None, use_cache: bool = True) -> list[dict]:
    """Snapshot rows for every stored stock with enough history (excluding indices)."""
    syms = [s for s in db.scalars(select(Price.symbol).group_by(Price.symbol).having(func.count() >= MIN_BARS)) if " " not in s and not s.startswith("^")]
    stamp = str(db.scalar(select(func.max(Price.ts)).where(Price.interval == "1d")))
    key = f"{stamp}:{','.join(sorted(syms))}"
    hit = _cache.get(key)
    if use_cache and hit and time.time() - hit[0] < CACHE_TTL:
        rows = hit[1]
    else:
        sect = {s.symbol: s.sector for s in db.scalars(select(Symbol))}
        if not sect:
            from app.api.routes import symbol_table
            sect = {x.symbol: x.sector for x in symbol_table()}
        rows = [r for s in sorted(syms) if (r := snapshot_row(db, s, sect.get(s, ""))) is not None]
        add_ranks(rows)
        _cache.clear()
        _cache[key] = (time.time(), rows)
    return [r for r in rows if not symbols or r["symbol"] in symbols]


def validate(conditions: list[dict]) -> list[str]:
    errs = []
    for i, c in enumerate(conditions):
        f, op, v = c.get("field"), c.get("op"), c.get("value")
        if f not in FIELD_MAP:
            errs.append(f"condition {i + 1}: unknown field {f!r}")
            continue
        k = FIELD_MAP[f].kind
        if op not in OPS:
            errs.append(f"condition {i + 1}: unknown operator {op!r}")
        elif k == "bool" and (op not in ("==", "!=") or not isinstance(v, bool)):
            errs.append(f"condition {i + 1}: {f} is yes/no, use == true or == false")
        elif k == "text" and op not in ("==", "!=", "in"):
            errs.append(f"condition {i + 1}: {f} is text, use ==, != or in")
        elif k == "number" and op == "between" and not (isinstance(v, list) and len(v) == 2 and all(_num(x) is not None for x in v)):
            errs.append(f"condition {i + 1}: between needs two numbers")
        elif k == "number" and op not in ("between", "in") and _num(v) is None:
            errs.append(f"condition {i + 1}: {f} needs a number")
        elif op == "in" and k != "text":
            errs.append(f"condition {i + 1}: 'in' only works on text fields")
    return errs


def _match(row: dict, c: dict) -> bool:
    v = row.get(c["field"])
    if v is None:                       # missing data never matches: a screen should not select what it cannot measure
        return False
    op, t = c["op"], c["value"]
    if op == "in":
        return str(v).lower() in {str(x).lower() for x in t}
    if isinstance(v, str):
        return (v.lower() == str(t).lower()) == (op == "==")
    if isinstance(v, bool):
        return (v == t) == (op == "==")
    if op == "between":
        return float(t[0]) <= v <= float(t[1])
    t = float(t)
    return {">": v > t, ">=": v >= t, "<": v < t, "<=": v <= t, "==": v == t, "!=": v != t}[op]


def screen(rows: list[dict], conditions: list[dict], sort: str = "rs_rank_126", desc: bool = True, limit: int = 50) -> dict:
    errs = validate(conditions)
    if errs:
        raise ValueError("; ".join(errs))
    if sort not in FIELD_MAP:
        raise ValueError(f"unknown sort field {sort!r}")
    hits = [r for r in rows if all(_match(r, c) for c in conditions)]
    def key(r: dict) -> tuple:
        v = r.get(sort)
        if v is None:
            return (1, 0, "")
        if isinstance(v, bool | int | float):
            return (0, -float(v) if desc else float(v), "")
        return (0, 0, str(v))
    hits.sort(key=key)
    missing = {c["field"]: sum(r.get(c["field"]) is None for r in rows) for c in conditions}
    return {"universe": len(rows), "matches": len(hits), "rows": hits[:limit], "missing_data": {k: v for k, v in missing.items() if v}}


def breadth(rows: list[dict]) -> dict:
    """How broad is the market? Shares of the stored universe above their averages, advancing, at highs/lows."""
    n = len(rows)
    if n == 0:
        return {"n": 0}

    def share(fn) -> float | None:  # type: ignore[no-untyped-def]
        vals = [fn(r) for r in rows]
        vals = [v for v in vals if v is not None]
        return float(np.mean(vals)) if vals else None
    r1 = [r.get("ret_5d") for r in rows if r.get("ret_5d") is not None]
    return {"n": n, "above_sma50": share(lambda r: r["above_sma50"]), "above_sma200": share(lambda r: r["above_sma200"]),
            "positive_5d": share(lambda r: None if r.get("ret_5d") is None else r["ret_5d"] > 0),
            "positive_21d": share(lambda r: None if r.get("ret_21d") is None else r["ret_21d"] > 0),
            "near_52w_high": share(lambda r: None if r.get("pct_from_52w_high") is None else r["pct_from_52w_high"] >= -0.03),
            "near_52w_low": share(lambda r: None if r.get("pct_from_52w_low") is None else r["pct_from_52w_low"] <= 0.05),
            "median_5d_return": float(np.median(r1)) if r1 else None,
            "reading": _breadth_reading(share(lambda r: r["above_sma200"]), share(lambda r: r["above_sma50"]), n)}


def _breadth_reading(a200: float | None, a50: float | None, n: int) -> str:
    if n < 10:
        return f"Only {n} stocks are stored, so breadth is a rough guide at best."
    if a200 is None or a50 is None:
        return "Not enough history for the long-term averages."
    if a200 >= 0.7 and a50 >= 0.6:
        return "Broad strength: most stocks are above both averages."
    if a200 <= 0.3 and a50 <= 0.4:
        return "Broad weakness: most stocks are below both averages."
    if a50 > a200 + 0.2:
        return "Short-term improvement inside a weaker long-term picture."
    return "Mixed: no clear majority either way."


def sectors(rows: list[dict]) -> dict:
    """Return by sector over several windows, with ranks. Rotation = how the 1-month rank differs from the 6-month rank."""
    df = pd.DataFrame(rows)
    if df.empty or "sector" not in df:
        return {"rows": [], "note": "No data."}
    out = []
    for sec, g in df[df["sector"] != ""].groupby("sector"):
        row: dict[str, Any] = {"sector": sec, "n": int(len(g))}
        for n in (5, 21, 63, 126):
            row[f"ret_{n}d"] = _num(g[f"ret_{n}d"].median())
        row["rs_rank_126"] = _num(g["rs_rank_126"].mean())
        out.append(row)
    for n in (5, 21, 63, 126):
        vals = pd.Series({r["sector"]: r[f"ret_{n}d"] for r in out if r[f"ret_{n}d"] is not None})
        rk = vals.rank(ascending=False, method="min")
        for r in out:
            r[f"rank_{n}d"] = int(rk[r["sector"]]) if r["sector"] in rk.index else None
    for r in out:
        r["rotation"] = (r["rank_126d"] - r["rank_21d"]) if r.get("rank_126d") and r.get("rank_21d") else None   # + = climbing
    out.sort(key=lambda r: (r.get("rank_21d") is None, r.get("rank_21d")))
    return {"rows": out, "note": "Median stock return within each sector. Rotation > 0 means the sector ranks higher over the last month than over six months (money moving in); < 0 means it is fading. Sectors with one or two stored stocks are noisy."}
