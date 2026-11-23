"""Momentum / mean-reversion indicators."""
from __future__ import annotations

import numpy as np
import pandas as pd

from app.features.common import safe_div, sma, wilder


def rsi(close: pd.Series, n: int = 14) -> pd.Series:
    """RSI = 100 - 100/(1+RS), RS = Wilder-avg(gain)/Wilder-avg(loss)."""
    d = close.diff()
    ag, al = wilder(d.clip(lower=0), n), wilder((-d).clip(lower=0), n)
    out = 100 - 100 / (1 + safe_div(ag, al))
    return out.where(al != 0, 100.0).where(ag.notna())


def stochastic(df: pd.DataFrame, n: int = 14, d: int = 3) -> pd.DataFrame:
    """%K = 100*(C-LL)/(HH-LL); %D = SMA(%K, d)."""
    ll, hh = df["low"].rolling(n).min(), df["high"].rolling(n).max()
    k = 100 * safe_div(df["close"] - ll, hh - ll)
    return pd.DataFrame({"stoch_k": k, "stoch_d": sma(k, d)})


def stoch_rsi(close: pd.Series, n: int = 14) -> pd.Series:
    r = rsi(close, n)
    return safe_div(r - r.rolling(n).min(), r.rolling(n).max() - r.rolling(n).min())


def cci(df: pd.DataFrame, n: int = 20) -> pd.Series:
    """CCI = (TP - SMA(TP)) / (0.015 * mean abs deviation)."""
    tp = (df["high"] + df["low"] + df["close"]) / 3
    mad = tp.rolling(n).apply(lambda w: np.abs(w - w.mean()).mean(), raw=True)
    return safe_div(tp - sma(tp, n), 0.015 * mad)


def williams_r(df: pd.DataFrame, n: int = 14) -> pd.Series:
    ll, hh = df["low"].rolling(n).min(), df["high"].rolling(n).max()
    return -100 * safe_div(hh - df["close"], hh - ll)


def roc(close: pd.Series, n: int = 12) -> pd.Series:
    return 100 * (close / close.shift(n) - 1)


def tsi(close: pd.Series, long: int = 25, short: int = 13) -> pd.Series:
    """TSI = 100 * EMA(EMA(dC, long), short) / EMA(EMA(|dC|, long), short)."""
    d = close.diff()
    num = d.ewm(span=long, adjust=False, min_periods=long).mean().ewm(span=short, adjust=False).mean()
    den = d.abs().ewm(span=long, adjust=False, min_periods=long).mean().ewm(span=short, adjust=False).mean()
    return 100 * safe_div(num, den)


def zscore(close: pd.Series, n: int = 20) -> pd.Series:
    return safe_div(close - sma(close, n), close.rolling(n).std())


def distance_52w(df: pd.DataFrame, n: int = 252) -> pd.DataFrame:
    """Percent distance from the trailing n-bar high/low (n=252 on daily data)."""
    hi, lo = df["high"].rolling(n, min_periods=n // 2).max(), df["low"].rolling(n, min_periods=n // 2).min()
    return pd.DataFrame({"dist_52w_high": df["close"] / hi - 1, "dist_52w_low": df["close"] / lo - 1})


def connors_rsi(close: pd.Series, rsi_n: int = 3, streak_n: int = 2, rank_n: int = 100) -> pd.Series:
    """CRSI = mean(RSI(close,3), RSI(streak,2), PercentRank(ROC1, 100))."""
    sign = np.sign(close.diff()).fillna(0).to_numpy()
    streak = np.zeros(len(close))
    for i in range(1, len(close)):
        streak[i] = (streak[i - 1] + sign[i] if streak[i - 1] * sign[i] > 0 else sign[i]) if sign[i] != 0 else 0
    streak_s = pd.Series(streak, index=close.index)
    r1 = close.pct_change()
    prank = r1.rolling(rank_n + 1).apply(lambda w: (w[:-1] < w[-1]).mean() * 100, raw=True)
    return (rsi(close, rsi_n) + rsi(streak_s, streak_n) + prank) / 3


def compute(df: pd.DataFrame, rsi_period: int = 14, **_: object) -> pd.DataFrame:
    c = df["close"]
    out = pd.concat([stochastic(df), distance_52w(df)], axis=1)
    out["rsi"] = rsi(c, rsi_period)
    out["connors_rsi"] = connors_rsi(c)
    out["stoch_rsi"] = stoch_rsi(c)
    out["cci"] = cci(df)
    out["williams_r"] = williams_r(df)
    out["roc"] = roc(c)
    out["tsi"] = tsi(c)
    out["zscore_20"] = zscore(c)
    return out
