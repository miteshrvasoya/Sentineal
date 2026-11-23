import asyncio
import time

import pandas as pd
import pytest

from app.providers.base import (
    ProviderError,
    ProviderRouter,
    RateLimiter,
    retry_with_backoff,
    validate_ohlcv,
)
from app.providers.yahoo import normalize_frame, to_yahoo_symbol
from tests.conftest import FakeProvider, make_frame


def test_symbol_mapping():
    assert to_yahoo_symbol("reliance") == "RELIANCE.NS"
    assert to_yahoo_symbol("NIFTY 50") == "^NSEI"
    assert to_yahoo_symbol("INDIA VIX") == "^INDIAVIX"
    assert to_yahoo_symbol("TCS.BO") == "TCS.BO"


def test_validate_rejects_empty_and_missing():
    with pytest.raises(ProviderError):
        validate_ohlcv(pd.DataFrame())
    with pytest.raises(ProviderError):
        validate_ohlcv(make_frame().drop(columns=["volume"]))


def test_validate_sorts_dedupes_and_rejects_bad_ohlc():
    df = make_frame(10)
    shuffled = pd.concat([df.iloc[5:], df.iloc[:5], df.iloc[:1]])
    out = validate_ohlcv(shuffled)
    assert out.index.is_monotonic_increasing and len(out) == 10
    bad = df.copy()
    bad["high"] = bad["low"] - 5
    with pytest.raises(ProviderError):
        validate_ohlcv(bad)


def test_normalize_yfinance_frame_localises_to_utc():
    idx = pd.date_range("2026-01-01", periods=3, freq="B")  # naive
    raw = pd.DataFrame({"Open": [1., 2, 3], "High": [2., 3, 4], "Low": [.5, 1, 2], "Close": [1.5, 2.5, 3.5],
                        "Adj Close": [1.5, 2.5, 3.5], "Volume": [10, 20, 30]}, index=idx)
    out = normalize_frame(raw)
    assert str(out.index.tz) == "UTC"
    assert out.index[0] == pd.Timestamp("2026-01-01 00:00", tz="Asia/Kolkata").tz_convert("UTC")
    with pytest.raises(ProviderError):
        normalize_frame(pd.DataFrame())


async def test_rate_limiter_throttles():
    rl = RateLimiter(rate=2, per=0.4)  # 5 tokens/sec after burst of 2
    t0 = time.monotonic()
    for _ in range(4):
        await rl.acquire()
    assert time.monotonic() - t0 >= 0.3


async def test_retry_backoff_then_success():
    n = {"i": 0}
    sleeps: list[float] = []

    async def fn():
        n["i"] += 1
        if n["i"] < 3:
            raise ProviderError("x")
        return "ok"

    async def fake_sleep(d):
        sleeps.append(d)

    assert await retry_with_backoff(fn, attempts=3, sleep=fake_sleep) == "ok"
    assert len(sleeps) == 2


async def test_router_falls_back_and_records_health():
    ok, err = [], []
    bad, good = FakeProvider("bad", fail=True), FakeProvider("good")
    r = ProviderRouter([bad, good], on_success=ok.append, on_error=lambda n, m: err.append(n))
    res = await r.fetch_ohlcv("X", "1d", pd.Timestamp("2025-01-01", tz="UTC"), pd.Timestamp("2025-06-01", tz="UTC"))
    assert res.source == "good" and "bad" in res.errors
    assert ok == ["good"] and err == ["bad"] * 1 or "bad" in err


async def test_router_all_fail_raises():
    r = ProviderRouter([FakeProvider("a", fail=True)])
    with pytest.raises(ProviderError):
        await asyncio.wait_for(
            r.fetch_ohlcv("X", "1d", pd.Timestamp("2025-01-01", tz="UTC"), pd.Timestamp("2025-02-01", tz="UTC")), 30)
