"""Incremental backfill: fetch only what is missing and store everything fetched."""
from __future__ import annotations

import logging
from datetime import UTC, datetime

import pandas as pd
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.data.models import Price
from app.data.prices import DEFAULT_LOOKBACK_DAYS, upsert_prices
from app.providers.base import ProviderError, ProviderRouter

log = logging.getLogger("quantlens.ingest")


async def backfill_symbol(db: Session, router: ProviderRouter, symbol: str, interval: str = "1d",
                          lookback_days: int | None = None) -> dict:
    """Fetch from the newest stored bar (minus a 2-day overlap) to now; full lookback if empty."""
    now = pd.Timestamp(datetime.now(UTC))
    latest = db.scalar(select(func.max(Price.ts)).where(Price.symbol == symbol, Price.interval == interval))
    if latest is None:
        start = now - pd.Timedelta(days=lookback_days or DEFAULT_LOOKBACK_DAYS[interval])
    else:
        start = pd.Timestamp(latest, unit="s", tz="UTC") - pd.Timedelta(days=2)
    try:
        res = await router.fetch_ohlcv(symbol, interval, start, now)
    except ProviderError as e:
        return {"symbol": symbol, "interval": interval, "ok": False, "error": str(e), "new_bars": 0}
    n = upsert_prices(db, symbol, interval, res.df, res.source)
    return {"symbol": symbol, "interval": interval, "ok": True, "source": res.source, "new_bars": n}


async def backfill_many(db: Session, router: ProviderRouter, symbols: list[str], interval: str = "1d",
                        lookback_days: int | None = None) -> list[dict]:
    return [await backfill_symbol(db, router, s, interval, lookback_days) for s in symbols]
