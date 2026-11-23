from __future__ import annotations

import csv
import time
from datetime import UTC, datetime
from functools import lru_cache

import pandas as pd
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.schemas import Bar, PricesResponse, QuoteResponse, SymbolOut, WatchlistAdd
from app.config import ROOT, get_settings
from app.data import calendar as cal
from app.data.db import get_session
from app.data.ingest import backfill_many
from app.data.models import ProviderHealth, WatchlistItem
from app.data.prices import apply_adjustment, ensure_prices, load_prices
from app.data.quality import quality_report
from app.deps import get_router
from app.providers.base import INTERVALS, ProviderError, ProviderRouter

router = APIRouter()
MAX_BARS = 5000


@lru_cache
def symbol_table() -> list[SymbolOut]:
    with open(ROOT / "data" / "symbols.csv", newline="") as f:
        return [SymbolOut(**r) for r in csv.DictReader(f)]


def _known(symbol: str) -> str:
    return symbol.upper().strip()


@router.get("/health")
def health() -> dict:
    return {"status": "ok", "market": cal.market_status()}


@router.get("/providers/health")
def providers_health(db: Session = Depends(get_session), r: ProviderRouter = Depends(get_router)) -> list[dict]:
    rows = {h.name: h for h in db.scalars(select(ProviderHealth))}
    out = []
    for p in r.providers:
        h = rows.get(p.name)
        out.append({
            "name": p.name, "configured": p.is_configured(),
            "rate_limit": f"{p.rate_limit[0]}/{int(p.rate_limit[1])}s",
            "last_success": h.last_success if h else None,
            "last_error": h.last_error if h else None,
            "last_error_msg": h.last_error_msg if h else "",
            "calls_today": h.calls_today if h else 0,
        })
    return out


@router.get("/symbols/search", response_model=list[SymbolOut])
def search_symbols(q: str = Query("", max_length=40), limit: int = 10) -> list[SymbolOut]:
    ql = q.lower().strip()
    if not ql:
        return symbol_table()[:limit]
    scored = []
    for s in symbol_table():
        sym, name = s.symbol.lower(), s.name.lower()
        if sym.startswith(ql):
            scored.append((0, s))
        elif ql in sym or ql in name:
            scored.append((1, s))
    scored.sort(key=lambda x: (x[0], x[1].symbol))
    return [s for _, s in scored[:limit]]


@router.get("/watchlist", response_model=list[str])
def get_watchlist(db: Session = Depends(get_session)) -> list[str]:
    items = db.scalars(select(WatchlistItem).order_by(WatchlistItem.added_at, WatchlistItem.symbol)).all()
    if not items:
        for i, s in enumerate(get_settings().watchlist):
            db.add(WatchlistItem(symbol=s, added_at=i))
        db.commit()
        items = db.scalars(select(WatchlistItem).order_by(WatchlistItem.added_at)).all()
    return [i.symbol for i in items]


@router.post("/watchlist", response_model=list[str], status_code=201)
def add_watchlist(body: WatchlistAdd, db: Session = Depends(get_session)) -> list[str]:
    get_watchlist(db)
    sym = _known(body.symbol)
    if not db.get(WatchlistItem, sym):
        db.add(WatchlistItem(symbol=sym, added_at=int(time.time())))
        db.commit()
    return get_watchlist(db)


@router.delete("/watchlist/{symbol}", response_model=list[str])
def remove_watchlist(symbol: str, db: Session = Depends(get_session)) -> list[str]:
    get_watchlist(db)
    item = db.get(WatchlistItem, _known(symbol))
    if item:
        db.delete(item)
        db.commit()
    return get_watchlist(db)


def _downsample(df: pd.DataFrame, max_bars: int) -> pd.DataFrame:
    """Keep the most recent `max_bars` bars (server-side cap for huge ranges)."""
    return df.iloc[-max_bars:] if len(df) > max_bars else df


@router.get("/prices/{symbol}", response_model=PricesResponse)
async def get_prices(
    symbol: str,
    interval: str = "1d",
    from_: str | None = Query(None, alias="from", description="ISO date"),
    to: str | None = Query(None, description="ISO date"),
    adjusted: bool = True,
    limit: int = Query(MAX_BARS, ge=1, le=MAX_BARS),
    refresh: bool = False,
    db: Session = Depends(get_session),
    r: ProviderRouter = Depends(get_router),
) -> PricesResponse:
    if interval not in INTERVALS:
        raise HTTPException(422, f"interval must be one of {list(INTERVALS)}")
    sym = _known(symbol)
    try:
        start = pd.Timestamp(from_, tz="UTC") if from_ else None
        end = pd.Timestamp(to, tz="UTC") if to else None
    except ValueError as e:
        raise HTTPException(422, f"bad date: {e}") from e

    warnings: list[str] = []
    source: str | None = None
    try:
        res = await ensure_prices(db, r, sym, interval, start, end,
                                  ttl=get_settings().price_cache_ttl_seconds, force=refresh)
        source = res.source if res else None
    except ProviderError as e:
        warnings.append(f"Provider refresh failed, serving cached data if any: {e}")

    df = load_prices(db, sym, interval,
                     int(start.timestamp()) if start is not None else None,
                     int(end.timestamp()) + 86400 if end is not None else None)
    if df.empty:
        raise HTTPException(502 if warnings else 404,
                            detail=warnings[0] if warnings else f"no data for {sym}")
    source = source or str(df["source"].iloc[-1])
    if adjusted:
        df = apply_adjustment(df)
    n_before = len(df)
    df = _downsample(df, limit)
    if not cal.holidays_known(datetime.now(UTC).year):
        warnings.append("NSE holiday table missing for current year; calendar uses weekdays only.")
    return PricesResponse(
        symbol=sym, interval=interval, adjusted=adjusted, source=source, count=len(df),
        downsampled=len(df) < n_before, warnings=warnings,
        bars=[Bar(t=int(t), o=row.open, h=row.high, l=row.low, c=row.close, v=row.volume)
              for t, row in zip(df.index, df.itertuples(), strict=True)],
    )


@router.get("/quote/{symbol}", response_model=QuoteResponse)
async def get_quote(symbol: str, r: ProviderRouter = Depends(get_router)) -> QuoteResponse:
    sym = _known(symbol)
    try:
        q, src = await r.fetch_quote(sym)
    except ProviderError as e:
        raise HTTPException(502, detail=f"quote unavailable: {e}") from e
    return QuoteResponse(symbol=sym, source=src, **q)


@router.get("/data-quality/{symbol}")
def data_quality(symbol: str, interval: str = "1d", db: Session = Depends(get_session)) -> dict:
    if interval not in INTERVALS:
        raise HTTPException(422, f"interval must be one of {list(INTERVALS)}")
    return {"symbol": _known(symbol), **quality_report(load_prices(db, _known(symbol), interval), interval)}


@router.post("/ingest/backfill")
async def ingest_backfill(symbols: list[str] | None = None, interval: str = "1d",
                          db: Session = Depends(get_session), r: ProviderRouter = Depends(get_router)) -> list[dict]:
    """Incremental backfill (default: the watchlist). Stores everything fetched."""
    if interval not in INTERVALS:
        raise HTTPException(422, f"interval must be one of {list(INTERVALS)}")
    syms = [_known(s) for s in symbols] if symbols else get_watchlist(db)
    return await backfill_many(db, r, syms, interval)
