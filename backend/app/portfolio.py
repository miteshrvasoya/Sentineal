"""Portfolio tracking for a beginner: positions, average cost, profit and loss, how the money grew, and a plain-English check-up.

Everything is derived from the buy/sell rows the user entered (average-cost method, the same way most brokers show it).
This is bookkeeping and observation only. It never tells anyone what to buy or sell.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

import numpy as np
import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.data.models import PortfolioTxn

EPS = 1e-9


class PortfolioError(ValueError):
    """A transaction that does not make sense (selling more than you own, a future date, ...)."""


@dataclass
class Pos:
    symbol: str
    qty: float = 0.0
    cost: float = 0.0              # money tied up in the shares still held (includes buying fees)
    realised: float = 0.0
    first_buy: str | None = None
    bought: float = 0.0            # total ever bought (rupees)
    sold: float = 0.0              # total ever received from sales (rupees, after fees)

    @property
    def avg_cost(self) -> float:
        return self.cost / self.qty if self.qty > EPS else 0.0


def _key(t: PortfolioTxn) -> tuple:
    return (t.date, 0 if t.side == "buy" else 1, t.id or 0)          # on the same day, buys count before sells


def replay(txns: list[PortfolioTxn]) -> dict[str, Pos]:
    """Apply transactions in date order. Raises PortfolioError if a sale exceeds the shares held at that moment."""
    pos: dict[str, Pos] = {}
    for t in sorted(txns, key=_key):
        p = pos.setdefault(t.symbol, Pos(t.symbol))
        if t.side == "buy":
            p.qty += t.qty
            p.cost += t.qty * t.price + t.fees
            p.bought += t.qty * t.price + t.fees
            p.first_buy = p.first_buy or t.date
        else:
            if t.qty > p.qty + 1e-6:
                raise PortfolioError(f"You cannot sell {t.qty:g} {t.symbol} on {t.date}: you only held {p.qty:g} then.")
            avg = p.avg_cost
            proceeds = t.qty * t.price - t.fees
            p.realised += proceeds - avg * t.qty
            p.sold += proceeds
            p.cost -= avg * t.qty
            p.qty -= t.qty
            if p.qty <= 1e-6:
                p.qty, p.cost = 0.0, 0.0
    return pos


def validate_new(existing: list[PortfolioTxn], new: list[PortfolioTxn]) -> None:
    today = datetime.now().date().isoformat()
    for t in new:
        if t.side not in ("buy", "sell"):
            raise PortfolioError("side must be buy or sell")
        if t.qty <= 0 or t.price <= 0 or t.fees < 0:
            raise PortfolioError("quantity and price must be above zero, and fees cannot be negative")
        try:
            date.fromisoformat(t.date)
        except ValueError:
            raise PortfolioError("date must look like 2025-03-31") from None
        if t.date > today:
            raise PortfolioError("the date is in the future")
    replay(existing + new)


def xirr(flows: list[tuple[date, float]]) -> float | None:
    """Annualised return of dated cash flows (negative = money in, positive = money out/value now). None if undefined."""
    if len(flows) < 2 or not any(v < 0 for _, v in flows) or not any(v > 0 for _, v in flows):
        return None
    t0 = min(d for d, _ in flows)
    ts = np.array([(d - t0).days / 365.0 for d, _ in flows])
    vs = np.array([v for _, v in flows])

    def f(r: float) -> float:
        return float(np.sum(vs / (1 + r) ** ts))
    lo, hi = -0.99, 10.0
    if f(lo) * f(hi) > 0:
        return None
    for _ in range(200):
        mid = (lo + hi) / 2
        if f(lo) * f(mid) <= 0:
            hi = mid
        else:
            lo = mid
    return (lo + hi) / 2


def _last_prices(db: Session, symbols: list[str]) -> dict[str, dict[str, Any]]:
    from app.data.analysis import close_series
    out: dict[str, dict[str, Any]] = {}
    for s in symbols:
        c = close_series(db, s, adjusted=False)
        if c is None or len(c) == 0:
            continue
        out[s] = {"price": float(c.iloc[-1]), "prev": float(c.iloc[-2]) if len(c) > 1 else float(c.iloc[-1]), "as_of": str(c.index[-1].date())}
    return out


def _sectors(symbols: list[str]) -> dict[str, str]:
    from app.search import universe
    u = {e.symbol: e.sector for e in universe()}
    return {s: (u.get(s) or "Other") for s in symbols}


def _names(symbols: list[str]) -> dict[str, str]:
    from app.search import universe
    u = {e.symbol: e.name for e in universe()}
    return {s: u.get(s, s) for s in symbols}


def summarize(db: Session) -> dict[str, Any]:
    txns = list(db.scalars(select(PortfolioTxn)))
    pos = replay(txns)
    open_syms = sorted(s for s, p in pos.items() if p.qty > EPS)
    prices = _last_prices(db, sorted(pos))
    sectors, names = _sectors(sorted(pos)), _names(sorted(pos))
    today = datetime.now().date()
    rows = []
    for s in open_syms:
        p, q = pos[s], prices.get(s)
        value = p.qty * q["price"] if q else None
        row: dict[str, Any] = {"symbol": s, "name": names[s], "sector": sectors[s], "qty": p.qty, "avg_cost": p.avg_cost, "invested": p.cost,
                               "price": q["price"] if q else None, "price_as_of": q["as_of"] if q else None, "value": value, "first_buy": p.first_buy,
                               "realised": p.realised}
        if q:
            row["pl"] = value - p.cost
            row["pl_pct"] = (value - p.cost) / p.cost if p.cost > EPS else None
            row["day_change"] = p.qty * (q["price"] - q["prev"])
            row["day_change_pct"] = q["price"] / q["prev"] - 1 if q["prev"] else None
            row["stale_days"] = (today - date.fromisoformat(q["as_of"])).days
        else:
            row["stale_days"] = None
        rows.append(row)
    valued = [r for r in rows if r["value"] is not None]
    value = sum(r["value"] for r in valued)
    invested = sum(r["invested"] for r in rows)
    invested_valued = sum(r["invested"] for r in valued)
    for r in rows:
        r["weight"] = (r["value"] / value) if r["value"] is not None and value > EPS else None
    realised = sum(p.realised for p in pos.values())
    day = sum(r.get("day_change", 0.0) for r in valued)
    flows = []
    for t in txns:
        d = date.fromisoformat(t.date)
        flows.append((d, -(t.qty * t.price + t.fees) if t.side == "buy" else (t.qty * t.price - t.fees)))
    span_days = (today - min((d for d, _ in flows), default=today)).days
    rate = xirr(flows + [(today, value)]) if value > EPS and span_days >= 90 else None
    by_sector: dict[str, float] = defaultdict(float)
    for r in valued:
        by_sector[r["sector"]] += r["value"]
    closed = [{"symbol": s, "name": names[s], "realised": p.realised, "bought": p.bought, "sold": p.sold} for s, p in sorted(pos.items()) if p.qty <= EPS and p.bought > 0]
    out = {
        "empty": not txns,
        "summary": {"value": value, "invested": invested, "pl": value - invested_valued, "pl_pct": (value - invested_valued) / invested_valued if invested_valued > EPS else None,
                    "realised": realised, "total_pl": value - invested_valued + realised, "day_change": day, "day_change_pct": day / (value - day) if value - day > EPS else None,
                    "annual_return": rate, "annual_return_note": None if rate is not None else ("Needs at least 3 months of history to be meaningful." if span_days < 90 else None),
                    "holdings": len(open_syms), "unpriced": [r["symbol"] for r in rows if r["value"] is None]},
        "positions": sorted(rows, key=lambda r: -(r["value"] or 0)),
        "allocation": {"by_sector": sorted(({"sector": k, "weight": v / value, "value": v} for k, v in by_sector.items()), key=lambda x: -x["weight"]) if value > EPS else []},
        "closed": closed,
    }
    out["checkup"] = checkup(db, out)
    return out


def checkup(db: Session, summ: dict[str, Any]) -> list[dict[str, Any]]:
    """Plain-English observations about the portfolio's risk shape. Observations, never instructions."""
    from app.agent.redflags import red_flags
    items: list[dict[str, Any]] = []
    rows = summ["positions"]

    def add(level: str, title: str, text: str, symbols: list[str] | None = None) -> None:
        items.append({"level": level, "title": title, "text": text, "symbols": symbols or []})
    if not rows:
        return items
    n = len(rows)
    if n < 5:
        add("info", f"You own {n} stock{'s' if n != 1 else ''}", "With only a few stocks, one company having a bad time can hurt your whole portfolio. Many investors spread across 10 or more companies in different industries; "
                                                                  "index funds do that automatically. Whether that suits you is your decision.")
    for r in rows:
        w = r.get("weight")
        if w and w > 0.4:
            add("high", f"{r['symbol']} is {w:.0%} of your portfolio", "One stock makes up a very large share. If it falls 30%, your whole portfolio falls roughly " + f"{w * 0.3:.0%}.", [r["symbol"]])
        elif w and w > 0.25:
            add("medium", f"{r['symbol']} is {w:.0%} of your portfolio", "A large share in one company. Worth knowing how much you would be hurt if it dropped sharply.", [r["symbol"]])
    for sec in summ["allocation"]["by_sector"]:
        if sec["sector"] not in ("Other", "") and sec["weight"] > 0.5 and n > 1:
            add("medium", f"{sec['weight']:.0%} of your money is in {sec['sector']}", "Companies in the same industry tend to rise and fall together, so this is less spread out than it looks.", [r["symbol"] for r in rows if r["sector"] == sec["sector"]])
    losers = [r for r in rows if r.get("pl_pct") is not None and r["pl_pct"] < -0.25]
    if losers:
        add("medium", f"{len(losers)} holding{'s are' if len(losers) > 1 else ' is'} down more than 25%", "Review why you bought: has the reason changed, or is it a temporary dip? " +
            "Selling only to avoid a loss, or holding only to avoid admitting one, are both common mistakes.", [r["symbol"] for r in losers])
    stale = [r for r in rows if r.get("stale_days") is not None and r["stale_days"] > 5]
    if stale:
        add("info", "Some prices are out of date", "Press Refresh prices. Until then the value shown for " + ", ".join(r["symbol"] for r in stale[:4]) + " is not current.", [r["symbol"] for r in stale])
    nop = [r["symbol"] for r in rows if r["value"] is None]
    if nop:
        add("info", "No price found for " + ", ".join(nop[:4]), "Check the symbol is right, then press Refresh prices.", nop)
    for r in rows[:15]:
        try:
            fl = [f for f in red_flags(db, r["symbol"])["flags"] if f["severity"] == "high"]
        except Exception:  # noqa: BLE001
            fl = []
        if fl:
            add("high", f"{r['symbol']} has {len(fl)} serious warning sign{'s' if len(fl) > 1 else ''}", fl[0]["message"], [r["symbol"]])
    if not any(i["level"] in ("high", "medium") for i in items):
        add("good", "No obvious concentration problems", "Nothing stands out on size of positions, sectors or warning signs. That does not mean it is safe: all stocks can fall together.")
    order = {"high": 0, "medium": 1, "info": 2, "good": 3}
    return sorted(items, key=lambda i: order[i["level"]])


def history(db: Session, max_points: int = 500) -> dict[str, Any]:
    """Daily value of the holdings vs the money put in, using stored prices."""
    from app.data.analysis import close_series
    txns = sorted(db.scalars(select(PortfolioTxn)), key=_key)
    if not txns:
        return {"points": []}
    start = pd.Timestamp(txns[0].date)
    syms = sorted({t.symbol for t in txns})
    closes = {}
    for s in syms:
        c = close_series(db, s, adjusted=False)
        if c is not None and len(c):
            closes[s] = c
    if not closes:
        return {"points": []}
    idx = sorted(set().union(*[set(c.index[c.index >= start]) for c in closes.values()]))
    if not idx:
        return {"points": []}
    idx = pd.DatetimeIndex(idx)
    qty = pd.DataFrame(0.0, index=idx, columns=syms)
    put_in = pd.Series(0.0, index=idx)
    for t in txns:
        d = pd.Timestamp(t.date)
        sign = 1 if t.side == "buy" else -1
        qty.loc[qty.index >= d, t.symbol] += sign * t.qty
        put_in.loc[put_in.index >= d] += sign * t.qty * t.price + (t.fees if t.side == "buy" else -t.fees)
    px = pd.DataFrame({s: closes[s].reindex(idx).ffill() for s in closes}).reindex(columns=syms)
    value = (qty * px).sum(axis=1)
    held = (qty > 1e-9).any(axis=1)
    pts = [{"date": str(d.date()), "value": round(float(value[d]), 2), "put_in": round(float(put_in[d]), 2)} for d in idx[held.to_numpy()]]
    if len(pts) > max_points:
        step = int(np.ceil(len(pts) / max_points))
        pts = pts[::step] + ([pts[-1]] if (len(pts) - 1) % step else [])
    return {"points": pts, "note": "Value uses the closing price of each day. Money put in is what you paid for buys minus what you received from sales."}
