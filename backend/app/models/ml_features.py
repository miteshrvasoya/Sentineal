"""Feature matrix and labels for the machine-learning models.

Point-in-time rule: the row for day t uses only information available at the close of day t. The label for day t is
the direction of the NEXT `horizon` days' return, so it needs data up to t + horizon. Rows whose label window runs past
the end of the training data are dropped ("purged"); they are never guessed.

Only stationary features go in (ratios, oscillators, percentiles, returns), not raw price levels: a tree model fitted on
price levels from 2019 cannot say anything about 2026. Sentiment features come from the default non-LLM series, because
LLM-derived scores are forward-only (look-ahead contaminated) and must not train a model.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
import pandas as pd

from app.features.pipeline import compute_features
from app.features.sentiment import effective_date  # noqa: F401  (re-exported for callers building sentiment frames)

CLASSES = ("up", "flat", "down")
FLAT_K = 0.25
MIN_ROWS = 150

PRICE_COLS = [
    "ret_1d", "ret_5d", "ret_10d", "ret_21d", "ret_63d",
    "close_vs_ema20", "close_vs_ema50", "ema20_vs_ema50", "close_vs_sma200", "close_vs_vwap20",
    "macd_hist_pct", "macd_pct", "adx", "di_diff", "aroon_osc", "linreg_slope_pct", "linreg_r2", "supertrend_dir",
    "rsi", "stoch_k", "stoch_d", "stoch_rsi", "cci", "williams_r", "roc", "tsi", "zscore_20", "connors_rsi",
    "dist_52w_high", "dist_52w_low",
    "atr_pct", "bb_pctb", "bb_bandwidth", "rv_cc", "rv_parkinson", "rv_gk", "rv_yz", "rv_percentile", "ttm_squeeze", "bb_squeeze_pctile",
    "cmf", "mfi", "rvol", "volume_zscore", "updown_volume_ratio",
]
SENT_COLS = ["mean_sent", "sent_std", "n_articles", "volume_z", "pos_ratio", "recency_weighted", "sent_mom"]


def price_features(df: pd.DataFrame) -> pd.DataFrame:
    """Stationary technical features for every row of a UTC-indexed OHLCV frame (all causal)."""
    f = compute_features(df)
    c = df["close"]
    out = pd.DataFrame(index=df.index)
    for h in (1, 5, 10, 21, 63):
        out[f"ret_{h}d"] = f[f"ret_{h}d"]
    out["close_vs_ema20"] = c / f["ema_20"] - 1
    out["close_vs_ema50"] = c / f["ema_50"] - 1
    out["ema20_vs_ema50"] = f["ema_20"] / f["ema_50"] - 1
    out["close_vs_sma200"] = c / f["sma_200"] - 1
    out["close_vs_vwap20"] = c / f["vwap_20"] - 1
    out["macd_hist_pct"] = f["macd_hist"] / c
    out["macd_pct"] = f["macd"] / c
    out["di_diff"] = f["plus_di"] - f["minus_di"]
    out["linreg_slope_pct"] = f["linreg_slope"] / c
    for k in ("adx", "aroon_osc", "linreg_r2", "supertrend_dir", "rsi", "stoch_k", "stoch_d", "stoch_rsi", "cci", "williams_r", "roc", "tsi",
              "zscore_20", "connors_rsi", "dist_52w_high", "dist_52w_low", "atr_pct", "bb_pctb", "bb_bandwidth", "rv_cc", "rv_parkinson",
              "rv_gk", "rv_yz", "rv_percentile", "ttm_squeeze", "bb_squeeze_pctile", "cmf", "mfi", "rvol", "volume_zscore", "updown_volume_ratio"):
        out[k] = f[k]
    return out[PRICE_COLS].replace([np.inf, -np.inf], np.nan)


def sentiment_features(sent: pd.DataFrame | None, index: pd.DatetimeIndex) -> pd.DataFrame:
    """Align a daily sentiment frame (index = naive IST dates) to trading days. Days with no coverage stay NaN: absence of
    news is information, and filling it would invent data."""
    if sent is None or sent.empty:
        return pd.DataFrame(np.nan, index=index, columns=SENT_COLS)
    ist = index.tz_convert("Asia/Kolkata").tz_localize(None).normalize() if index.tz is not None else index.normalize()
    cols = [c for c in SENT_COLS if c in sent.columns]
    al = sent[cols].reindex(ist)
    al.index = index
    for c in SENT_COLS:
        if c not in al.columns:
            al[c] = np.nan
    return al[SENT_COLS]


def sentiment_coverage(sent: pd.DataFrame | None) -> dict:
    """How many calendar days of news history exist, and how many days actually had articles."""
    if sent is None or sent.empty:
        return {"days_span": 0, "days_with_news": 0}
    return {"days_span": int((sent.index.max() - sent.index.min()).days) + 1, "days_with_news": int((sent["n_articles"] > 0).sum())}


def feature_frame(df: pd.DataFrame, feature_set: str, aux: dict | None = None) -> pd.DataFrame:
    """feature_set: 'price' | 'sentiment' | 'combined'."""
    parts = []
    if feature_set in ("price", "combined"):
        parts.append(price_features(df))
    if feature_set in ("sentiment", "combined"):
        parts.append(sentiment_features((aux or {}).get("sentiment"), df.index))
    return pd.concat(parts, axis=1)


def band_series(close: pd.Series, horizon: int, k: float = FLAT_K) -> pd.Series:
    """Causal flat band at every origin: k x trailing-60d daily volatility x sqrt(h). Matches models.base.flat_band."""
    sig = np.log(close).diff().rolling(60).std()
    return k * sig * math.sqrt(horizon)


@dataclass
class Dataset:
    X: pd.DataFrame
    y: np.ndarray            # 0 = up, 1 = flat, 2 = down
    ret: np.ndarray          # forward log return over the horizon
    band: np.ndarray
    index: pd.DatetimeIndex


def build_dataset(df: pd.DataFrame, horizon: int, feature_set: str = "price", aux: dict | None = None) -> Dataset:
    """Labelled rows for training. Row t is kept only if its forward window [t, t + horizon] lies inside `df`."""
    X = feature_frame(df, feature_set, aux)
    close = df["close"]
    lc = np.log(close)
    fwd = lc.shift(-horizon) - lc                       # NaN for the last `horizon` rows: purged, never guessed
    band = band_series(close, horizon)
    ok = fwd.notna() & band.notna() & (X.notna().sum(axis=1) >= max(3, X.shape[1] // 4))
    fw, bd = fwd[ok].to_numpy(), band[ok].to_numpy()
    y = np.where(fw > bd, 0, np.where(fw < -bd, 2, 1))
    return Dataset(X[ok], y, fw, bd, X.index[ok])


def latest_row(df: pd.DataFrame, feature_set: str, aux: dict | None = None) -> pd.DataFrame:
    return feature_frame(df, feature_set, aux).iloc[[-1]]


# ---------------- optional advanced tools (library functions; see docs) ----------------

def triple_barrier_labels(close: pd.Series, horizon: int, up_mult: float = 1.0, down_mult: float = 1.0) -> pd.Series:
    """Triple-barrier labels (Lopez de Prado). From each day, watch the next `horizon` days: +1 if the price first touches the
    upper barrier (+up_mult x daily vol x sqrt(h)), -1 if it first touches the lower barrier, else 0 when the time barrier hits.
    Uses future data BY DESIGN (it is a label); never feed it as a feature."""
    lc = np.log(close).to_numpy()
    sig = np.log(close).diff().rolling(60).std().to_numpy() * math.sqrt(horizon)
    out = np.full(len(lc), np.nan)
    for t in range(len(lc) - horizon):
        if np.isnan(sig[t]):
            continue
        path = lc[t + 1:t + horizon + 1] - lc[t]
        up = np.flatnonzero(path >= up_mult * sig[t])
        dn = np.flatnonzero(path <= -down_mult * sig[t])
        first_up, first_dn = (up[0] if len(up) else horizon + 1), (dn[0] if len(dn) else horizon + 1)
        out[t] = 0.0 if first_up == first_dn == horizon + 1 else (1.0 if first_up < first_dn else -1.0)
    return pd.Series(out, index=close.index, name="triple_barrier")


def frac_diff(series: pd.Series, d: float = 0.4, thresh: float = 1e-4) -> pd.Series:
    """Fractional differentiation (fixed-width window): makes a price series closer to stationary while keeping more memory
    than a plain return. d = 0 returns the series, d = 1 is the ordinary first difference. Causal (weights apply to the past)."""
    w = [1.0]
    k = 1
    while abs(w[-1]) > thresh and k < 500:
        w.append(-w[-1] * (d - k + 1) / k)
        k += 1
    w_arr = np.array(w[::-1])
    width = len(w_arr)
    x = series.to_numpy(float)
    out = np.full(len(x), np.nan)
    for i in range(width - 1, len(x)):
        out[i] = float(w_arr @ x[i - width + 1:i + 1])
    return pd.Series(out, index=series.index, name=f"fracdiff_{d}")
