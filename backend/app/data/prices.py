"""Price service: DB-first reads with provider refresh, upserts, adjusted views."""
from __future__ import annotations

import logging
import time
from datetime import UTC, datetime

import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.data import calendar as cal
from app.data.models import Price, ProviderHealth
from app.providers.base import INTERVALS, FetchResult, ProviderError, ProviderRouter

log = logging.getLogger("quantlens.prices")

_last_refresh: dict[tuple[str, str], float] = {}  # in-memory TTL guard (Redis optional later)

DEFAULT_LOOKBACK_DAYS = {"1d": 365 * 5, "1h": 365, "15m": 58, "5m": 58, "1m": 6}


def clear_refresh_cache() -> None:
    _last_refresh.clear()


def to_epoch_seconds(idx: pd.DatetimeIndex) -> list[int]:
    """UTC epoch seconds, independent of the index's datetime64 resolution (ns/us/ms/s)."""
    return [int(v) for v in (idx - pd.Timestamp("1970-01-01", tz="UTC")) // pd.Timedelta(seconds=1)]


def upsert_prices(db: Session, symbol: str, interval: str, df: pd.DataFrame, source: str) -> int:
    ts = to_epoch_seconds(df.index)
    existing = set(
        db.scalars(
            select(Price.ts).where(
                Price.symbol == symbol, Price.interval == interval,
                Price.ts >= min(ts), Price.ts <= max(ts),
            )
        )
    )
    rows = [
        Price(symbol=symbol, interval=interval, ts=t, open=float(r.open), high=float(r.high),
              low=float(r.low), close=float(r.close), adj_close=float(r.adj_close),
              volume=float(r.volume), source=source)
        for t, r in zip(ts, df.itertuples(), strict=True)
        if t not in existing
    ]
    # Refresh the most recent bar(s) (still forming / revised) instead of skipping them.
    if existing:
        latest = max(existing)
        for p in db.scalars(select(Price).where(Price.symbol == symbol, Price.interval == interval, Price.ts >= latest)):
            if p.ts in set(ts):
                r = df.iloc[ts.index(p.ts)]
                p.open, p.high, p.low, p.close = float(r.open), float(r.high), float(r.low), float(r.close)
                p.adj_close, p.volume, p.source = float(r.adj_close), float(r.volume), source
    db.add_all(rows)
    db.commit()
    return len(rows)


def load_prices(db: Session, symbol: str, interval: str, start_ts: int | None = None,
                end_ts: int | None = None) -> pd.DataFrame:
    q = select(Price).where(Price.symbol == symbol, Price.interval == interval)
    if start_ts is not None:
        q = q.where(Price.ts >= start_ts)
    if end_ts is not None:
        q = q.where(Price.ts <= end_ts)
    rows = db.scalars(q.order_by(Price.ts)).all()
    if not rows:
        return pd.DataFrame(columns=["open", "high", "low", "close", "adj_close", "volume"])
    df = pd.DataFrame(
        [(r.ts, r.open, r.high, r.low, r.close, r.adj_close, r.volume, r.source) for r in rows],
        columns=["ts", "open", "high", "low", "close", "adj_close", "volume", "source"],
    ).set_index("ts")
    return df


def apply_adjustment(df: pd.DataFrame) -> pd.DataFrame:
    """Scale OHL by adj_close/close so splits/dividends are continuous. Volume unchanged."""
    out = df.copy()
    f = (out["adj_close"] / out["close"]).replace([float("inf")], 1.0).fillna(1.0)
    for c in ("open", "high", "low"):
        out[c] = out[c] * f
    out["close"] = out["adj_close"]
    return out


def _is_stale(df: pd.DataFrame, interval: str, now: datetime) -> bool:
    if df.empty:
        return True
    last_ts = int(df.index.max())
    if interval == "1d":
        last_bar_day = datetime.fromtimestamp(last_ts, cal.IST).date()
        return last_bar_day < cal.last_completed_session(now) and last_bar_day < now.astimezone(cal.IST).date()
    return now.timestamp() - last_ts > 15 * 60 and cal.market_status(now)["state"] == "open"


async def ensure_prices(
    db: Session, router: ProviderRouter, symbol: str, interval: str,
    start: pd.Timestamp | None = None, end: pd.Timestamp | None = None,
    ttl: int = 300, force: bool = False,
) -> FetchResult | None:
    """Refresh from providers when data is missing/stale. Returns FetchResult if fetched."""
    if interval not in INTERVALS:
        raise ValueError(f"interval must be one of {INTERVALS}")
    now = datetime.now(UTC)
    end = end or pd.Timestamp(now)
    start = start or end - pd.Timedelta(days=DEFAULT_LOOKBACK_DAYS[interval])
    have = load_prices(db, symbol, interval)
    need_older = (not have.empty) and interval == "1d" and int(have.index.min()) > start.timestamp() + 7 * 86400 * 5
    key = (symbol, interval)
    recently = time.monotonic() - _last_refresh.get(key, -1e9) < ttl
    if not force and not need_older and not _is_stale(have, interval, now):
        return None
    if not force and recently and not have.empty:
        return None
    _last_refresh[key] = time.monotonic()
    res = await router.fetch_ohlcv(symbol, interval, start, end)
    upsert_prices(db, symbol, interval, res.df, res.source)
    return res


def record_health(db_factory, name: str, error: str | None) -> None:  # type: ignore[no-untyped-def]
    """Persist provider health. db_factory yields a Session context manager."""
    now = int(time.time())
    today = datetime.now(cal.IST).strftime("%Y-%m-%d")
    with db_factory() as db:
        h = db.get(ProviderHealth, name) or ProviderHealth(name=name, calls_today=0, day=today)
        if h.day != today:
            h.day, h.calls_today = today, 0
        h.calls_today += 1
        if error is None:
            h.last_success = now
        else:
            h.last_error, h.last_error_msg = now, error[:500]
        db.merge(h)
        db.commit()


__all__ = ["ProviderError"]
