"""Calendar effects (day-of-week, month-of-year) with significance tests, and an STL trend/seasonal decomposition.

Seasonality claims are easy to find by accident: test 12 months and one will look special by luck. Every group is tested
against the OTHER days (Welch t-test) in a step-down procedure, with Bonferroni correction for the number of groups. An
overall Kruskal-Wallis test asks whether the groups differ at all. Expect "nothing significant" on most stocks.
"""
from __future__ import annotations

import warnings
from typing import Any

import numpy as np
import pandas as pd
from scipy import stats

DOW = ["Mon", "Tue", "Wed", "Thu", "Fri"]
MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def _table(r: pd.Series, keys: pd.Series, names: list[str], offset: int) -> dict[str, Any]:
    """Per-group statistics with a STEP-DOWN significance procedure.

    Each group is compared (Welch t-test) with the days NOT in that group and not in any group already flagged. The strongest
    group is tested first; if it is significant after Bonferroni correction it is flagged and removed from the comparison pool,
    then the rest are re-tested against what is left. Without this, one genuine effect (say a strong Monday) would make every
    other weekday look "significantly low" simply because they are being compared with a pool that contains Monday.
    """
    n_groups = len(names)
    grp = {i: r[keys == i + offset] for i in range(n_groups)}
    flagged: set[int] = set()
    pvals: dict[int, float] = {}
    for _ in range(n_groups):
        cand: dict[int, float] = {}
        for i, g in grp.items():
            if i in flagged:
                continue
            rest = r[(keys != i + offset) & ~keys.isin([f + offset for f in flagged])]
            if len(g) >= 20 and len(rest) >= 20 and g.std(ddof=1) > 0:
                cand[i] = float(stats.ttest_ind(g, rest, equal_var=False).pvalue)
        if not cand:
            break
        best = min(cand, key=cand.get)           # type: ignore[arg-type]
        pvals.update({k: v for k, v in cand.items() if k not in flagged})
        if min(1.0, cand[best] * n_groups) < 0.05:
            flagged.add(best)
        else:
            break
    rows, groups = [], []
    for i, name in enumerate(names):
        g = grp[i]
        groups.append(g.to_numpy())
        p = pvals.get(i)
        rows.append({"group": name, "n": int(len(g)), "mean_pct": float(g.mean() * 100) if len(g) else None,
                     "up_share": float((g > 0).mean()) if len(g) else None, "p": p,
                     "p_bonferroni": None if p is None else min(1.0, p * n_groups), "significant": i in flagged})
    valid = [g for g in groups if len(g) >= 20]
    kw = float(stats.kruskal(*valid).pvalue) if len(valid) >= 2 else None
    return {"rows": rows, "kruskal_p": kw, "any_significant": bool(flagged), "overall_mean_pct": float(r.mean() * 100)}


def stl_decomposition(close: pd.Series, period: int = 21) -> dict[str, Any]:
    from statsmodels.tsa.seasonal import STL
    warnings.filterwarnings("ignore")
    lp = np.log(close.astype(float))
    res = STL(lp, period=period, robust=True).fit()
    resid, seas, trend = res.resid.to_numpy(), res.seasonal.to_numpy(), res.trend.to_numpy()
    s_strength = max(0.0, 1 - np.var(resid) / np.var(seas + resid)) if np.var(seas + resid) > 0 else 0.0
    t_strength = max(0.0, 1 - np.var(resid) / np.var(trend + resid)) if np.var(trend + resid) > 0 else 0.0
    n = min(500, len(close))
    return {"period": period, "seasonal_strength": float(s_strength), "trend_strength": float(t_strength),
            "dates": [str(d.date()) for d in close.index[-n:]], "trend_pct": ((np.exp(trend[-n:] - trend[-n]) - 1) * 100).round(3).tolist(),
            "seasonal_pct": ((np.exp(seas[-n:]) - 1) * 100).round(3).tolist(), "resid_pct": ((np.exp(resid[-n:]) - 1) * 100).round(3).tolist(),
            "reading": "strong repeating pattern" if s_strength > 0.64 else "weak or no repeating pattern" if s_strength < 0.3 else "mild repeating pattern"}


def analyse(close: pd.Series) -> dict[str, Any]:
    """close: daily closes indexed by date (naive). Needs at least ~2 years for the month table to mean anything."""
    r = np.log(close).diff().dropna()
    idx = pd.DatetimeIndex(r.index)
    wk = pd.Series(idx.day_of_week, index=r.index)
    mo = pd.Series(idx.month, index=r.index)
    notes = ["Each group is compared with the other days (step-down Welch tests), corrected for testing several groups at once."]
    if len(r) < 500:
        notes.append("Fewer than ~2 years of data: the monthly table is very noisy.")
    out = {"n_returns": int(len(r)), "first": str(r.index[0].date()), "last": str(r.index[-1].date()),
           "day_of_week": _table(r[wk < 5], wk[wk < 5], DOW, 0), "month": _table(r, mo, MONTHS, 1), "notes": notes}
    try:
        out["stl"] = stl_decomposition(close) if len(close) >= 100 else None
    except Exception as e:  # noqa: BLE001
        out["stl"], out["notes"].append(f"STL decomposition failed: {type(e).__name__}")
    return out
