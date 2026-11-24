"""Fundamentals via yfinance (unofficial; field names vary by company, so extraction uses alias lists)."""
from __future__ import annotations

import asyncio
from typing import Any

import yfinance as yf

from app.providers.base import FundamentalsProvider, ProviderError
from app.providers.yahoo import to_yahoo_symbol


class YahooFundamentalsProvider(FundamentalsProvider):
    name = "yahoo_fundamentals"

    async def fetch(self, symbol: str) -> dict[str, Any]:
        t = yf.Ticker(to_yahoo_symbol(symbol))

        def _call() -> dict[str, Any]:
            return {"info": dict(t.info or {}), "income": t.financials, "balance": t.balance_sheet, "cashflow": t.cashflow}
        try:
            raw = await asyncio.to_thread(_call)
        except Exception as e:  # noqa: BLE001
            raise ProviderError(f"yfinance fundamentals error for {symbol}: {type(e).__name__}") from None
        if not raw["info"] and (raw["income"] is None or raw["income"].empty):
            raise ProviderError(f"no fundamentals returned for {symbol}")
        return raw
