"""Yahoo Finance via yfinance. Unofficial and fragile: always a fallback-tier source."""
from __future__ import annotations

import asyncio

import pandas as pd
import yfinance as yf

from app.providers.base import OHLCV_COLS, MarketDataProvider, ProviderError

INDEX_MAP = {
    "NIFTY 50": "^NSEI",
    "NIFTY": "^NSEI",
    "NIFTY BANK": "^NSEBANK",
    "BANKNIFTY": "^NSEBANK",
    "INDIA VIX": "^INDIAVIX",
    "SENSEX": "^BSESN",
}
YF_INTERVAL = {"1m": "1m", "5m": "5m", "15m": "15m", "1h": "60m", "1d": "1d"}
# Yahoo's hard lookback limits for intraday data (days).
MAX_LOOKBACK_DAYS = {"1m": 7, "5m": 60, "15m": 60, "1h": 730}


def to_yahoo_symbol(symbol: str) -> str:
    s = symbol.upper().strip()
    if s in INDEX_MAP:
        return INDEX_MAP[s]
    if s.startswith("^") or "." in s:
        return s
    return f"{s}.NS"


def normalize_frame(raw: pd.DataFrame) -> pd.DataFrame:
    """Convert a yfinance frame (auto_adjust=False) to our schema with a UTC index."""
    if raw is None or raw.empty:
        raise ProviderError("yfinance returned no data")
    df = raw.copy()
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    df = df.rename(columns={"Open": "open", "High": "high", "Low": "low", "Close": "close",
                            "Adj Close": "adj_close", "Volume": "volume"})
    if "adj_close" not in df.columns:
        df["adj_close"] = df["close"]
    idx = pd.DatetimeIndex(df.index)
    idx = idx.tz_localize("Asia/Kolkata") if idx.tz is None else idx
    df.index = idx.tz_convert("UTC")
    return df[OHLCV_COLS]


class YahooProvider(MarketDataProvider):
    name = "yahoo"
    rate_limit = (30, 60.0)

    async def fetch_ohlcv(
        self, symbol: str, interval: str, start: pd.Timestamp, end: pd.Timestamp
    ) -> pd.DataFrame:
        if interval not in YF_INTERVAL:
            raise ProviderError(f"unsupported interval {interval}")
        ysym = to_yahoo_symbol(symbol)
        max_days = MAX_LOOKBACK_DAYS.get(interval)
        if max_days:
            earliest = pd.Timestamp.now(tz="UTC") - pd.Timedelta(days=max_days - 1)
            start = max(start, earliest)

        def _call() -> pd.DataFrame:
            return yf.Ticker(ysym).history(
                start=start.tz_convert("UTC").strftime("%Y-%m-%d"),
                end=(end + pd.Timedelta(days=1)).tz_convert("UTC").strftime("%Y-%m-%d"),
                interval=YF_INTERVAL[interval], auto_adjust=False, actions=False,
            )

        try:
            raw = await asyncio.to_thread(_call)
        except Exception as e:
            raise ProviderError(f"yfinance error for {ysym}: {e}") from e
        return normalize_frame(raw)

    async def fetch_quote(self, symbol: str) -> dict:
        ysym = to_yahoo_symbol(symbol)

        def _call() -> dict:
            fi = yf.Ticker(ysym).fast_info
            return {"last": float(fi["last_price"]), "prev_close": float(fi["previous_close"])}

        try:
            q = await asyncio.to_thread(_call)
        except Exception as e:
            raise ProviderError(f"yfinance quote error for {ysym}: {e}") from e
        q["change"] = q["last"] - q["prev_close"]
        q["change_pct"] = q["change"] / q["prev_close"] * 100 if q["prev_close"] else 0.0
        return q
