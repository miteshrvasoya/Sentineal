"""Statistical models: probabilities, quantiles, planted-structure recovery, determinism."""
import math

import numpy as np
import pandas as pd
import pytest

from app.models import registry as reg
from app.models.base import (
    FLAT_K,
    ModelView,
    daily_sigma,
    direction,
    flat_band,
    probs_from_normal,
    probs_from_samples,
    quantiles_from_samples,
)
from app.models.montecarlo import McBootstrap, McGbm, fan_and_touch


def prices(n=900, seed=1, phi=0.0, garch=True, drift=0.0004):
    """Synthetic daily OHLCV. garch=True gives volatility clustering; phi adds AR(1) memory to returns."""
    rng = np.random.default_rng(seed)
    r, sig = np.zeros(n), np.full(n, 0.01)
    for t in range(1, n):
        sig[t] = math.sqrt(2e-6 + 0.08 * r[t - 1] ** 2 + 0.9 * sig[t - 1] ** 2) if garch else 0.01
        r[t] = drift + phi * r[t - 1] + sig[t] * rng.standard_normal()
    c = 100 * np.exp(np.cumsum(r))
    return pd.DataFrame({"open": c, "high": c * 1.003, "low": c * 0.997, "close": c, "volume": 1e6}, index=pd.bdate_range("2019-01-01", periods=n))


@pytest.fixture(scope="module")
def df():
    return prices()


ALL = [n for n, c in reg.MODEL_CLASSES.items() if c.kind in ("statistical", "baseline")]   # ML/deep models: tests/test_ml.py


@pytest.mark.parametrize("name", ALL)
def test_every_model_returns_a_valid_view(name, df):
    v = reg.build(name, fast=True).fit(df).predict(df, 5)
    assert isinstance(v, ModelView) and v.name == name and v.horizon == 5
    assert v.p_up + v.p_flat + v.p_down == pytest.approx(1.0) and min(v.p_up, v.p_flat, v.p_down) >= 0
    q = [v.quantiles[k] for k in ("5", "25", "50", "75", "95")]
    assert q == sorted(q) and q[0] < 0 < q[-1] or name in reg.BASELINES
    assert v.asof == str(df.index[-1].date()) and v.version == f"{name}-v1" and v.vote in ("up", "flat", "down")
    assert v.training_window["n"] == len(df) and v.to_dict()["conviction"] == max(v.p_up, v.p_flat, v.p_down)


@pytest.mark.parametrize("name", ALL)
def test_models_are_deterministic_for_a_seed(name, df):
    a = reg.build(name, fast=True, seed=3).fit(df).predict(df, 5)
    b = reg.build(name, fast=True, seed=3).fit(df).predict(df, 5)
    assert (a.p_up, a.p_down) == pytest.approx((b.p_up, b.p_down), rel=1e-9)
    assert list(a.quantiles.values()) == pytest.approx(list(b.quantiles.values()), rel=1e-6, abs=1e-9)


def test_short_history_is_rejected():
    with pytest.raises(ValueError, match="at least"):
        reg.build("arima").fit(prices(60))
    with pytest.raises(KeyError):
        reg.build("nope")


def test_flat_band_formula_and_directions():
    d = prices(300)
    sig = np.log(d.close).diff().dropna().iloc[-60:].std(ddof=1)
    assert daily_sigma(d.close) == pytest.approx(sig) and flat_band(d.close, 5) == pytest.approx(FLAT_K * sig * math.sqrt(5))
    assert direction(0.02, 0.01) == "up" and direction(-0.02, 0.01) == "down" and direction(0.005, 0.01) == "flat"


def test_probability_helpers_agree():
    rng = np.random.default_rng(0)
    s = rng.normal(0.004, 0.03, 200_000)
    a, b = probs_from_samples(s, 0.01), probs_from_normal(0.004, 0.03, 0.01)
    assert a == pytest.approx(b, abs=0.005) and sum(a) == pytest.approx(1)
    q = quantiles_from_samples(s)
    assert q["50"] == pytest.approx(math.expm1(0.004), abs=0.001) and q["5"] < q["95"]
    assert probs_from_samples(np.array([np.nan]), 0.01) == (1 / 3, 1 / 3, 1 / 3)


def test_baselines_use_training_rates_only(df):
    train = df.iloc[:700]
    br = reg.build("base_rate").fit(train)
    v = br.predict(train, 5)
    assert (v.p_up, v.p_flat, v.p_down) == pytest.approx(tuple(br._rates(5)["base"][k] for k in ("up", "flat", "down")))
    bh = reg.build("buy_hold").fit(train).predict(train, 5)
    assert bh.extras["forced_vote"] == "up"
    ma = reg.build("ma_rule").fit(train)
    cond = ma._rates(5)["cond"]
    above = float(train.close.iloc[-1] > train.close.iloc[-50:].mean())
    assert ma.predict(train, 5).p_up == pytest.approx(cond[above]["up"])
    # changing prices AFTER the training window cannot change a baseline's probabilities
    later = train.copy()
    assert br.predict(later, 5).p_up == v.p_up


def test_arima_recovers_planted_autocorrelation_and_is_near_zero_on_noise():
    ar = prices(1200, seed=2, phi=0.5, garch=False, drift=0.0)
    m = reg.build("arima").fit(ar)
    assert m.order[0] >= 1 and m.fit_params["ar.L1"] == pytest.approx(0.5, abs=0.12)
    noise = reg.build("arima", fast=True).fit(prices(1200, seed=5, phi=0.0, garch=False, drift=0.0))
    assert abs(noise.predict(prices(1200, seed=5, garch=False, drift=0.0), 5).quantiles["50"]) < 0.01


def test_ets_parameters_valid(df):
    m = reg.build("ets").fit(df)
    assert 0 <= m.alpha <= 1 and 0 <= m.phi <= 1.0001
    v = m.predict(df, 21)
    assert v.quantiles["95"] - v.quantiles["5"] > 0


def test_garch_volatility_forecast_tracks_a_volatility_shock():
    d = prices(900, seed=7)
    m = reg.build("garch", fast=True).fit(d)
    calm = m.predict(d, 5).extras["vol_forecast_annualised"]
    shocked = d.copy()
    shocked.iloc[-8:, shocked.columns.get_loc("close")] = d.close.iloc[-9] * np.exp(np.cumsum(np.tile([0.05, -0.045], 4)))
    hot = m.predict(shocked, 5).extras["vol_forecast_annualised"]
    assert hot > calm * 1.3                                              # a recent storm raises the volatility forecast


def test_garch_family_and_vol_cone_shape(df):
    for name in ("garch", "gjr_garch", "egarch"):
        v = reg.build(name, fast=True).fit(df).predict(df, 10)
        cone = v.extras["vol_cone"]
        assert cone["horizons"] == [5, 10, 21, 42, 63] and len(cone["forecast"]) == 5
        for i in range(5):
            assert cone["hist_min"][i] <= cone["hist_p25"][i] <= cone["hist_p50"][i] <= cone["hist_p75"][i] <= cone["hist_max"][i]
        assert 0.02 < v.extras["vol_forecast_annualised"] < 1.5
    assert "gamma[1]" in reg.build("gjr_garch", fast=True).fit(df).params()
    assert "cone" not in reg.build("garch", fast=True).fit(df).predict(df, 5, cone=False).extras


def test_garch_interval_width_matches_realised_volatility():
    d = prices(1500, seed=11, drift=0.0)
    v = reg.build("garch", fast=True).fit(d.iloc[:1000]).predict(d.iloc[:1000], 5)
    width = v.quantiles["95"] - v.quantiles["5"]
    realised = np.log(d.close).diff().dropna().iloc[:1000].std() * math.sqrt(5) * 2 * 1.645
    assert width == pytest.approx(realised, rel=0.5)


def test_monte_carlo_gbm_matches_theory():
    d = prices(600, seed=3, garch=False, drift=0.0)
    m = McGbm(seed=1)
    m.n_sims = 20000
    m.fit(d)
    v = m.predict(d, 21)
    r = np.log(d.close).diff().dropna().iloc[-252:]
    sd_theory = r.std(ddof=1) * math.sqrt(21)
    spread = np.log1p(v.quantiles["95"]) - np.log1p(v.quantiles["5"])
    assert spread == pytest.approx(2 * 1.645 * sd_theory, rel=0.05)
    assert v.quantiles["50"] == pytest.approx(math.expm1(r.mean() * 21), abs=0.004)


def test_fan_chart_properties_and_touch_probabilities():
    d = prices(600, seed=4)
    m = McBootstrap(seed=2)
    m.n_sims = 6000
    m.fit(d)
    last = float(d.close.iloc[-1])
    v = m.predict(d, 21, levels=[last * 1.03, last * 1.15, last * 0.97, last * 0.85])
    f = v.extras["fan"]
    assert len(f["days"]) == 21
    for i in range(21):
        assert f["fan"]["p5"][i] < f["fan"]["p25"][i] < f["fan"]["p50"][i] < f["fan"]["p75"][i] < f["fan"]["p95"][i]
    assert (f["fan"]["p95"][-1] - f["fan"]["p5"][-1]) > (f["fan"]["p95"][0] - f["fan"]["p5"][0]) * 2     # fan widens with time
    t = f["touch"]
    assert t[f"{last * 1.03:g}"]["probability"] > t[f"{last * 1.15:g}"]["probability"]
    assert t[f"{last * 0.97:g}"]["probability"] > t[f"{last * 0.85:g}"]["probability"]
    assert t[f"{last * 1.03:g}"]["direction"] == "above" and t[f"{last * 0.97:g}"]["direction"] == "below"


def test_touch_probability_is_at_least_terminal_probability():
    rng = np.random.default_rng(0)
    paths = np.cumsum(rng.normal(0, 0.01, (4000, 20)), axis=1)
    last = 100.0
    lvl = 105.0
    out = fan_and_touch(last, paths, [lvl])
    terminal = float((last * np.exp(paths[:, -1]) >= lvl).mean())
    assert out["touch"]["105"]["probability"] >= terminal                 # ending above implies having touched it
    assert fan_and_touch(last, paths, [last])["touch"][f"{last:g}"]["probability"] == 1.0


def test_bootstrap_only_uses_observed_returns():
    d = prices(700, seed=6)
    m = McBootstrap(seed=1).fit(d)
    r = np.log(d.close).diff().dropna().iloc[-504:].to_numpy()
    paths = m._paths(r, 10, np.random.default_rng(0))
    steps = np.diff(np.c_[np.zeros(len(paths)), paths], axis=1)
    assert steps.max() <= r.max() + 1e-12 and steps.min() >= r.min() - 1e-12


def regime_series(n=1500, seed=0):
    """Calm +0.1%/day (sd 0.5%) alternating with turbulent -0.15%/day (sd 2%) in 60-day blocks."""
    rng = np.random.default_rng(seed)
    turb = (np.arange(n) // 60) % 2 == 1
    r = np.where(turb, rng.normal(-0.0015, 0.02, n), rng.normal(0.001, 0.005, n))
    c = 100 * np.exp(np.cumsum(r))
    return pd.DataFrame({"open": c, "high": c * 1.003, "low": c * 0.997, "close": c, "volume": 1e6}, index=pd.bdate_range("2018-01-01", periods=n)), turb


def test_hmm_finds_planted_regimes_and_filtering_has_no_hindsight():
    d, turb = regime_series()
    m = reg.build("hmm_regime").fit(d)
    tab = {r["regime"]: r for r in m.regime_table()}
    assert max(r["volatility_annual"] for r in tab.values()) > 2.5 * min(r["volatility_annual"] for r in tab.values())
    assert sum(r["share_of_days"] for r in tab.values()) == pytest.approx(1.0)
    X = np.c_[np.log(d.close).diff().dropna().to_numpy() * 100, np.abs(np.log(d.close).diff().dropna().to_numpy()) * 100]
    full, part = m.filtered(X), m.filtered(X[:900])
    np.testing.assert_allclose(full[:900], part, atol=1e-9)              # probabilities at t ignore everything after t
    assert full.sum(axis=1) == pytest.approx(np.ones(len(full)))
    hi = int(np.argmax([r["volatility_annual"] for r in m.regime_table()]))
    inside_turb = full[turb[1:]][:, hi].mean()
    inside_calm = full[~turb[1:]][:, hi].mean()
    assert inside_turb > 0.7 > 0.3 > inside_calm or inside_turb > inside_calm + 0.4


def test_hmm_view_contents():
    d, _ = regime_series(1200, seed=2)
    v = reg.build("hmm_regime", fast=True).fit(d).predict(d, 10)
    assert set(v.extras["regime_probs"]) == {"bear", "sideways", "bull"} and sum(v.extras["regime_probs"].values()) == pytest.approx(1)
    t = v.extras["timeline"]
    assert len(t["dates"]) == len(t["regime"]) == len(t["prob"]) <= 500 and v.extras["current_regime"] in t["labels"]
    assert all(r["expected_duration_days"] >= 1 for r in v.extras["regime_table"])


def test_sanity_guard_rejects_non_finite_or_absurd_forecasts():
    from app.models.base import ModelError, validate_quantiles
    ok = {"5": -0.03, "25": -0.01, "50": 0.0, "75": 0.01, "95": 0.03}
    validate_quantiles(ok, (0.4, 0.2, 0.4))
    for bad in ({**ok, "95": float("inf")}, {**ok, "5": -1.0}, {**ok, "95": 8.5e6}, {**ok, "50": float("nan")}):
        with pytest.raises(ModelError):
            validate_quantiles(bad, (0.4, 0.2, 0.4))
    with pytest.raises(ModelError):
        validate_quantiles(ok, (float("nan"), 0.2, 0.4))


def test_unstable_egarch_parameters_never_produce_an_absurd_number():
    """Regression: EGARCH simulations used to explode (infinite quantiles). Now every forecast is either sane or rejected."""
    from app.models.base import ModelError
    d = prices(900, seed=7)
    m = reg.build("egarch", fast=True).fit(d)
    wild = m.fit_params.copy()
    wild["alpha[1]"], wild["beta[1]"], wild["omega"] = -0.6, 1.25, -0.5          # explosive log-variance recursion
    m.fit_params = wild
    try:
        v = m.predict(d, 5)
    except ModelError:
        return                                                                   # rejected loudly: acceptable
    q = list(v.quantiles.values())
    assert all(np.isfinite(q)) and max(abs(math.log1p(x)) for x in q) <= 2.0
