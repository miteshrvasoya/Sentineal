"""Volume and flow indicators. (Volume profile arrives with market structure in Phase 4.)"""
from __future__ import annotations

import numpy as np
import pandas as pd

from app.features.common import ema, safe_div


def obv(df: pd.DataFrame) -> pd.Series:
    """OBV_t = OBV_{t-1} + sign(C_t - C_{t-1}) * V_t."""
    return (np.sign(df["close"].diff()).fillna(0) * df["volume"]).cumsum()


def _clv(df: pd.DataFrame) -> pd.Series:
    """Close location value ((C-L)-(H-C))/(H-L)."""
    return safe_div((df["close"] - df["low"]) - (df["high"] - df["close"]), df["high"] - df["low"]).fillna(0)


def ad_line(df: pd.DataFrame) -> pd.Series:
    return (_clv(df) * df["volume"]).cumsum()


def cmf(df: pd.DataFrame, n: int = 20) -> pd.Series:
    """CMF = sum(CLV*V, n) / sum(V, n)."""
    return safe_div((_clv(df) * df["volume"]).rolling(n).sum(), df["volume"].rolling(n).sum())


def mfi(df: pd.DataFrame, n: int = 14) -> pd.Series:
    tp = (df["high"] + df["low"] + df["close"]) / 3
    raw = tp * df["volume"]
    pos = raw.where(tp.diff() > 0, 0.0).rolling(n).sum()
    neg = raw.where(tp.diff() < 0, 0.0).rolling(n).sum()
    return (100 - 100 / (1 + safe_div(pos, neg))).where(neg != 0, 100.0).where(pos.notna())


def vwap_rolling(df: pd.DataFrame, n: int = 20) -> pd.Series:
    """Rolling VWAP = sum(TP*V, n) / sum(V, n)."""
    tp = (df["high"] + df["low"] + df["close"]) / 3
    return safe_div((tp * df["volume"]).rolling(n).sum(), df["volume"].rolling(n).sum())


def vwap_session(df: pd.DataFrame) -> pd.Series:
    """Intraday VWAP that resets each IST trading day."""
    tp = (df["high"] + df["low"] + df["close"]) / 3
    day = df.index.tz_convert("Asia/Kolkata").date if getattr(df.index, "tz", None) else df.index.date
    g = pd.Series(day, index=df.index)
    return safe_div((tp * df["volume"]).groupby(g).cumsum(), df["volume"].groupby(g).cumsum())


def anchored_vwap(df: pd.DataFrame, anchor_pos: int) -> pd.Series:
    """VWAP accumulated from bar `anchor_pos` onward (NaN before). Anchor must be a past bar."""
    tp = (df["high"] + df["low"] + df["close"]) / 3
    pv, v = (tp * df["volume"]).copy(), df["volume"].copy()
    pv.iloc[:anchor_pos] = 0.0
    v.iloc[:anchor_pos] = 0.0
    out = safe_div(pv.cumsum(), v.cumsum())
    out.iloc[:anchor_pos] = np.nan
    return out


def vw_macd(df: pd.DataFrame, fast: int = 12, slow: int = 26, signal: int = 9) -> pd.DataFrame:
    """Volume-weighted MACD: EMA(C*V)/EMA(V) per leg."""
    def vwema(n: int) -> pd.Series:
        return safe_div(ema(df["close"] * df["volume"], n), ema(df["volume"], n))
    line = vwema(fast) - vwema(slow)
    sig = line.ewm(span=signal, adjust=False, min_periods=signal).mean()
    return pd.DataFrame({"vwmacd": line, "vwmacd_signal": sig, "vwmacd_hist": line - sig})


def compute(df: pd.DataFrame, **_: object) -> pd.DataFrame:
    v = df["volume"]
    base = v.rolling(20).mean().shift(1)  # exclude today from its own baseline
    sd = v.rolling(20).std().shift(1)
    up = v.where(df["close"] > df["close"].shift(1), 0.0).rolling(20).sum()
    dn = v.where(df["close"] < df["close"].shift(1), 0.0).rolling(20).sum()
    out = pd.concat([vw_macd(df)], axis=1)
    out["obv"], out["ad_line"], out["cmf"], out["mfi"] = obv(df), ad_line(df), cmf(df), mfi(df)
    out["vwap_20"] = vwap_rolling(df)
    out["rvol"] = safe_div(v, base)
    out["volume_zscore"] = safe_div(v - base, sd)
    out["updown_volume_ratio"] = safe_div(up, dn)
    if getattr(df.index, "tz", None) is not None and len(df) > 1 and (df.index[1] - df.index[0]) < pd.Timedelta(days=1):
        out["vwap_session"] = vwap_session(df)
    return out
