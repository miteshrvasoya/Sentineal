"""Volatility indicators. Annualisation assumes 252 trading days (daily bars)."""
from __future__ import annotations

import numpy as np
import pandas as pd

from app.features.common import safe_div, sma, true_range, wilder

ANN = 252


def atr(df: pd.DataFrame, n: int = 14) -> pd.Series:
    return wilder(true_range(df), n)


def bollinger(df: pd.DataFrame, n: int = 20, k: float = 2.0) -> pd.DataFrame:
    """Bands = SMA +/- k*std; %B = (C-lower)/(upper-lower); bandwidth = (upper-lower)/mid."""
    mid, sd = sma(df["close"], n), df["close"].rolling(n).std(ddof=0)
    up, lo = mid + k * sd, mid - k * sd
    return pd.DataFrame({"bb_mid": mid, "bb_upper": up, "bb_lower": lo,
                         "bb_pctb": safe_div(df["close"] - lo, up - lo), "bb_bandwidth": safe_div(up - lo, mid)})


def keltner(df: pd.DataFrame, n: int = 20, mult: float = 1.5) -> pd.DataFrame:
    mid = df["close"].ewm(span=n, adjust=False, min_periods=n).mean()
    a = atr(df, n)
    return pd.DataFrame({"kc_mid": mid, "kc_upper": mid + mult * a, "kc_lower": mid - mult * a})


def realized_vol(df: pd.DataFrame, n: int = 20) -> pd.DataFrame:
    """Annualised close-to-close, Parkinson, Garman-Klass and Yang-Zhang volatility."""
    o, h, lo, c = df["open"], df["high"], df["low"], df["close"]
    lc = np.log(c / c.shift(1))
    cc = lc.rolling(n).std() * np.sqrt(ANN)
    park = np.sqrt((np.log(h / lo) ** 2).rolling(n).mean() / (4 * np.log(2)) * ANN)
    gk_term = 0.5 * np.log(h / lo) ** 2 - (2 * np.log(2) - 1) * np.log(c / o) ** 2
    gk = np.sqrt(gk_term.rolling(n).mean().clip(lower=0) * ANN)
    ro, rc = np.log(o / c.shift(1)), np.log(c / o)
    rs = (np.log(h / c) * np.log(h / o) + np.log(lo / c) * np.log(lo / o))
    k = 0.34 / (1.34 + (n + 1) / (n - 1))
    yz_var = ro.rolling(n).var() + k * rc.rolling(n).var() + (1 - k) * rs.rolling(n).mean()
    yz = np.sqrt(yz_var.clip(lower=0) * ANN)
    pct = cc.rolling(ANN, min_periods=60).apply(lambda w: (w[:-1] < w[-1]).mean() * 100, raw=True)
    return pd.DataFrame({"rv_cc": cc, "rv_parkinson": park, "rv_gk": gk, "rv_yz": yz, "rv_percentile": pct})


def compute(df: pd.DataFrame, bb_period: int = 20, bb_std: float = 2.0, **_: object) -> pd.DataFrame:
    bb, kc = bollinger(df, bb_period, bb_std), keltner(df)
    out = pd.concat([bb, kc, realized_vol(df)], axis=1)
    a = atr(df)
    out["atr"] = a
    out["atr_pct"] = 100 * safe_div(a, df["close"])
    # TTM squeeze: Bollinger bands fully inside Keltner channel.
    out["ttm_squeeze"] = ((bb["bb_upper"] < kc["kc_upper"]) & (bb["bb_lower"] > kc["kc_lower"])).where(bb["bb_upper"].notna() & kc["kc_upper"].notna()).astype(float)
    out["bb_squeeze_pctile"] = bb["bb_bandwidth"].rolling(126, min_periods=40).apply(lambda w: (w[:-1] < w[-1]).mean() * 100, raw=True)
    return out
