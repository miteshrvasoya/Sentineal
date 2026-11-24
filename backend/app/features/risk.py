"""Risk and performance metrics from a daily price series (252 trading days per year).

All rolling series are causal (the value at t uses only data up to t). The risk-free rate is an ASSUMPTION you can
change (default 7% a year, roughly Indian government bond yields); Sharpe/Sortino/alpha move with it.
These are descriptive statistics of the past, not forecasts. Kelly is shown for education only.
"""
from __future__ import annotations

import math
from typing import Any

import numpy as np
import pandas as pd
from scipy import stats

ANN = 252
EPS = 1e-12   # below this a std/variance is floating-point noise (e.g. constant returns), i.e. undefined


def simple_returns(close: pd.Series) -> pd.Series:
    return close.pct_change().dropna()


def drawdown_series(close: pd.Series) -> pd.Series:
    """Fractional drop from the running peak (0 at a new high, -0.25 = 25% below peak)."""
    return close / close.cummax() - 1


def drawdown_stats(close: pd.Series) -> dict[str, Any]:
    dd = drawdown_series(close)
    underwater = (dd < 0).astype(int)
    # lengths of consecutive underwater runs
    runs, cur = [], 0
    for u in underwater.to_numpy():
        cur = cur + 1 if u else 0
        runs.append(cur)
    trough = dd.idxmin() if len(dd) else None
    peak = close.loc[:trough].idxmax() if trough is not None else None
    return {"max_drawdown": float(dd.min()) if len(dd) else None,
            "max_drawdown_peak": None if peak is None else str(peak.date()), "max_drawdown_trough": None if trough is None else str(trough.date()),
            "longest_drawdown_bars": int(max(runs)) if runs else 0, "current_drawdown": float(dd.iloc[-1]) if len(dd) else None,
            "current_drawdown_bars": int(runs[-1]) if runs else 0}


def sharpe(r: pd.Series, rf: float = 0.07) -> float | None:
    ex = r - rf / ANN
    sd = ex.std(ddof=1)
    return None if len(r) < 2 or math.isnan(sd) or sd < EPS else float(ex.mean() / sd * math.sqrt(ANN))


def sortino(r: pd.Series, rf: float = 0.07) -> float | None:
    ex = r - rf / ANN
    dd = math.sqrt(float((np.minimum(ex, 0) ** 2).mean())) if len(ex) else 0.0
    return None if dd < EPS else float(ex.mean() / dd * math.sqrt(ANN))


def cagr(close: pd.Series) -> float | None:
    if len(close) < 2 or close.iloc[0] <= 0:
        return None
    years = (close.index[-1] - close.index[0]).days / 365.25
    return None if years <= 0 else float((close.iloc[-1] / close.iloc[0]) ** (1 / years) - 1)


def calmar(close: pd.Series) -> float | None:
    g, mdd = cagr(close), drawdown_stats(close)["max_drawdown"]
    return None if g is None or not mdd else float(g / abs(mdd))


def var_cvar(r: pd.Series, level: float = 0.95) -> dict[str, float | None]:
    """One-day Value at Risk and Conditional VaR (expected shortfall) as POSITIVE loss fractions.
    Historical: empirical percentile. Parametric: normal distribution fitted to mean and std (understates fat tails)."""
    if len(r) < 20:
        return {"historical_var": None, "historical_cvar": None, "parametric_var": None, "parametric_cvar": None}
    q = float(np.percentile(r, (1 - level) * 100))
    tail = r[r <= q]
    z = stats.norm.ppf(1 - level)
    mu, sd = float(r.mean()), float(r.std(ddof=1))
    return {"historical_var": -q, "historical_cvar": -float(tail.mean()) if len(tail) else -q,
            "parametric_var": -(mu + z * sd), "parametric_cvar": -(mu - sd * stats.norm.pdf(z) / (1 - level))}


def beta_alpha(r: pd.Series, rb: pd.Series, rf: float = 0.07) -> dict[str, float | None]:
    """Beta = cov(stock, benchmark)/var(benchmark). Alpha (Jensen, annualised) = mean excess return the beta does not explain."""
    df = pd.concat([r, rb], axis=1, join="inner").dropna()
    if len(df) < 30 or df.iloc[:, 1].var() < EPS:
        return {"beta": None, "alpha_annual": None, "correlation": None, "r_squared": None, "n": int(len(df))}
    x, y = df.iloc[:, 1] - rf / ANN, df.iloc[:, 0] - rf / ANN
    b = float(np.cov(y, x, ddof=1)[0, 1] / x.var(ddof=1))
    a = float((y.mean() - b * x.mean()) * ANN)
    c = float(df.iloc[:, 0].corr(df.iloc[:, 1]))
    return {"beta": b, "alpha_annual": a, "correlation": c, "r_squared": c * c, "n": int(len(df))}


def kelly(r: pd.Series, rf: float = 0.07) -> dict[str, Any]:
    """Gaussian Kelly fraction f* = (mu - rf) / sigma^2 using annualised figures. DISPLAY ONLY: it is extremely sensitive to
    estimation error and assumes the past mean continues, which is why full Kelly is rarely sensible."""
    mu, var = float(r.mean() * ANN), float(r.var(ddof=1) * ANN)
    f = None if var < EPS else (mu - rf) / var
    return {"full": f, "half": None if f is None else f / 2,
            "warning": "Display only, not a position size. Kelly assumes the historical average return persists and is very "
                       "sensitive to error; even small overestimates imply ruinous leverage. Negative means no historical edge."}


def rolling(close: pd.Series, bench: pd.Series | None, window: int = 63, rf: float = 0.07) -> dict[str, pd.Series]:
    r = close.pct_change()
    sd = r.rolling(window).std().where(lambda x: x > EPS)
    out = {"volatility": r.rolling(window).std() * math.sqrt(ANN),
           "sharpe": (r - rf / ANN).rolling(window).mean() / sd * math.sqrt(ANN),
           "drawdown": drawdown_series(close)}
    if bench is not None:
        rb = bench.pct_change().reindex(r.index)
        out["beta"] = r.rolling(window).cov(rb) / rb.rolling(window).var().where(lambda x: x > EPS)
        out["correlation"] = r.rolling(window).corr(rb)
    return out


def summary(close: pd.Series, bench: pd.Series | None = None, rf: float = 0.07, window: int = 63) -> dict[str, Any]:
    """All headline metrics plus chart series for one stock (and optionally its benchmark)."""
    r = simple_returns(close)
    out: dict[str, Any] = {
        "n_returns": int(len(r)), "rf": rf, "first": str(close.index[0].date()), "last": str(close.index[-1].date()),
        "cagr": cagr(close), "volatility_annual": float(r.std(ddof=1) * math.sqrt(ANN)) if len(r) > 1 else None,
        "sharpe": sharpe(r, rf), "sortino": sortino(r, rf), "calmar": calmar(close), **drawdown_stats(close),
        "var_95": var_cvar(r, 0.95), "var_99": var_cvar(r, 0.99), "kelly": kelly(r, rf) if len(r) > 30 else None,
        "best_day": float(r.max()) if len(r) else None, "worst_day": float(r.min()) if len(r) else None,
    }
    if bench is not None:
        out["vs_benchmark"] = beta_alpha(r, simple_returns(bench), rf)
    return out


def correlation_matrix(closes: dict[str, pd.Series], days: int = 252) -> dict[str, Any]:
    df = pd.DataFrame(closes).dropna(how="all").iloc[-(days + 1):]
    rets = df.pct_change().dropna(how="all")
    c = rets.corr(min_periods=30)
    return {"symbols": list(c.columns), "matrix": [[None if pd.isna(v) else round(float(v), 3) for v in row] for row in c.to_numpy()],
            "days": int(len(rets))}
