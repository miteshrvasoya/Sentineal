"""Trend indicators."""
from __future__ import annotations

import numpy as np
import pandas as pd

from app.features.common import ema, safe_div, sma, true_range, wilder


def returns(df: pd.DataFrame, horizons: tuple[int, ...] = (1, 5, 10, 21, 63)) -> pd.DataFrame:
    """Simple and log returns over trailing horizons: C_t / C_{t-h} - 1."""
    out = {}
    for h in horizons:
        out[f"ret_{h}d"] = df["close"].pct_change(h)
        out[f"logret_{h}d"] = np.log(df["close"]).diff(h)
    return pd.DataFrame(out)


def moving_averages(df: pd.DataFrame, periods: tuple[int, ...] = (9, 20, 50, 100, 200)) -> pd.DataFrame:
    out = {}
    for n in periods:
        out[f"sma_{n}"] = sma(df["close"], n)
        out[f"ema_{n}"] = ema(df["close"], n)
    return pd.DataFrame(out)


def macd(df: pd.DataFrame, fast: int = 12, slow: int = 26, signal: int = 9) -> pd.DataFrame:
    """MACD = EMA(fast) - EMA(slow); signal = EMA(MACD, signal); hist = MACD - signal."""
    line = ema(df["close"], fast) - ema(df["close"], slow)
    sig = line.ewm(span=signal, adjust=False, min_periods=signal).mean()
    return pd.DataFrame({"macd": line, "macd_signal": sig, "macd_hist": line - sig})


def adx(df: pd.DataFrame, n: int = 14) -> pd.DataFrame:
    """Wilder ADX/DI. +DM = up-move if up>down and up>0; DX = 100*|+DI - -DI|/(+DI + -DI)."""
    up, down = df["high"].diff(), -df["low"].diff()
    plus_dm = up.where((up > down) & (up > 0), 0.0)
    minus_dm = down.where((down > up) & (down > 0), 0.0)
    atr = wilder(true_range(df), n)
    pdi = 100 * safe_div(wilder(plus_dm, n), atr)
    mdi = 100 * safe_div(wilder(minus_dm, n), atr)
    dx = 100 * safe_div((pdi - mdi).abs(), pdi + mdi)
    return pd.DataFrame({"plus_di": pdi, "minus_di": mdi, "adx": wilder(dx.dropna(), n).reindex(df.index)})


def supertrend(df: pd.DataFrame, n: int = 10, mult: float = 3.0) -> pd.DataFrame:
    """Supertrend: ATR bands around HL2 that ratchet; direction +1 (up) / -1 (down)."""
    atr = wilder(true_range(df), n).to_numpy()
    hl2 = ((df["high"] + df["low"]) / 2).to_numpy()
    close = df["close"].to_numpy()
    bu, bl = hl2 + mult * atr, hl2 - mult * atr
    fu, fl = bu.copy(), bl.copy()
    st = np.full(len(df), np.nan)
    direction = np.full(len(df), np.nan)
    start = int(np.argmax(~np.isnan(atr))) if (~np.isnan(atr)).any() else len(df)
    for i in range(start + 1, len(df)):
        fu[i] = bu[i] if (bu[i] < fu[i - 1] or close[i - 1] > fu[i - 1]) else fu[i - 1]
        fl[i] = bl[i] if (bl[i] > fl[i - 1] or close[i - 1] < fl[i - 1]) else fl[i - 1]
        prev_dir = direction[i - 1] if not np.isnan(direction[i - 1]) else (1.0 if close[i - 1] >= hl2[i - 1] else -1.0)
        if prev_dir == 1.0:
            direction[i] = -1.0 if close[i] < fl[i] else 1.0
        else:
            direction[i] = 1.0 if close[i] > fu[i] else -1.0
        st[i] = fl[i] if direction[i] == 1.0 else fu[i]
    return pd.DataFrame({"supertrend": st, "supertrend_dir": direction}, index=df.index)


def psar(df: pd.DataFrame, step: float = 0.02, max_step: float = 0.2) -> pd.Series:
    """Parabolic SAR (Wilder)."""
    h, lo = df["high"].to_numpy(), df["low"].to_numpy()
    n = len(df)
    out = np.full(n, np.nan)
    if n < 2:
        return pd.Series(out, index=df.index, name="psar")
    up = h[1] > h[0] or df["close"].iloc[1] >= df["close"].iloc[0]
    sar = lo[0] if up else h[0]
    ep = h[0] if up else lo[0]
    af = step
    out[0] = sar
    for i in range(1, n):
        sar = sar + af * (ep - sar)
        if up:
            sar = min(sar, lo[i - 1], lo[i - 2] if i > 1 else lo[i - 1])
            if lo[i] < sar:
                up, sar, ep, af = False, ep, lo[i], step
            elif h[i] > ep:
                ep, af = h[i], min(af + step, max_step)
        else:
            sar = max(sar, h[i - 1], h[i - 2] if i > 1 else h[i - 1])
            if h[i] > sar:
                up, sar, ep, af = True, ep, h[i], step
            elif lo[i] < ep:
                ep, af = lo[i], min(af + step, max_step)
        out[i] = sar
    return pd.Series(out, index=df.index, name="psar")


def ichimoku(df: pd.DataFrame, conv: int = 9, base: int = 26, span_b: int = 52) -> pd.DataFrame:
    """Tenkan/Kijun midpoints; cloud spans are computed from data `base` bars ago (causal).

    The lagging span (chikou) is omitted: plotting it back in time needs the future.
    """
    def mid(n: int) -> pd.Series:
        return (df["high"].rolling(n).max() + df["low"].rolling(n).min()) / 2
    tenkan, kijun = mid(conv), mid(base)
    return pd.DataFrame({
        "ichi_tenkan": tenkan, "ichi_kijun": kijun,
        "ichi_span_a": ((tenkan + kijun) / 2).shift(base),
        "ichi_span_b": mid(span_b).shift(base),
    })


def aroon(df: pd.DataFrame, n: int = 25) -> pd.DataFrame:
    """Aroon Up = 100*(n - bars since highest high)/n over the last n+1 bars."""
    since_hi = df["high"].rolling(n + 1).apply(lambda w: n - np.argmax(w), raw=True)
    since_lo = df["low"].rolling(n + 1).apply(lambda w: n - np.argmin(w), raw=True)
    up, dn = 100 * (n - since_hi) / n, 100 * (n - since_lo) / n
    return pd.DataFrame({"aroon_up": up, "aroon_down": dn, "aroon_osc": up - dn})


def donchian(df: pd.DataFrame, n: int = 20) -> pd.DataFrame:
    up, lo = df["high"].rolling(n).max(), df["low"].rolling(n).min()
    return pd.DataFrame({"donchian_upper": up, "donchian_lower": lo, "donchian_mid": (up + lo) / 2})


def linreg(df: pd.DataFrame, n: int = 20) -> pd.DataFrame:
    """Rolling OLS of close on time: slope (price units/bar) and R^2."""
    x = np.arange(n) - (n - 1) / 2
    sxx = (x**2).sum()

    def slope(w: np.ndarray) -> float:
        return float((x * (w - w.mean())).sum() / sxx)

    def r2(w: np.ndarray) -> float:
        syy = ((w - w.mean()) ** 2).sum()
        return float((x * (w - w.mean())).sum() ** 2 / (sxx * syy)) if syy > 0 else np.nan

    c = df["close"]
    return pd.DataFrame({"linreg_slope": c.rolling(n).apply(slope, raw=True),
                         "linreg_r2": c.rolling(n).apply(r2, raw=True)})


def compute(df: pd.DataFrame, ma_periods: tuple[int, ...] = (9, 20, 50, 100, 200), **_: object) -> pd.DataFrame:
    return pd.concat([returns(df), moving_averages(df, tuple(ma_periods)), macd(df), adx(df),
                      supertrend(df), psar(df), ichimoku(df), aroon(df), donchian(df), linreg(df)], axis=1)
