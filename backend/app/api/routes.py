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
from app.features.patterns import detect as pattern_detect
from app.features.patterns import edge_stats, recent_signals
from app.features.pipeline import FEATURE_VERSION, SETS, compute_features, feature_hash, to_frame
from app.features.structure import analyze as structure_analyze
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
async def search_symbols(q: str = Query("", max_length=60), limit: int = Query(10, ge=1, le=30), live: bool = True) -> list[SymbolOut]:
    """Search every NSE company by name, short name, symbol or typo; falls back to Yahoo Finance for BSE and new listings."""
    from app.search import search
    return [SymbolOut(**r) for r in await search(q, limit, live)]


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


@router.get("/indicators/{symbol}")
def indicators(
    symbol: str, set: str = "trend,momentum,volatility,volume", interval: str = "1d",
    adjusted: bool = True, limit: int = Query(500, ge=1, le=MAX_BARS),
    params: str | None = Query(None, description='JSON, e.g. {"momentum":{"rsi_period":21}}'),
    db: Session = Depends(get_session),
) -> dict:
    """Indicator series aligned to bar times `t` (last `limit` bars) plus latest values."""
    import json
    if interval not in INTERVALS:
        raise HTTPException(422, f"interval must be one of {list(INTERVALS)}")
    names = [x.strip() for x in set.split(",") if x.strip()]
    bad = [n for n in names if n not in SETS]
    if bad:
        raise HTTPException(422, f"unknown set(s) {bad}; available {list(SETS)}")
    try:
        p = json.loads(params) if params else {}
    except ValueError as e:
        raise HTTPException(422, f"params is not valid JSON: {e}") from e
    sym = _known(symbol)
    prices = load_prices(db, sym, interval)
    if prices.empty:
        raise HTTPException(404, f"no stored prices for {sym}; fetch /prices/{sym} first")
    if adjusted:
        prices = apply_adjustment(prices)
    try:
        feats = compute_features(to_frame(prices), names, p)
    except TypeError as e:
        raise HTTPException(422, f"bad params: {e}") from e
    feats = feats.iloc[-limit:]
    cols = {c: [None if v != v else round(float(v), 6) for v in feats[c]] for c in feats.columns}
    last = feats.iloc[-1]
    return {"symbol": sym, "interval": interval, "version": FEATURE_VERSION,
            "feature_hash": feature_hash(list(feats.columns), names),
            "t": [int(x.timestamp()) for x in feats.index],
            "latest": {c: (None if last[c] != last[c] else round(float(last[c]), 6)) for c in feats.columns},
            "series": cols}


def _frame(db: Session, sym: str, interval: str, adjusted: bool, limit: int) -> pd.DataFrame:
    if interval not in INTERVALS:
        raise HTTPException(422, f"interval must be one of {list(INTERVALS)}")
    prices = load_prices(db, sym, interval)
    if prices.empty:
        raise HTTPException(404, f"no stored prices for {sym}; fetch /prices/{sym} first")
    if adjusted:
        prices = apply_adjustment(prices)
    return to_frame(prices).iloc[-limit:]


@router.get("/structure/{symbol}")
def structure(symbol: str, interval: str = "1d", k: int = Query(3, ge=1, le=10),
              limit: int = Query(750, ge=60, le=MAX_BARS), profile_window: int = Query(120, ge=20, le=1000),
              adjusted: bool = True, db: Session = Depends(get_session)) -> dict:
    """Swings, BOS/CHoCH, sweeps, FVG, order blocks, S/R zones, Fibonacci, pivots, volume profile.
    Swings are confirmed k bars late; see `confirmed_t`. Heuristics, not predictions."""
    sym = _known(symbol)
    df = _frame(db, sym, interval, adjusted, limit)
    if len(df) < 2 * k + 10:
        raise HTTPException(422, f"need at least {2 * k + 10} bars, have {len(df)}")
    return {"symbol": sym, "interval": interval, "bars": len(df), **structure_analyze(df, k, profile_window)}


@router.get("/patterns/{symbol}")
def patterns(symbol: str, interval: str = "1d", limit: int = Query(5000, ge=60, le=MAX_BARS),
             recent_bars: int = Query(30, ge=1, le=500), adjusted: bool = True,
             db: Session = Depends(get_session)) -> dict:
    """Candlestick patterns: recent detections plus per-pattern historical edge on this stock."""
    sym = _known(symbol)
    df = _frame(db, sym, interval, adjusted, limit)
    flags = pattern_detect(df)
    return {"symbol": sym, "interval": interval, "bars": len(df),
            "recent": recent_signals(df, flags, recent_bars), "stats": edge_stats(df, flags),
            "notes": ["Hit rate is compared with this stock's own base rate (binomial test).",
                      "p_value_bonferroni corrects for testing all patterns and horizons at once.",
                      "Fewer than 30 occurrences is reported as insufficient sample."]}
