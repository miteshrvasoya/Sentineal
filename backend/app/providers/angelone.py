"""Angel One SmartAPI provider (REST via httpx; no order endpoints are used anywhere).

Auth: API key + client code + PIN + TOTP (pyotp). Session token refreshed automatically.
Candles are RAW (unadjusted); adj_close == close, so splits/bonuses are NOT adjusted here.
A 403/429 or "exceeding access rate" reply raises RateLimitedError (router backs off).
"""
from __future__ import annotations

import json
import logging
import time
from datetime import timedelta
from pathlib import Path

import httpx
import pandas as pd
import pyotp

from app.config import ROOT, get_settings
from app.providers.base import MarketDataProvider, ProviderError, RateLimitedError

log = logging.getLogger("quantlens.angelone")

BASE = "https://apiconnect.angelbroking.com"
SCRIP_MASTER_URL = "https://margincalculator.angelbroking.com/OpenAPI_File/files/OpenAPIScripMaster.json"
SCRIP_CACHE = ROOT / "data" / "cache" / "OpenAPIScripMaster.json"

AO_INTERVAL = {"1m": "ONE_MINUTE", "5m": "FIVE_MINUTE", "15m": "FIFTEEN_MINUTE",
               "1h": "ONE_HOUR", "1d": "ONE_DAY"}
# Max days of history per request (SmartAPI documented limits).
MAX_DAYS = {"1m": 30, "5m": 100, "15m": 200, "1h": 400, "1d": 2000}
INDEX_TOKENS = {"NIFTY 50": "99926000", "NIFTY BANK": "99926009", "INDIA VIX": "99926017"}


def chunk_ranges(start: pd.Timestamp, end: pd.Timestamp, interval: str) -> list[tuple[pd.Timestamp, pd.Timestamp]]:
    """Split [start, end] into windows no longer than the per-request day limit."""
    step = timedelta(days=MAX_DAYS[interval])
    out, cur = [], start
    while cur <= end:
        nxt = min(cur + step, end)
        out.append((cur, nxt))
        cur = nxt + timedelta(minutes=1) if interval != "1d" else nxt + timedelta(days=1)
    return out


def parse_candles(rows: list[list]) -> pd.DataFrame:
    """[[iso_ts, o, h, l, c, v], ...] -> UTC-indexed OHLCV frame."""
    if not rows:
        raise ProviderError("angelone returned no candles")
    df = pd.DataFrame(rows, columns=["ts", "open", "high", "low", "close", "volume"])
    df.index = pd.DatetimeIndex(pd.to_datetime(df.pop("ts"), utc=True))
    df["adj_close"] = df["close"]
    return df.astype(float)[["open", "high", "low", "close", "adj_close", "volume"]]


class ScripMaster:
    """symbol -> (exchange, token) from OpenAPIScripMaster.json, cached on disk for a day."""

    def __init__(self, path: Path = SCRIP_CACHE, max_age: float = 86400) -> None:
        self.path, self.max_age = path, max_age
        self._map: dict[str, str] | None = None

    def load(self, entries: list[dict] | None = None) -> None:
        if entries is None:
            fresh = self.path.exists() and time.time() - self.path.stat().st_mtime < self.max_age
            if not fresh:
                try:
                    r = httpx.get(SCRIP_MASTER_URL, timeout=60)
                    r.raise_for_status()
                    self.path.parent.mkdir(parents=True, exist_ok=True)
                    self.path.write_bytes(r.content)
                except httpx.HTTPError as e:
                    if not self.path.exists():
                        raise ProviderError(f"scrip master download failed: {e}") from e
                    log.warning("scrip master refresh failed, using stale cache: %s", e)
            entries = json.loads(self.path.read_text())
        m: dict[str, str] = {}
        for e in entries:
            if e.get("exch_seg") == "NSE" and str(e.get("symbol", "")).endswith("-EQ"):
                m[e["symbol"][:-3]] = str(e["token"])
        self._map = m

    def token(self, symbol: str) -> tuple[str, str]:
        s = symbol.upper()
        if s in INDEX_TOKENS:
            return "NSE", INDEX_TOKENS[s]
        if self._map is None:
            self.load()
        assert self._map is not None
        if s not in self._map:
            raise ProviderError(f"{s} not in Angel One NSE equity scrip master")
        return "NSE", self._map[s]


class AngelOneProvider(MarketDataProvider):
    name = "angelone"
    rate_limit = (3, 1.0)  # historical API is ~3 req/s

    def __init__(self, client: httpx.AsyncClient | None = None, scrips: ScripMaster | None = None,
                 creds: dict[str, str] | None = None) -> None:
        super().__init__()
        s = get_settings()
        self.creds = creds or {"api_key": s.angel_api_key, "client": s.angel_client_code,
                               "pin": s.angel_pin, "totp": s.angel_totp_secret}
        self.client = client or httpx.AsyncClient(timeout=30)
        self.scrips = scrips or ScripMaster()
        self._jwt: str | None = None
        self._refresh: str | None = None
        self._jwt_at = 0.0

    def is_configured(self) -> bool:
        return all(self.creds.values())

    def _headers(self, auth: bool = True) -> dict[str, str]:
        h = {"Content-Type": "application/json", "Accept": "application/json",
             "X-UserType": "USER", "X-SourceID": "WEB", "X-ClientLocalIP": "127.0.0.1",
             "X-ClientPublicIP": "127.0.0.1", "X-MACAddress": "00:00:00:00:00:00",
             "X-PrivateKey": self.creds["api_key"]}
        if auth and self._jwt:
            h["Authorization"] = f"Bearer {self._jwt}"
        return h

    @staticmethod
    def _check(r: httpx.Response) -> dict:
        if r.status_code in (403, 429) or "exceeding access rate" in r.text.lower():
            raise RateLimitedError(f"angelone rate limited (HTTP {r.status_code})")
        try:
            j = r.json()
        except ValueError as e:
            raise ProviderError(f"angelone non-JSON reply (HTTP {r.status_code})") from e
        if not j.get("status"):
            raise ProviderError(f"angelone error {j.get('errorcode')}: {j.get('message')}")
        return j

    async def login(self) -> None:
        body = {"clientcode": self.creds["client"], "password": self.creds["pin"],
                "totp": pyotp.TOTP(self.creds["totp"]).now()}
        try:
            r = await self.client.post(f"{BASE}/rest/auth/angelbroking/user/v1/loginByPassword",
                                       json=body, headers=self._headers(auth=False))
        except httpx.HTTPError as e:
            raise ProviderError(f"angelone login network error: {e}") from e
        d = self._check(r)["data"]
        self._jwt, self._refresh, self._jwt_at = d["jwtToken"], d.get("refreshToken"), time.time()

    async def _ensure_session(self) -> None:
        # Sessions last until ~5am IST; re-login every 6h to be safe.
        if self._jwt is None or time.time() - self._jwt_at > 6 * 3600:
            await self.login()

    async def _post(self, path: str, body: dict) -> dict:
        await self._ensure_session()
        for attempt in (0, 1):
            try:
                r = await self.client.post(f"{BASE}{path}", json=body, headers=self._headers())
            except httpx.HTTPError as e:
                raise ProviderError(f"angelone network error: {e}") from e
            if r.status_code == 401 and attempt == 0:  # token expired -> re-login once
                self._jwt = None
                await self.login()
                continue
            return self._check(r)
        raise ProviderError("angelone auth failed")

    async def fetch_ohlcv(self, symbol: str, interval: str, start: pd.Timestamp,
                          end: pd.Timestamp) -> pd.DataFrame:
        if interval not in AO_INTERVAL:
            raise ProviderError(f"unsupported interval {interval}")
        exch, token = self.scrips.token(symbol)
        fmt = "%Y-%m-%d %H:%M"
        frames = []
        for a, b in chunk_ranges(start.tz_convert("Asia/Kolkata"), end.tz_convert("Asia/Kolkata"), interval):
            await self.limiter.acquire()
            j = await self._post("/rest/secure/angelbroking/historical/v1/getCandleData", {
                "exchange": exch, "symboltoken": token, "interval": AO_INTERVAL[interval],
                "fromdate": a.strftime(fmt), "todate": b.strftime(fmt)})
            if j.get("data"):
                frames.append(parse_candles(j["data"]))
        if not frames:
            raise ProviderError("angelone returned no candles")
        df = pd.concat(frames)
        return df[~df.index.duplicated(keep="last")].sort_index()
