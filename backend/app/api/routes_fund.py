"""Fundamentals, risk, scorecard and watchlist-summary endpoints."""
from __future__ import annotations

import json
import math
import time
from functools import lru_cache
from typing import Any

import pandas as pd
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.api.routes import _known, get_watchlist
from app.data.analysis import close_series, fundamentals_view, scorecard_for
from app.data.db import get_session
from app.data.models import FundamentalsSnapshot
from app.features import fundamentals as fd
from app.features import risk as rk
from app.providers.base import FundamentalsProvider, ProviderError

router = APIRouter()


@lru_cache
def get_fund_provider() -> FundamentalsProvider:
    from app.providers.yahoo_fundamentals import YahooFundamentalsProvider
    return YahooFundamentalsProvider()


def clean(v: Any) -> Any:
    if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
        return None
    if isinstance(v, dict):
        return {k: clean(x) for k, x in v.items()}
    if isinstance(v, list | tuple):
        return [clean(x) for x in v]
    return v


@router.post("/fundamentals/{symbol}/refresh")
async def refresh_fundamentals(symbol: str, db: Session = Depends(get_session),
                               prov: FundamentalsProvider = Depends(get_fund_provider)) -> dict:
    sym = _known(symbol)
    try:
        raw = await prov.fetch(sym)
    except ProviderError as e:
        raise HTTPException(502, f"fundamentals unavailable: {e}") from e
    inp = fd.extract_inputs(sym, raw["info"], raw["income"], raw["balance"], raw["cashflow"], int(time.time()))
    db.merge(FundamentalsSnapshot(symbol=sym, sector=inp.sector, fetched_at=inp.fetched_at, payload=json.dumps(inp.to_dict())))
    db.commit()
    have = {k: v for k, v in inp.cur.__dict__.items() if v is not None}
    return {"symbol": sym, "sector": inp.sector, "fields_found": len(have), "fields_total": len(inp.cur.__dict__),
            "has_prior_year": inp.prev is not None, "price": inp.price}


@router.get("/fundamentals/{symbol}")
def get_fundamentals(symbol: str, r: float | None = Query(None, gt=0, lt=1), g1: float | None = Query(None, gt=-0.5, lt=1),
                     g2: float | None = Query(None, gt=-0.1, lt=0.15), years: int | None = Query(None, ge=1, le=30),
                     db: Session = Depends(get_session)) -> dict:
    """Ratios, scores and a DCF whose assumptions you can override (r, g1, g2, years)."""
    sym = _known(symbol)
    try:
        v = fundamentals_view(db, sym, r, g1, g2, years)
    except ValueError as e:
        raise HTTPException(422, str(e)) from e
    if v is None:
        raise HTTPException(404, f"No fundamentals stored for {sym}. POST /fundamentals/{sym}/refresh first.")
    return clean(v)


def _series(s: pd.Series, n: int = 500) -> list[float | None]:
    return [None if pd.isna(x) else round(float(x), 5) for x in s.iloc[-n:]]


@router.get("/risk/correlation")
def correlation(symbols: str | None = None, days: int = Query(252, ge=30, le=1500), db: Session = Depends(get_session)) -> dict:
    syms = [_known(s) for s in symbols.split(",")] if symbols else get_watchlist(db)
    closes = {s: c for s in syms if (c := close_series(db, s)) is not None}
    if len(closes) < 2:
        raise HTTPException(404, "Need stored prices for at least two symbols.")
    return clean(rk.correlation_matrix(closes, days))


@router.get("/risk/{symbol}")
def get_risk(symbol: str, rf: float = Query(0.07, ge=0, le=0.5), benchmark: str = "NIFTY 50", window: int = Query(63, ge=20, le=252),
             days: int | None = Query(None, ge=60, le=5000), db: Session = Depends(get_session)) -> dict:
    sym = _known(symbol)
    c = close_series(db, sym)
    if c is None or len(c) < 60:
        raise HTTPException(404, f"Need at least 60 stored daily bars for {sym}.")
    b = close_series(db, _known(benchmark)) if _known(benchmark) != sym else None
    if days:
        c = c.iloc[-days:]
    notes = []
    if b is None:
        notes.append(f"Benchmark {benchmark} has no stored prices (run make seed), so beta and correlation are unavailable.")
    else:
        b = b.reindex(c.index).ffill()
    roll = rk.rolling(c, b, window, rf)
    equity = c / c.iloc[0] * 100
    return clean({
        "symbol": sym, "benchmark": benchmark if b is not None else None, "window": window, "notes": notes,
        "summary": rk.summary(c, b, rf, window),
        "series": {"dates": [str(d.date()) for d in c.index[-500:]], "equity": _series(equity), "drawdown": _series(roll["drawdown"]),
                   "volatility": _series(roll["volatility"]), "sharpe": _series(roll["sharpe"]),
                   "beta": _series(roll["beta"]) if "beta" in roll else None,
                   "correlation": _series(roll["correlation"]) if "correlation" in roll else None},
        "disclaimer": "Descriptive statistics of the past, not forecasts. Kelly is display-only.",
    })


@router.get("/scorecard/{symbol}")
def get_scorecard(symbol: str, db: Session = Depends(get_session)) -> dict:
    sym = _known(symbol)
    s = scorecard_for(db, sym)
    if s is None:
        raise HTTPException(404, f"Need at least 60 stored daily bars for {sym}.")
    return clean(s)


_summary_cache: dict[str, tuple[float, Any]] = {}


@router.get("/watchlist/summary")
def watchlist_summary(db: Session = Depends(get_session)) -> list[dict]:
    """Per watchlist symbol: last close, day change, 30-bar sparkline and the scorecard badge (from stored data only)."""
    out = []
    for sym in get_watchlist(db):
        hit = _summary_cache.get(sym)
        if hit and time.time() - hit[0] < 60:
            out.append(hit[1])
            continue
        c = close_series(db, sym, adjusted=False)
        row: dict[str, Any] = {"symbol": sym, "last": None, "change_pct": None, "spark": [], "score": None, "label": None}
        if c is not None and len(c) >= 2:
            row.update(last=round(float(c.iloc[-1]), 2), change_pct=round(float(c.iloc[-1] / c.iloc[-2] - 1) * 100, 2),
                       spark=[round(float(x), 2) for x in c.iloc[-30:]])
            try:
                card = scorecard_for(db, sym)
            except Exception:  # noqa: BLE001  never let one symbol break the sidebar
                card = None
            if card:
                row.update(score=card["composite"], label=card["label"])
        _summary_cache[sym] = (time.time(), row)
        out.append(row)
    return out
