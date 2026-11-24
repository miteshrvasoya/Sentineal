"""Candlestick patterns (causal) and honest historical edge statistics.

A pattern at bar t uses bars <= t. Edge stats measure forward close-to-close return after the
signal bar and compare the hit rate with the stock's own base rate (a binomial test), because a
"bullish" pattern that merely matches the share of up days has no edge.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from scipy.stats import binomtest

from app.features.volatility import atr

# name -> expected direction ("bull" | "bear" | "neutral")
DIRECTION = {
    "doji": "neutral", "hammer": "bull", "shooting_star": "bear",
    "bullish_engulfing": "bull", "bearish_engulfing": "bear",
    "morning_star": "bull", "evening_star": "bear",
    "bullish_harami": "bull", "bearish_harami": "bear",
    "three_white_soldiers": "bull", "three_black_crows": "bear",
    "inside_bar": "neutral", "outside_bar": "neutral",
}
HORIZONS = (1, 5, 10)
MIN_N = 30


def detect(df: pd.DataFrame) -> pd.DataFrame:
    """Boolean frame, one column per pattern."""
    o, h, lo, c = df["open"], df["high"], df["low"], df["close"]
    body, rng = (c - o).abs(), (h - lo)
    upper, lower = h - np.maximum(o, c), np.minimum(o, c) - lo
    bull, bear = c > o, c < o
    a = atr(df)
    long_body = body >= 0.8 * a
    down5, up5 = c.shift(1) < c.shift(6), c.shift(1) > c.shift(6)  # trend context, prior bars only
    p = lambda s, n=1: s.shift(n)  # noqa: E731
    out = pd.DataFrame(index=df.index)
    out["doji"] = (rng > 0) & (body <= 0.1 * rng)
    out["hammer"] = (lower >= 2 * body) & (upper <= 0.3 * body.clip(lower=rng * 0.05)) & (body > 0) & down5
    out["shooting_star"] = (upper >= 2 * body) & (lower <= 0.3 * body.clip(lower=rng * 0.05)) & (body > 0) & up5
    out["bullish_engulfing"] = p(bear) & bull & (o <= p(c)) & (c >= p(o)) & (body > p(body))
    out["bearish_engulfing"] = p(bull) & bear & (o >= p(c)) & (c <= p(o)) & (body > p(body))
    out["morning_star"] = (p(bear, 2) & p(long_body, 2) & (p(body) <= 0.3 * p(body, 2)) & bull
                           & (c > (p(o, 2) + p(c, 2)) / 2))
    out["evening_star"] = (p(bull, 2) & p(long_body, 2) & (p(body) <= 0.3 * p(body, 2)) & bear
                           & (c < (p(o, 2) + p(c, 2)) / 2))
    out["bullish_harami"] = (p(bear) & p(long_body) & bull & (o > p(c)) & (c < p(o)) & (body < 0.6 * p(body)))
    out["bearish_harami"] = (p(bull) & p(long_body) & bear & (o < p(c)) & (c > p(o)) & (body < 0.6 * p(body)))
    soldiers = bull & p(bull) & p(bull, 2) & (c > p(c)) & (p(c) > p(c, 2))
    soldiers &= (o > p(o)) & (o < p(c)) & (p(o) > p(o, 2)) & (p(o) < p(c, 2))
    soldiers &= (upper <= 0.3 * body) & (p(upper) <= 0.3 * p(body))
    out["three_white_soldiers"] = soldiers
    crows = bear & p(bear) & p(bear, 2) & (c < p(c)) & (p(c) < p(c, 2))
    crows &= (o < p(o)) & (o > p(c)) & (p(o) < p(o, 2)) & (p(o) > p(c, 2))
    crows &= (lower <= 0.3 * body) & (p(lower) <= 0.3 * p(body))
    out["three_black_crows"] = crows
    out["inside_bar"] = (h < p(h)) & (lo > p(lo))
    out["outside_bar"] = (h > p(h)) & (lo < p(lo))
    return out.fillna(False).astype(bool)


def edge_stats(df: pd.DataFrame, flags: pd.DataFrame | None = None) -> list[dict]:
    """Forward-return statistics per pattern on THIS stock's history (signal at close of bar t)."""
    flags = detect(df) if flags is None else flags
    c = df["close"]
    n_tests = len(DIRECTION) * len(HORIZONS)
    rows = []
    for name, direction in DIRECTION.items():
        sig = flags[name]
        row: dict = {"pattern": name, "direction": direction, "occurrences": int(sig.sum()), "horizons": {}}
        for h in HORIZONS:
            fwd = (c.shift(-h) / c - 1)
            valid = sig & fwd.notna()
            r = fwd[valid]
            allr = fwd.dropna()
            entry: dict = {"n": int(len(r))}
            if len(r):
                entry["avg_return_pct"] = round(float(r.mean() * 100), 3)
                entry["baseline_avg_return_pct"] = round(float(allr.mean() * 100), 3)
            if direction != "neutral" and len(r):
                sign = 1 if direction == "bull" else -1
                hits = int((sign * r > 0).sum())
                base = float((sign * allr > 0).mean())
                p = float(binomtest(hits, len(r), base).pvalue)
                entry.update(hit_rate=round(hits / len(r), 3), baseline_hit_rate=round(base, 3),
                             avg_dir_return_pct=round(float(sign * r.mean() * 100), 3),
                             p_value=round(p, 4), p_value_bonferroni=round(min(1.0, p * n_tests), 4))
                if len(r) < MIN_N:
                    entry["verdict"] = "insufficient sample"
                elif p * n_tests < 0.05 and hits / len(r) > base:
                    entry["verdict"] = "edge (after multiple-testing correction)"
                else:
                    entry["verdict"] = "no demonstrated edge"
            row["horizons"][f"{h}d"] = entry
        rows.append(row)
    return rows


def recent_signals(df: pd.DataFrame, flags: pd.DataFrame | None = None, last_n: int = 30) -> list[dict]:
    flags = detect(df) if flags is None else flags
    out = []
    tail = flags.iloc[-last_n:]
    for ts, row in tail.iterrows():
        for name in tail.columns[row.to_numpy()]:
            out.append({"t": int(ts.timestamp()), "pattern": name, "direction": DIRECTION[name]})
    return out
