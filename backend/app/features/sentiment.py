"""Per-ticker, per-day sentiment features. Point-in-time safe by construction.

An article published at or after the 15:30 IST close belongs to the NEXT calendar day's bucket, so a
feature stamped day d contains only information published before day d's close. Windows look backward only.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from scipy import stats

from app.data import calendar as cal

HALF_LIFE_H = 24.0
WINDOW_DAYS = 7
POS_T = 0.15  # |score| above this counts as a positive / negative article


def effective_date(published_epoch: pd.Series) -> pd.Series:
    """IST date bucket; post-close articles roll to the next day."""
    ist = pd.to_datetime(published_epoch, unit="s", utc=True).dt.tz_convert(cal.IST)
    after_close = (ist.dt.hour * 60 + ist.dt.minute) >= (cal.CLOSE_T.hour * 60 + cal.CLOSE_T.minute)
    d = ist.dt.normalize().dt.tz_localize(None)
    return d + pd.to_timedelta(after_close.astype(int), unit="D")


def daily_features(articles: pd.DataFrame) -> pd.DataFrame:
    """`articles` needs columns: published (epoch s), score. Returns one row per calendar day
    from the first to the last bucket (n_articles = 0 on quiet days)."""
    cols = ["mean_sent", "sent_std", "n_articles", "volume_z", "volume_spike", "pos_ratio",
            "recency_weighted", "sent_mom"]
    if articles.empty:
        return pd.DataFrame(columns=cols, index=pd.DatetimeIndex([], name="date"))
    a = articles.copy()
    a["date"] = effective_date(a["published"])
    days = pd.date_range(a["date"].min(), a["date"].max(), freq="D", name="date")
    g = a.groupby("date")["score"]
    out = pd.DataFrame(index=days)
    out["mean_sent"] = g.mean()
    out["sent_std"] = g.std(ddof=0)
    out["n_articles"] = g.size().reindex(days).fillna(0).astype(int)
    pos = a[a["score"] > POS_T].groupby("date").size().reindex(days).fillna(0)
    neg = a[a["score"] < -POS_T].groupby("date").size().reindex(days).fillna(0)
    out["pos_ratio"] = (pos + 1) / (neg + 1)          # add-one smoothing: finite on quiet days
    prior = out["n_articles"].shift(1)
    mu, sd = prior.rolling(30, min_periods=10).mean(), prior.rolling(30, min_periods=10).std(ddof=0)
    # Counts are roughly Poisson, so floor the spread at sqrt(mean): a perfectly flat baseline would
    # otherwise have std 0 and any spike would be undefined (NaN) instead of flagged.
    sd_eff = np.maximum(sd, np.sqrt(mu).clip(lower=0.5))
    out["volume_z"] = (out["n_articles"] - mu) / sd_eff
    out["volume_spike"] = (out["volume_z"] > 2).astype(int)

    # Recency-weighted score as of each day's close: exp decay with a 24h half-life over a 7-day window.
    sc = a["score"].to_numpy()
    pub_s = a["published"].to_numpy(dtype=float)       # epoch seconds (avoids datetime64 unit pitfalls)
    rw = []
    for d in days:
        close = pd.Timestamp(d).tz_localize(cal.IST) + pd.Timedelta(hours=cal.CLOSE_T.hour, minutes=cal.CLOSE_T.minute)
        age_h = (close.timestamp() - pub_s) / 3600.0
        m = (age_h >= 0) & (age_h <= WINDOW_DAYS * 24)
        w = 0.5 ** (age_h[m] / HALF_LIFE_H)
        rw.append(float((w * sc[m]).sum() / w.sum()) if m.any() else np.nan)
    out["recency_weighted"] = rw
    out["sent_mom"] = (out["mean_sent"].ewm(span=5, ignore_na=True).mean()
                       - out["mean_sent"].ewm(span=20, ignore_na=True).mean())
    return out[cols]


def divergence(sent_mom: pd.Series, close: pd.Series) -> pd.Series:
    """+1 = price up over 5d while sentiment momentum falls; -1 = price down while it rises; else 0."""
    r5 = close.pct_change(5).reindex(sent_mom.index)
    return pd.Series(np.where((r5 > 0) & (sent_mom < 0), 1, np.where((r5 < 0) & (sent_mom > 0), -1, 0)),
                     index=sent_mom.index)


def market_index(articles: pd.DataFrame) -> pd.Series:
    """Market-wide daily sentiment: article-count-weighted mean of the signed score across all tickers/news."""
    if articles.empty:
        return pd.Series(dtype=float, name="market_sentiment")
    d = effective_date(articles["published"])
    return articles.groupby(d)["score"].mean().rename("market_sentiment")


def lead_lag(sent: pd.Series, close: pd.Series, max_lag: int = 5, min_n: int = 30) -> list[dict]:
    """corr(sentiment_t, return_{t+lag}). lag > 0: sentiment leads price; lag < 0: price leads sentiment.
    Both series are indexed by calendar date; sentiment is reindexed onto trading days."""
    ret = close.pct_change()
    s = sent.reindex(ret.index)
    n_tests = 2 * max_lag + 1
    out = []
    for lag in range(-max_lag, max_lag + 1):
        df = pd.DataFrame({"s": s, "r": ret.shift(-lag)}).dropna()
        row: dict = {"lag": lag, "n": int(len(df)), "corr": None, "p": None, "p_bonferroni": None}
        if len(df) >= min_n and df["s"].std() > 0 and df["r"].std() > 0:
            c, p = stats.pearsonr(df["s"], df["r"])
            row.update(corr=round(float(c), 4), p=round(float(p), 4), p_bonferroni=round(min(1.0, float(p) * n_tests), 4))
        out.append(row)
    return out
