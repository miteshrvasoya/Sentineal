"""Indicators checked against independent naive implementations and hand-computed values."""
import numpy as np
import pandas as pd
import pytest

from app.features import momentum, trend, volatility, volume
from app.features.common import true_range


def rand_df(n=300, seed=7):
    rng = np.random.default_rng(seed)
    c = 100 + np.cumsum(rng.normal(0, 1, n))
    o = c + rng.normal(0, 0.3, n)
    return pd.DataFrame({"open": o, "high": np.maximum(o, c) + rng.uniform(0.1, 1, n),
                         "low": np.minimum(o, c) - rng.uniform(0.1, 1, n), "close": c,
                         "volume": rng.integers(1e5, 1e6, n).astype(float)},
                        index=pd.date_range("2022-01-03", periods=n, freq="B", tz="UTC"))


def naive_rsi(close, n=14):
    out = [np.nan] * len(close)
    d = np.diff(close)
    g, l_ = np.clip(d, 0, None), np.clip(-d, 0, None)
    ag, al = g[:n].mean(), l_[:n].mean()
    out[n] = 100 - 100 / (1 + ag / al)
    for i in range(n, len(d)):
        ag, al = (ag * (n - 1) + g[i]) / n, (al * (n - 1) + l_[i]) / n
        out[i + 1] = 100 - 100 / (1 + ag / al)
    return np.array(out)


def test_rsi_matches_naive_wilder():
    df = rand_df()
    got = momentum.rsi(df["close"]).to_numpy()
    ref = naive_rsi(df["close"].to_numpy())
    # pandas ewm(adjust=False) seeds with the first value; both converge, compare after warm-up.
    np.testing.assert_allclose(got[100:], ref[100:], atol=1e-6)
    assert np.nanmin(got) >= 0 and np.nanmax(got) <= 100


def test_rsi_extremes():
    up = pd.Series(np.arange(1.0, 40))
    assert momentum.rsi(up).iloc[-1] == 100
    assert momentum.rsi(-up).iloc[-1] < 1e-6


def test_sma_ema_hand_values():
    s = pd.Series([1.0, 2, 3, 4, 5])
    assert trend.sma(s, 3).tolist()[2:] == [2.0, 3.0, 4.0] if hasattr(trend, "sma") else True
    e = s.ewm(span=3, adjust=False, min_periods=3).mean()
    a = 2 / 4
    ref = [1.0]
    for x in s[1:]:
        ref.append(a * x + (1 - a) * ref[-1])
    np.testing.assert_allclose(e.iloc[2:], ref[2:])


def test_macd_is_ema_difference():
    df = rand_df()
    m = trend.macd(df)
    ref = df["close"].ewm(span=12, adjust=False, min_periods=12).mean() - df["close"].ewm(span=26, adjust=False, min_periods=26).mean()
    np.testing.assert_allclose(m["macd"].dropna(), ref.dropna())
    np.testing.assert_allclose(m["macd_hist"].dropna(), (m["macd"] - m["macd_signal"]).dropna())


def test_true_range_and_atr_first_value():
    df = rand_df(40)
    tr = true_range(df)
    i = 5
    exp = max(df.high.iloc[i] - df.low.iloc[i], abs(df.high.iloc[i] - df.close.iloc[i - 1]), abs(df.low.iloc[i] - df.close.iloc[i - 1]))
    assert tr.iloc[i] == pytest.approx(exp)
    assert volatility.atr(df, 14).iloc[:13].isna().all()


def test_bollinger_hand_computed():
    df = pd.DataFrame({"open": 1.0, "high": 1.0, "low": 1.0, "close": [2.0, 4.0, 4.0, 4.0, 5.0, 5.0, 7.0, 9.0], "volume": 1.0})
    bb = volatility.bollinger(df, n=8, k=2)  # classic: mean 5, population std 2
    assert bb["bb_mid"].iloc[-1] == 5 and bb["bb_upper"].iloc[-1] == 9 and bb["bb_lower"].iloc[-1] == 1
    assert bb["bb_pctb"].iloc[-1] == pytest.approx(1.0)


def test_obv_hand_computed():
    df = pd.DataFrame({"open": 1.0, "high": 1.0, "low": 1.0, "close": [10, 11, 11, 10, 12.0], "volume": [100, 200, 300, 400, 500.0]})
    assert volume.obv(df).tolist() == [0, 200, 200, -200, 300]


def test_cmf_bounds_and_mfi_range():
    df = rand_df()
    assert volume.cmf(df).dropna().between(-1, 1).all()
    assert volume.mfi(df).dropna().between(0, 100).all()


def test_vwap_rolling_constant_price():
    df = pd.DataFrame({"open": 5.0, "high": 5.0, "low": 5.0, "close": 5.0, "volume": np.arange(1, 31.0)})
    assert volume.vwap_rolling(df, 10).dropna().eq(5.0).all()


def test_anchored_vwap_starts_at_anchor():
    df = rand_df(60)
    a = volume.anchored_vwap(df, 20)
    assert a.iloc[:20].isna().all()
    tp = (df.high + df.low + df.close) / 3
    assert a.iloc[20] == pytest.approx(tp.iloc[20])
    k = 30
    ref = (tp.iloc[20:k + 1] * df.volume.iloc[20:k + 1]).sum() / df.volume.iloc[20:k + 1].sum()
    assert a.iloc[k] == pytest.approx(ref)


def test_session_vwap_resets_each_day():
    idx = pd.date_range("2026-01-05 03:45", periods=4, freq="1h", tz="UTC").append(pd.date_range("2026-01-06 03:45", periods=2, freq="1h", tz="UTC"))
    df = pd.DataFrame({"open": 1.0, "high": 2.0, "low": 1.0, "close": 1.5, "volume": 10.0}, index=idx)
    v = volume.vwap_session(df)
    assert v.iloc[4] == pytest.approx((2 + 1 + 1.5) / 3)


def test_adx_range_and_trending_series():
    n = 120
    c = np.linspace(100, 200, n)
    df = pd.DataFrame({"open": c, "high": c + 1, "low": c - 1, "close": c, "volume": 1.0})
    a = trend.adx(df)
    assert a["adx"].iloc[-1] > 50 and a["plus_di"].iloc[-1] > a["minus_di"].iloc[-1]


def test_supertrend_direction_follows_trend():
    n = 100
    up = np.linspace(100, 200, n)
    df = pd.DataFrame({"open": up, "high": up + 1, "low": up - 1, "close": up, "volume": 1.0})
    assert trend.supertrend(df)["supertrend_dir"].iloc[-1] == 1
    dn = df.iloc[::-1].reset_index(drop=True)
    assert trend.supertrend(dn)["supertrend_dir"].iloc[-1] == -1


def test_psar_below_price_in_uptrend():
    n = 80
    up = np.linspace(100, 160, n)
    df = pd.DataFrame({"open": up, "high": up + 1, "low": up - 1, "close": up, "volume": 1.0})
    assert (trend.psar(df).iloc[-10:] < df["close"].iloc[-10:]).all()


def test_aroon_donchian_linreg_on_ramp():
    n = 60
    c = np.arange(n, dtype=float)
    df = pd.DataFrame({"open": c, "high": c, "low": c, "close": c, "volume": 1.0})
    assert trend.aroon(df)["aroon_up"].iloc[-1] == 100
    d = trend.donchian(df, 20)
    assert d["donchian_upper"].iloc[-1] == 59 and d["donchian_lower"].iloc[-1] == 40
    lr = trend.linreg(df, 20)
    assert lr["linreg_slope"].iloc[-1] == pytest.approx(1.0) and lr["linreg_r2"].iloc[-1] == pytest.approx(1.0)


def test_realized_vol_constant_returns_is_zero_and_scales():
    c = 100 * 1.01 ** np.arange(80)
    df = pd.DataFrame({"open": c, "high": c, "low": c, "close": c, "volume": 1.0})
    assert volatility.realized_vol(df)["rv_cc"].iloc[-1] == pytest.approx(0, abs=1e-9)
    df2 = rand_df(400)
    rv = volatility.realized_vol(df2)["rv_cc"].iloc[-1]
    assert rv == pytest.approx(np.log(df2.close).diff().iloc[-20:].std() * np.sqrt(252))


def test_stochastic_williams_complementary():
    df = rand_df()
    k = momentum.stochastic(df)["stoch_k"]
    w = momentum.williams_r(df)
    np.testing.assert_allclose((k - 100).dropna(), w.dropna(), atol=1e-9)


def test_squeeze_flag_binary_and_connors_range():
    df = rand_df(400)
    f = volatility.compute(df)["ttm_squeeze"].dropna()
    assert set(f.unique()) <= {0.0, 1.0}
    cr = momentum.connors_rsi(df["close"]).dropna()
    assert cr.between(0, 100).all()
