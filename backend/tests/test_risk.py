import math

import numpy as np
import pandas as pd
import pytest
from scipy import stats

from app.features import risk as rk


def prices(vals, start="2024-01-01"):
    return pd.Series(vals, index=pd.bdate_range(start, periods=len(vals)), dtype=float)


def test_drawdown_stats_hand_computed():
    c = prices([100, 120, 90, 110, 80])
    d = rk.drawdown_stats(c)
    assert d["max_drawdown"] == pytest.approx(80 / 120 - 1)
    assert d["max_drawdown_peak"] == str(c.index[1].date()) and d["max_drawdown_trough"] == str(c.index[4].date())
    assert d["longest_drawdown_bars"] == 3 and d["current_drawdown_bars"] == 3
    assert rk.drawdown_stats(prices([1, 2, 3]))["max_drawdown"] == 0


def test_sharpe_and_sortino_hand_computed():
    r = pd.Series([0.02, 0.0, 0.02, 0.0])
    assert rk.sharpe(r, rf=0.0) == pytest.approx(0.01 / math.sqrt(4 * 0.01**2 / 3) * math.sqrt(252), rel=1e-9)
    assert rk.sharpe(r, rf=0.0) == pytest.approx(13.7477, abs=1e-3)
    assert rk.sharpe(pd.Series([0.01] * 10), 0.0) is None                              # zero variance -> undefined, not inf
    s = pd.Series([0.02, -0.01, 0.02, -0.01])
    assert rk.sortino(s, 0.0) == pytest.approx(0.005 / math.sqrt(0.0002 / 4) * math.sqrt(252), rel=1e-9)
    assert rk.sortino(pd.Series([0.01] * 5), 0.0) is None
    assert rk.sharpe(r, rf=0.05) < rk.sharpe(r, rf=0.0)                                # higher risk-free rate lowers Sharpe


def test_cagr_and_calmar():
    c = pd.Series([100, 121.0], index=pd.to_datetime(["2024-01-01", "2026-01-01"]))
    assert rk.cagr(c) == pytest.approx(0.10, abs=2e-3)
    c2 = pd.Series([100, 50, 100, 200.0], index=pd.to_datetime(["2023-01-01", "2023-06-01", "2024-01-01", "2025-01-01"]))
    assert rk.calmar(c2) == pytest.approx(rk.cagr(c2) / 0.5)


def test_var_cvar_historical_and_parametric():
    r = pd.Series(np.linspace(-0.05, 0.05, 101))
    v = rk.var_cvar(r, 0.95)
    assert v["historical_var"] == pytest.approx(0.045) and v["historical_cvar"] == pytest.approx(0.0475)
    assert v["historical_cvar"] >= v["historical_var"]
    sd = r.std(ddof=1)
    assert v["parametric_var"] == pytest.approx(-(r.mean() + stats.norm.ppf(0.05) * sd)) and v["parametric_cvar"] > v["parametric_var"]
    assert rk.var_cvar(r, 0.99)["historical_var"] > v["historical_var"]               # deeper tail = bigger loss
    assert rk.var_cvar(r.iloc[:10])["historical_var"] is None


def test_beta_alpha_correlation():
    rng = np.random.default_rng(0)
    rb = pd.Series(rng.normal(0.0004, 0.01, 300), index=pd.bdate_range("2024-01-01", periods=300))
    r = 2 * rb
    b = rk.beta_alpha(r, rb, rf=0.0)
    assert b["beta"] == pytest.approx(2.0) and b["correlation"] == pytest.approx(1.0) and b["alpha_annual"] == pytest.approx(0, abs=1e-9)
    shifted = rk.beta_alpha(rb + 0.001, rb, rf=0.0)
    assert shifted["beta"] == pytest.approx(1.0) and shifted["alpha_annual"] == pytest.approx(0.001 * 252)
    assert rk.beta_alpha(r.iloc[:10], rb.iloc[:10])["beta"] is None


def test_kelly_formula_and_negative_edge():
    z = pd.Series(np.random.default_rng(1).normal(size=500))
    z = (z - z.mean()) / z.std(ddof=1)
    r = z * math.sqrt(0.04 / 252) + 0.2 / 252                                          # exactly 20% mean, 4% variance, annualised
    k = rk.kelly(r, rf=0.07)
    assert k["full"] == pytest.approx((0.2 - 0.07) / 0.04) and k["half"] == pytest.approx(k["full"] / 2)
    assert "Display only" in k["warning"]
    assert rk.kelly(-r, rf=0.07)["full"] < 0


def test_rolling_metrics_are_causal():
    rng = np.random.default_rng(3)
    c = prices(100 * np.cumprod(1 + rng.normal(0.0003, 0.01, 400)))
    b = prices(100 * np.cumprod(1 + rng.normal(0.0003, 0.008, 400)))
    full, part = rk.rolling(c, b, 63), rk.rolling(c.iloc[:300], b.iloc[:300], 63)
    for k in ("volatility", "sharpe", "drawdown", "beta", "correlation"):
        np.testing.assert_allclose(full[k].iloc[:300].to_numpy(), part[k].to_numpy(), equal_nan=True, err_msg=k)


def test_summary_and_correlation_matrix():
    rng = np.random.default_rng(5)
    a = prices(100 * np.cumprod(1 + rng.normal(0.0004, 0.012, 300)))
    b = prices(100 * np.cumprod(1 + rng.normal(0.0003, 0.009, 300)))
    s = rk.summary(a, b)
    for key in ("cagr", "sharpe", "sortino", "calmar", "max_drawdown", "var_95", "var_99", "kelly", "vs_benchmark"):
        assert key in s
    assert s["worst_day"] < 0 < s["best_day"] and s["var_99"]["historical_var"] >= s["var_95"]["historical_var"]
    m = rk.correlation_matrix({"A": a, "B": a * 2, "C": 200 - a + a.iloc[0] * 0}, 250)
    assert m["symbols"] == ["A", "B", "C"] and m["matrix"][0][1] == pytest.approx(1.0, abs=1e-3)
    assert all(m["matrix"][i][i] == pytest.approx(1.0) for i in range(3))
