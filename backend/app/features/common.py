"""Shared helpers. Every feature at row t may use only rows <= t (point-in-time safe)."""
from __future__ import annotations

import numpy as np
import pandas as pd

OHLCV = ["open", "high", "low", "close", "volume"]


def wilder(s: pd.Series, n: int) -> pd.Series:
    """Wilder smoothing (RMA): seed = SMA of the first n valid values, then
    RMA_t = (RMA_{t-1}*(n-1) + x_t)/n. Matches textbook RSI/ATR/ADX and TradingView's ta.rma."""
    x = s.to_numpy(dtype=float)
    out = np.full(len(x), np.nan)
    valid = np.flatnonzero(~np.isnan(x))
    if len(valid) >= n:
        i0 = valid[0] + n - 1
        out[i0] = x[valid[0]:i0 + 1].mean()
        for i in range(i0 + 1, len(x)):
            out[i] = (out[i - 1] * (n - 1) + x[i]) / n if not np.isnan(x[i]) else np.nan
    return pd.Series(out, index=s.index)


def ema(s: pd.Series, n: int) -> pd.Series:
    """EMA_t = a*x_t + (1-a)*EMA_{t-1}, a = 2/(n+1)."""
    return s.ewm(span=n, adjust=False, min_periods=n).mean()


def sma(s: pd.Series, n: int) -> pd.Series:
    return s.rolling(n).mean()


def true_range(df: pd.DataFrame) -> pd.Series:
    """TR = max(H-L, |H-C_prev|, |L-C_prev|)."""
    pc = df["close"].shift(1)
    return pd.concat([df["high"] - df["low"], (df["high"] - pc).abs(), (df["low"] - pc).abs()], axis=1).max(axis=1)


def safe_div(a: pd.Series, b: pd.Series) -> pd.Series:
    return a / b.replace(0, np.nan)
