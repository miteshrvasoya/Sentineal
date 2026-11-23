"""Proof that features are point-in-time safe.

1. Prefix invariance: a feature value at t must be identical whether or not data after t exists.
2. Leakage canary: a deliberately leaky feature MUST be caught by (1) and by the predictive check.
3. On a pure random walk (no real signal) no honest feature may predict next-day return.
"""
import numpy as np
import pandas as pd
import pytest

from app.features.pipeline import SETS, compute_features
from tests.test_features import rand_df


def lookahead_violations(fn, df: pd.DataFrame, cut: int = 250, tol: float = 1e-9) -> list[str]:
    full, part = fn(df), fn(df.iloc[:cut])
    bad = []
    for c in part.columns:
        a, b = full[c].iloc[:cut].to_numpy(dtype=float), part[c].to_numpy(dtype=float)
        if not np.allclose(a, b, atol=tol, equal_nan=True):
            bad.append(c)
    return bad


def leaky_canary(df: pd.DataFrame) -> pd.DataFrame:
    return pd.DataFrame({"canary": df["close"].shift(-1) / df["close"] - 1,           # tomorrow's return
                         "centered_ma": df["close"].rolling(5, center=True).mean()})   # uses future bars


@pytest.mark.parametrize("name", list(SETS))
def test_prefix_invariance(name):
    df = rand_df(420, seed=11)
    assert lookahead_violations(lambda d: compute_features(d, [name]), df, cut=300) == []


def test_prefix_invariance_intraday_session_vwap():
    idx = pd.date_range("2026-01-05 03:45", periods=200, freq="15min", tz="UTC")
    df = rand_df(200)
    df.index = idx
    assert lookahead_violations(lambda d: compute_features(d, ["volume"]), df, cut=120) == []


def test_canary_is_caught_by_prefix_test():
    bad = lookahead_violations(leaky_canary, rand_df(420, seed=3), cut=300)
    assert set(bad) == {"canary", "centered_ma"}


def test_no_honest_feature_predicts_next_return_but_canary_does():
    df = rand_df(2500, seed=5)
    fwd = df["close"].pct_change().shift(-1)
    feats = compute_features(df)
    corr = feats.apply(lambda s: s.corr(fwd, method="spearman")).abs()
    # level-type columns (price-scale, cumulative) trend with a random walk; skip non-stationary levels
    levels = {c for c in feats.columns if c.startswith(("sma_", "ema_", "bb_mid", "bb_upper", "bb_lower", "kc_", "donchian", "ichi_", "supertrend", "psar", "vwap", "obv", "ad_line"))}
    honest = corr.drop(index=[c for c in corr.index if c in levels]).dropna()
    assert honest.max() < 0.12, honest.sort_values().tail(3).to_dict()
    assert abs(leaky_canary(df)["canary"].corr(fwd, method="spearman")) > 0.99
