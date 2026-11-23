import json

import httpx
import pandas as pd
import pytest

from app.providers.angelone import AngelOneProvider, ScripMaster, chunk_ranges, parse_candles
from app.providers.base import ProviderError, RateLimitedError

CREDS = {"api_key": "k", "client": "C1", "pin": "1234", "totp": "JBSWY3DPEHPK3PXPJBSWY3DPEHPK3PXP"}
MASTER = [
    {"token": "2885", "symbol": "RELIANCE-EQ", "exch_seg": "NSE"},
    {"token": "11536", "symbol": "TCS-EQ", "exch_seg": "NSE"},
    {"token": "1", "symbol": "RELIANCE", "exch_seg": "BSE"},
]
ROWS = [["2026-01-05T00:00:00+05:30", 100, 110, 95, 105, 1000], ["2026-01-06T00:00:00+05:30", 105, 112, 101, 111, 1500]]


def provider(handler):
    sm = ScripMaster()
    sm.load(MASTER)
    return AngelOneProvider(httpx.AsyncClient(transport=httpx.MockTransport(handler)), sm, CREDS)


def ok_handler(calls):
    def h(req: httpx.Request):
        body = json.loads(req.content)
        calls.append((req.url.path, body, dict(req.headers)))
        if "loginByPassword" in req.url.path:
            assert body["clientcode"] == "C1" and len(body["totp"]) == 6
            return httpx.Response(200, json={"status": True, "data": {"jwtToken": "J", "refreshToken": "R"}})
        return httpx.Response(200, json={"status": True, "data": ROWS})
    return h


def test_scrip_master_maps_nse_equity_only():
    sm = ScripMaster()
    sm.load(MASTER)
    assert sm.token("reliance") == ("NSE", "2885")
    assert sm.token("NIFTY 50") == ("NSE", "99926000")
    with pytest.raises(ProviderError):
        sm.token("NOPE")


def test_chunking_respects_day_limit():
    a, b = pd.Timestamp("2026-01-01"), pd.Timestamp("2026-04-01")
    ch = chunk_ranges(a, b, "1m")  # 30-day cap
    assert all((y - x).days <= 30 for x, y in ch) and ch[0][0] == a and ch[-1][1] == b
    assert len(ch) == 3
    assert len(chunk_ranges(a, b, "1d")) == 1


def test_parse_candles_to_utc():
    df = parse_candles(ROWS)
    assert str(df.index.tz) == "UTC" and df.index[0] == pd.Timestamp("2026-01-04 18:30", tz="UTC")
    assert (df["adj_close"] == df["close"]).all()
    with pytest.raises(ProviderError):
        parse_candles([])


async def test_fetch_logs_in_once_and_sends_auth():
    calls = []
    p = provider(ok_handler(calls))
    df = await p.fetch_ohlcv("RELIANCE", "1d", pd.Timestamp("2026-01-01", tz="UTC"), pd.Timestamp("2026-01-10", tz="UTC"))
    await p.fetch_ohlcv("TCS", "1d", pd.Timestamp("2026-01-01", tz="UTC"), pd.Timestamp("2026-01-10", tz="UTC"))
    assert len(df) == 2
    logins = [c for c in calls if "loginByPassword" in c[0]]
    assert len(logins) == 1
    candle = [c for c in calls if "getCandleData" in c[0]]
    assert candle[0][1]["symboltoken"] == "2885" and candle[0][1]["interval"] == "ONE_DAY"
    assert candle[0][2]["authorization"] == "Bearer J"


async def test_403_is_rate_limit_error():
    def h(req):
        if "loginByPassword" in req.url.path:
            return httpx.Response(200, json={"status": True, "data": {"jwtToken": "J"}})
        return httpx.Response(403, text="Access denied because of exceeding access rate")
    p = provider(h)
    with pytest.raises(RateLimitedError):
        await p.fetch_ohlcv("TCS", "1d", pd.Timestamp("2026-01-01", tz="UTC"), pd.Timestamp("2026-01-10", tz="UTC"))


async def test_expired_token_relogins_once():
    state = {"candle": 0, "login": 0}

    def h(req):
        if "loginByPassword" in req.url.path:
            state["login"] += 1
            return httpx.Response(200, json={"status": True, "data": {"jwtToken": f"J{state['login']}"}})
        state["candle"] += 1
        if state["candle"] == 1:
            return httpx.Response(401, json={"status": False})
        return httpx.Response(200, json={"status": True, "data": ROWS})
    p = provider(h)
    df = await p.fetch_ohlcv("TCS", "1d", pd.Timestamp("2026-01-01", tz="UTC"), pd.Timestamp("2026-01-10", tz="UTC"))
    assert len(df) == 2 and state["login"] == 2


async def test_api_error_message_surfaces():
    def h(req):
        if "loginByPassword" in req.url.path:
            return httpx.Response(200, json={"status": False, "errorcode": "AB1050", "message": "Invalid totp"})
    p = provider(h)
    with pytest.raises(ProviderError, match="Invalid totp"):
        await p.login()


def test_not_configured_without_creds():
    assert not AngelOneProvider(creds={"api_key": "", "client": "", "pin": "", "totp": ""}).is_configured()
