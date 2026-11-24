"""Cointegration / pairs analysis (Engle-Granger).

Two prices are cointegrated if some combination of them (the SPREAD) keeps snapping back to a mean even though each wanders.
We regress log price of the stock on a peer, test the spread for stationarity, and report the spread's current z-score and
mean-reversion half-life. Scanning many peers will find false positives, so p-values are Bonferroni-corrected, and the
relationship is re-tested separately on each half of the history: pairs that only "work" in one half are fragile.
"""
from __future__ import annotations

import warnings
from typing import Any

import numpy as np
import pandas as pd


def _spread(y: np.ndarray, x: np.ndarray) -> tuple[np.ndarray, float, float]:
    b, a = np.polyfit(x, y, 1)
    return y - (a + b * x), float(b), float(a)


def half_life(spread: np.ndarray) -> float | None:
    """Days for the spread to close half the distance back to its mean, from an AR(1) fit: ds_t = lam * s_{t-1}."""
    s = spread - spread.mean()
    ds, lag = np.diff(s), s[:-1]
    if lag.std() == 0:
        return None
    lam = float(np.polyfit(lag, ds, 1)[0])
    return float(-np.log(2) / np.log(1 + lam)) if -1 < lam < 0 else None


def _coint_p(y: np.ndarray, x: np.ndarray) -> float:
    from statsmodels.tsa.stattools import coint
    warnings.filterwarnings("ignore")
    return float(coint(y, x, trend="c")[1])


def analyse(target: str, closes: dict[str, pd.Series], min_days: int = 250) -> dict[str, Any]:
    if target not in closes:
        raise ValueError(f"no prices for {target}")
    peers = [p for p in closes if p != target]
    rows: list[dict[str, Any]] = []
    series: dict[str, Any] = {}
    for p in peers:
        df = pd.concat([np.log(closes[target]), np.log(closes[p])], axis=1, join="inner").dropna()
        if len(df) < min_days:
            rows.append({"peer": p, "n": int(len(df)), "skipped": f"needs {min_days} common days"})
            continue
        y, x = df.iloc[:, 0].to_numpy(), df.iloc[:, 1].to_numpy()
        pv = _coint_p(y, x)
        sp, b, a = _spread(y, x)
        mid = len(df) // 2
        row = {"peer": p, "n": int(len(df)), "p": pv, "hedge_ratio": b, "half_life_days": half_life(sp),
               "zscore_now": float((sp[-1] - sp.mean()) / sp.std(ddof=1)) if sp.std() > 0 else None,
               "p_first_half": _coint_p(y[:mid], x[:mid]) if mid >= 120 else None,
               "p_second_half": _coint_p(y[mid:], x[mid:]) if len(df) - mid >= 120 else None}
        rows.append(row)
        series[p] = {"dates": [str(d.date()) for d in df.index[-500:]], "spread": sp[-500:].round(5).tolist(), "mean": float(sp.mean()), "std": float(sp.std(ddof=1))}
    tested = [r for r in rows if "p" in r]
    for r in tested:
        r["p_bonferroni"] = min(1.0, r["p"] * len(tested))
        r["stable"] = bool(r["p_first_half"] is not None and r["p_second_half"] is not None and max(r["p_first_half"], r["p_second_half"]) < 0.1)
        r["candidate"] = bool(r["p_bonferroni"] < 0.05 and r["stable"])
    tested.sort(key=lambda r: r["p"])
    best = tested[0]["peer"] if tested else None
    return {"target": target, "tested": len(tested), "peers": tested + [r for r in rows if "skipped" in r],
            "best": best, "best_spread": series.get(best) if best else None,
            "notes": ["p-values are Bonferroni-corrected for the number of peers scanned.",
                      "'stable' requires cointegration at p < 0.10 in BOTH halves of the history; fragile pairs fail this.",
                      "A z-score far from 0 only matters if the pair is a genuine, stable candidate. This is analysis, not a trade signal."]}
