"""Backtest statistics and the 'was it luck?' tests."""
from __future__ import annotations

import math

import numpy as np
import pandas as pd

TRADING_DAYS = 252
MIN_BOOT = 60


def sharpe_of(excess: np.ndarray) -> float:
    sd = excess.std(ddof=1) if len(excess) > 1 else 0.0
    return float(excess.mean() / sd * math.sqrt(TRADING_DAYS)) if sd > 1e-12 else 0.0


def metrics(equity: pd.Series, trades: list[dict], rf: float = 0.07) -> dict:
    eq = equity.dropna()
    if len(eq) < 3:
        return {"n_days": len(eq), "n_trades": len(trades)}
    r = eq.pct_change().dropna().to_numpy()
    years = (eq.index[-1] - eq.index[0]).days / 365.25
    total = float(eq.iloc[-1] / eq.iloc[0] - 1)
    dd = eq / eq.cummax() - 1
    ex = r - rf / TRADING_DAYS
    dn = np.minimum(ex, 0)
    down = math.sqrt(float(np.mean(dn**2))) * math.sqrt(TRADING_DAYS)
    wins = [t["net_pnl"] for t in trades if t["net_pnl"] > 0]
    losses = [t["net_pnl"] for t in trades if t["net_pnl"] <= 0]
    tot_pnl = sum(t["net_pnl"] for t in trades)
    top5 = sum(sorted((t["net_pnl"] for t in trades), reverse=True)[:5])
    cagr = (1 + total) ** (1 / years) - 1 if years > 0.25 and total > -1 else None
    return {
        "n_days": len(eq), "years": round(years, 3), "total_return": total, "cagr": cagr,
        "volatility_annual": float(r.std(ddof=1) * math.sqrt(TRADING_DAYS)), "sharpe": sharpe_of(ex),
        "sortino": float(ex.mean() * TRADING_DAYS / down) if down > 1e-12 else None,
        "max_drawdown": float(dd.min()), "calmar": float(cagr / abs(dd.min())) if cagr is not None and dd.min() < -1e-9 else None,
        "n_trades": len(trades), "win_rate": len(wins) / len(trades) if trades else None,
        "profit_factor": float(sum(wins) / abs(sum(losses))) if losses and sum(losses) != 0 else None,
        "avg_trade_return": float(np.mean([t["return_pct"] for t in trades])) if trades else None,
        "avg_bars_held": float(np.mean([t["bars"] for t in trades])) if trades else None,
        "top5_trade_share": float(top5 / tot_pnl) if trades and tot_pnl > 0 else None,
    }


def stationary_bootstrap_indices(n: int, reps: int, mean_block: float, rng: np.random.Generator) -> np.ndarray:
    """Politis-Romano stationary bootstrap: resample in random-length blocks (mean `mean_block`), wrapping around the end."""
    p = 1.0 / max(mean_block, 1.0)
    starts = rng.integers(0, n, (reps, n))
    restart = rng.random((reps, n)) < p
    restart[:, 0] = True
    pos = np.arange(n)
    last = np.maximum.accumulate(np.where(restart, pos, 0), axis=1)
    base = np.take_along_axis(starts, last, axis=1)
    return (base + pos - last) % n


def bootstrap(daily_returns: np.ndarray, rf: float = 0.07, reps: int = 2000, seed: int = 0, trials: int = 1) -> dict:
    """Is the Sharpe ratio distinguishable from luck?  Resamples the strategy's daily returns in blocks (keeping
    volatility clustering) for a confidence interval, and re-centres them at zero excess return for the p-value:
    p = share of zero-skill worlds that produce a Sharpe at least as high as the one observed. `trials` is how many
    parameter sets were tried before this one was picked; the p-value is Bonferroni-adjusted for it."""
    r = np.asarray(daily_returns, float)
    r = r[np.isfinite(r)]
    if len(r) < MIN_BOOT:
        return {"available": False, "reason": f"need at least {MIN_BOOT} daily returns, have {len(r)}"}
    ex = r - rf / TRADING_DAYS
    obs = sharpe_of(ex)
    rng = np.random.default_rng(seed)
    idx = stationary_bootstrap_indices(len(ex), reps, max(5.0, len(ex) ** (1 / 3)), rng)
    boot = ex[idx]
    sd = boot.std(axis=1, ddof=1)
    sh = np.where(sd > 1e-12, boot.mean(axis=1) / np.where(sd > 1e-12, sd, 1) * math.sqrt(TRADING_DAYS), 0.0)
    null = (ex - ex.mean())[idx]
    nsd = null.std(axis=1, ddof=1)
    null_sh = np.where(nsd > 1e-12, null.mean(axis=1) / np.where(nsd > 1e-12, nsd, 1) * math.sqrt(TRADING_DAYS), 0.0)
    p = float((np.sum(null_sh >= obs) + 1) / (reps + 1))
    tot = np.exp(np.log1p(r)[idx].sum(axis=1)) - 1
    hist, edges = np.histogram(sh, bins=24)
    return {"available": True, "reps": reps, "sharpe": obs, "sharpe_ci90": [float(np.percentile(sh, 5)), float(np.percentile(sh, 95))],
            "total_return_ci90": [float(np.percentile(tot, 5)), float(np.percentile(tot, 95))],
            "p_value": p, "trials": trials, "p_adjusted": min(1.0, p * trials), "block_length": round(max(5.0, len(ex) ** (1 / 3)), 1),
            "hist": {"counts": hist.tolist(), "edges": [float(e) for e in edges]}}


def luck_test(position: np.ndarray, asset_returns: np.ndarray, reps: int = 2000, seed: int = 0, min_shift: int = 20) -> dict:
    """Circularly shift the strategy's positions against the price: the same number of trades, durations and time in the
    market, but with the timing destroyed. Where does the real timing rank among those random timings?  (Gross of costs.)"""
    pos = np.asarray(position, float)
    r = np.asarray(asset_returns, float)
    n = len(pos)
    if n < 2 * min_shift + 10 or pos.sum() == 0:
        return {"available": False, "reason": "not enough data or the strategy never held a position"}
    held = np.concatenate([[0.0], pos[:-1]])           # a signal from bar t-1 is held through bar t
    real = float(np.sum(held * np.log1p(r)))
    rng = np.random.default_rng(seed)
    shifts = rng.integers(min_shift, n - min_shift, reps)
    lr = np.log1p(r)
    sims = np.array([np.sum(np.roll(held, int(s)) * lr) for s in shifts])
    pct = float((sims < real).mean())
    return {"available": True, "reps": reps, "real_log_return": real, "random_median": float(np.median(sims)), "random_p5": float(np.percentile(sims, 5)),
            "random_p95": float(np.percentile(sims, 95)), "percentile": pct, "p_value": float((np.sum(sims >= real) + 1) / (reps + 1)),
            "note": "Gross of costs. Compares the timing against random timing with the same exposure."}
