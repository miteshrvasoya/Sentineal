"""Provider abstractions, shared async rate limiter, retry/backoff and the fallback router."""
from __future__ import annotations

import abc
import asyncio
import logging
import random
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import TypeVar

import pandas as pd

log = logging.getLogger("quantlens.providers")
T = TypeVar("T")

INTERVALS = ("1m", "5m", "15m", "1h", "1d")
OHLCV_COLS = ["open", "high", "low", "close", "adj_close", "volume"]


class ProviderError(Exception):
    """Provider failed (network, auth, bad data). Triggers fallback."""


class RateLimitedError(ProviderError):
    """Provider signalled rate limiting (e.g. HTTP 403/429)."""


class RateLimiter:
    """Async token bucket: at most `rate` calls per `per` seconds, bursts up to `rate`."""

    def __init__(self, rate: int, per: float = 60.0) -> None:
        self.capacity = float(rate)
        self.tokens = float(rate)
        self.refill = rate / per
        self.updated = time.monotonic()
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        async with self._lock:
            while True:
                now = time.monotonic()
                self.tokens = min(self.capacity, self.tokens + (now - self.updated) * self.refill)
                self.updated = now
                if self.tokens >= 1:
                    self.tokens -= 1
                    return
                await asyncio.sleep((1 - self.tokens) / self.refill)


async def retry_with_backoff(
    fn: Callable[[], Awaitable[T]],
    *,
    attempts: int = 3,
    base: float = 0.5,
    cap: float = 8.0,
    retry_on: tuple[type[Exception], ...] = (ProviderError,),
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> T:
    """Exponential backoff with full jitter."""
    for i in range(attempts):
        try:
            return await fn()
        except retry_on as e:
            if i == attempts - 1:
                raise
            delay = random.uniform(0, min(cap, base * 2**i))
            log.warning("retry %d/%d after %.2fs: %s", i + 1, attempts, delay, e)
            await sleep(delay)
    raise AssertionError("unreachable")


def validate_ohlcv(df: pd.DataFrame) -> pd.DataFrame:
    """Return a cleaned frame or raise ProviderError. Index must be UTC DatetimeIndex."""
    if df is None or df.empty:
        raise ProviderError("empty frame")
    missing = [c for c in OHLCV_COLS if c not in df.columns]
    if missing:
        raise ProviderError(f"missing columns {missing}")
    df = df[OHLCV_COLS].dropna(subset=["open", "high", "low", "close"])
    df = df[~df.index.duplicated(keep="last")].sort_index()
    if df.empty:
        raise ProviderError("all rows NaN")
    if not df.index.is_monotonic_increasing:
        raise ProviderError("non-monotonic index")
    bad = (df["high"] < df[["open", "close", "low"]].max(axis=1) - 1e-9) | (df["low"] > df[["open", "close", "high"]].min(axis=1) + 1e-9)
    if bad.mean() > 0.05:
        raise ProviderError(f"{bad.mean():.0%} rows violate OHLC bounds")
    df = df[~bad]
    df["volume"] = df["volume"].fillna(0.0)
    return df


class MarketDataProvider(abc.ABC):
    name: str = "base"
    rate_limit: tuple[int, float] = (60, 60.0)  # (calls, per seconds)

    def __init__(self) -> None:
        self.limiter = RateLimiter(*self.rate_limit)

    def is_configured(self) -> bool:
        return True

    @abc.abstractmethod
    async def fetch_ohlcv(
        self, symbol: str, interval: str, start: pd.Timestamp, end: pd.Timestamp
    ) -> pd.DataFrame:
        """UTC-indexed frame with OHLCV_COLS. Raise ProviderError on failure."""

    async def fetch_quote(self, symbol: str) -> dict:
        raise ProviderError(f"{self.name} has no quote support")


class NewsProvider(abc.ABC):  # filled in Phase 5
    name: str = "base"


class FundamentalsProvider(abc.ABC):  # filled in Phase 6
    name: str = "base"


class MacroProvider(abc.ABC):  # filled in Phase 6
    name: str = "base"


@dataclass
class FetchResult:
    df: pd.DataFrame
    source: str
    errors: dict[str, str] = field(default_factory=dict)


class ProviderRouter:
    """Try providers in priority order; validate; fall back; record health."""

    def __init__(
        self,
        providers: list[MarketDataProvider],
        on_success: Callable[[str], None] | None = None,
        on_error: Callable[[str, str], None] | None = None,
    ) -> None:
        self.providers = providers
        self.on_success = on_success or (lambda n: None)
        self.on_error = on_error or (lambda n, m: None)

    async def fetch_ohlcv(
        self, symbol: str, interval: str, start: pd.Timestamp, end: pd.Timestamp
    ) -> FetchResult:
        errors: dict[str, str] = {}
        for p in self.providers:
            if not p.is_configured():
                continue
            try:
                await p.limiter.acquire()
                raw = await retry_with_backoff(lambda p=p: p.fetch_ohlcv(symbol, interval, start, end))
                df = validate_ohlcv(raw)
                self.on_success(p.name)
                return FetchResult(df, p.name, errors)
            except Exception as e:  # noqa: BLE001 - any provider failure triggers fallback
                msg = f"{type(e).__name__}: {e}"
                errors[p.name] = msg
                self.on_error(p.name, msg)
                log.warning("provider %s failed for %s: %s", p.name, symbol, msg)
        raise ProviderError("; ".join(f"{k}: {v}" for k, v in errors.items()) or "no provider configured")

    async def fetch_quote(self, symbol: str) -> tuple[dict, str]:
        errors = []
        for p in self.providers:
            if not p.is_configured():
                continue
            try:
                await p.limiter.acquire()
                q = await retry_with_backoff(lambda p=p: p.fetch_quote(symbol), attempts=2)
                self.on_success(p.name)
                return q, p.name
            except Exception as e:  # noqa: BLE001
                errors.append(f"{p.name}: {e}")
                self.on_error(p.name, str(e))
        raise ProviderError("; ".join(errors) or "no provider configured")
