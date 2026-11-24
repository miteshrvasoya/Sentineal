"""Walk-forward harness and metrics, checked against hand-computed values and planted signals."""
import math

import numpy as np
import pandas as pd
import pytest
from scipy import stats

from app.eval import metrics as mt
from app.eval.calibration import calibration_curve
from app.eval.walkforward import WFConfig, origins, walk_forward
from app.models import registry as reg
from app.models.base import Model
from tests.test_models_stat import prices


def frame(rows, h=1, stride=1):
    """rows: (p_up, p_flat, p_down, label, actual_log_return, vote)"""
    idx = pd.bdate_range("2024-01-01", periods=len(rows))
    d = pd.DataFrame(rows, columns=["p_up", "p_flat", "p_down", "label", "actual", "vote"], index=idx)
    for q in (5, 25, 50, 75, 95):
        d[f"q{q}"] = 0.0
    d["band"] = 0.01
    d.attrs.update(horizon=h, stride=stride, failures=0, mode="expanding")
    return d


# ---------------- metrics against hand-computed numbers ----------------

def test_brier_hand_computed():
    d = frame([(0.7, 0.2, 0.1, "up", 0.02, "up"), (0.1, 0.2, 0.7, "up", 0.02, "down")])
    b = mt.brier_per_forecast(d)
    assert b[0] == pytest.approx(0.3**2 + 0.2**2 + 0.1**2) and b[1] == pytest.approx(0.9**2 + 0.2**2 + 0.7**2)
    assert mt.brier_per_forecast(frame([(1, 0, 0, "up", 0.02, "up")]))[0] == 0.0


def test_directional_accuracy_and_binomial_tests():
    rows = [(0.6, 0.1, 0.3, "up", 0.02, "up")] * 8 + [(0.6, 0.1, 0.3, "down", -0.02, "up")] * 2 + [(0.4, 0.4, 0.2, "flat", 0.0, "flat")] * 5
    d = mt.directional(frame(rows))
    assert d["n"] == 10 and d["hits"] == 8 and d["hit_rate"] == 0.8 and d["naive_rate"] == 0.8      # flat outcomes ignored
    assert d["p_vs_half"] == pytest.approx(stats.binomtest(8, 10, 0.5).pvalue) and d["p_vs_half"] == pytest.approx(0.1094, abs=1e-3)
    assert d["p_vs_naive"] > 0.5                                                                   # "always up" explains the 80%
    assert mt.directional(frame([(0.3, 0.4, 0.3, "flat", 0.0, "flat")]))["hit_rate"] is None


def test_confusion_precision_recall():
    rows = [(0.5, 0.2, 0.3, "up", 0.02, "up"), (0.5, 0.2, 0.3, "down", -0.02, "up"), (0.2, 0.2, 0.6, "down", -0.02, "down"), (0.2, 0.2, 0.6, "up", 0.02, "down")]
    c = mt.confusion(frame(rows))
    assert c["matrix"] == [[1, 0, 1], [0, 0, 0], [1, 0, 1]] and c["accuracy3"] == 0.5
    assert c["precision"]["up"] == 0.5 and c["recall"]["down"] == 0.5 and c["precision"]["flat"] is None


def test_pinball_and_coverage():
    d = frame([(0.4, 0.2, 0.4, "up", math.log(1.1), "up")])
    for q in (5, 25, 50, 75, 95):
        d[f"q{q}"] = 0.0
    p = mt.pinball(d)
    assert p["mean"] == pytest.approx(0.5 * 0.1) and p["per_quantile"]["50"] == pytest.approx(0.05) and p["coverage_90"] == 0.0
    d2 = frame([(0.4, 0.2, 0.4, "up", 0.0, "up")] * 4)
    d2["q5"], d2["q95"] = -0.1, 0.1
    assert mt.pinball(d2)["coverage_90"] == 1.0


def test_point_errors_and_mase():
    d = frame([(0.4, 0.2, 0.4, "up", 0.02, "up"), (0.4, 0.2, 0.4, "down", -0.04, "down")])
    d["q50"] = [0.02, -0.04]                             # perfect median forecast (in simple return it differs slightly)
    e = mt.point_errors(d)
    assert e["mae_naive"] == pytest.approx(0.03) and e["mase"] < 0.05
    d["q50"] = 0.0
    assert mt.point_errors(d)["mase"] == pytest.approx(1.0)       # forecasting "no change" scores exactly 1


def test_rank_ic():
    rng = np.random.default_rng(0)
    y = rng.normal(0, 0.02, 120)
    d = frame([(0.5 + v * 5, 0.1, 0.4 - v * 5, "up", v, "up") for v in y])
    assert mt.rank_ic(d)["ic"] == pytest.approx(1.0)
    noise = frame([(float(u), 0.1, 0.1, "up", v, "up") for u, v in zip(rng.random(120), y, strict=True)])
    assert abs(mt.rank_ic(noise)["ic"]) < 0.3 and len(mt.rank_ic(noise)["rolling"]) > 0


def test_calibration_curve():
    rng = np.random.default_rng(1)
    p = np.full(1000, 0.2)
    y = (rng.random(1000) < 0.2).astype(float)
    c = calibration_curve(p, y)
    assert c["rows"][0]["mean_pred"] == pytest.approx(0.2) and c["rows"][0]["observed"] == pytest.approx(0.2, abs=0.04) and c["ece"] < 0.05
    bad = calibration_curve(np.full(1000, 0.9), y)
    assert bad["ece"] == pytest.approx(0.7, abs=0.05) and sum(r["n"] for r in bad["rows"]) == 1000


def test_newey_west_and_diebold_mariano():
    rng = np.random.default_rng(2)
    e = rng.normal(size=4000)
    ar = np.zeros(4000)
    for t in range(1, 4000):
        ar[t] = 0.7 * ar[t - 1] + e[t]
    assert mt.newey_west_var(ar, 0) == pytest.approx(np.var(ar), rel=1e-6)
    assert mt.newey_west_var(ar, 10) > 2 * mt.newey_west_var(ar, 0)               # autocorrelation inflates the long-run variance
    base = rng.uniform(0.5, 0.7, 400)
    assert mt.diebold_mariano(base, base, 0)["dm_p"] is None
    better = mt.diebold_mariano(base - 0.05 + rng.normal(0, 0.01, 400), base, 0)
    worse = mt.diebold_mariano(base + 0.05 + rng.normal(0, 0.01, 400), base, 0)
    assert better["dm_p"] < 0.001 and worse["dm_p"] > 0.99


def res(**kw):
    base = {"n_effective": 100.0, "brier_skill": 0.03, "dm_p": 0.03}
    return {**base, **kw}


def test_verdicts_and_bonferroni_correction():
    r1 = {"m": res()}
    mt.finalize_verdicts(r1, set())
    assert r1["m"]["verdict"] == "demonstrated edge" and r1["m"]["p_adjusted"] == pytest.approx(0.03)
    r3 = {"a": res(), "b": res(dm_p=0.9, brier_skill=-0.01), "c": res(dm_p=0.5, brier_skill=0.0), "base_rate": res()}
    mt.finalize_verdicts(r3, {"base_rate"})
    assert r3["a"]["p_adjusted"] == pytest.approx(0.09) and r3["a"]["verdict"] == "no demonstrated edge"   # 3 models tried
    assert r3["base_rate"]["verdict"] == "baseline" and "not statistically significant" in r3["a"]["verdict_reason"]
    assert r3["b"]["verdict"] == "no demonstrated edge" and "Did not beat" in r3["b"]["verdict_reason"]
    small = {"m": res(n_effective=12.0)}
    mt.finalize_verdicts(small, set())
    assert small["m"]["verdict"] == "insufficient sample"
    neg = {"m": res(brier_skill=-0.02, dm_p=0.001)}
    mt.finalize_verdicts(neg, set())
    assert neg["m"]["verdict"] == "no demonstrated edge"                           # significance in the WRONG direction is not an edge


# ---------------- walk-forward harness ----------------

def test_origins_geometry():
    cfg = WFConfig(horizon=5, min_train=300)
    ts = origins(1000, cfg)
    assert ts[0] == 299 and ts[-1] + 5 <= 999 and set(np.diff(ts)) == {5}          # stride = horizon: outcomes never overlap
    assert origins(1000, WFConfig(horizon=5, min_train=300, stride=1))[1] - 299 == 1
    assert len(origins(1000, WFConfig(horizon=5, min_train=300, max_origins=10))) == 10
    assert origins(300, WFConfig(horizon=5, min_train=300)) == []


class Spy(Model):
    """Records what the harness hands it, to prove nothing from the future is visible."""
    name = "spy"
    log: list = []

    def fit(self, train):
        self.last_train = train.index[-1]
        Spy.log.append(("fit", train.index[0], train.index[-1], len(train)))
        self._fitted = True
        return self

    def predict(self, history, horizon, **kw):
        assert self.last_train <= history.index[-1], "model was fitted on data later than the forecast origin"
        Spy.log.append(("predict", history.index[-1]))
        return reg.build("base_rate").fit(history).predict(history, horizon)


def test_harness_fits_only_on_data_up_to_the_origin_and_refits_on_schedule():
    d = prices(700, seed=3)
    Spy.log = []
    cfg = WFConfig(horizon=5, min_train=300, refit_every=60)
    out = walk_forward(lambda: Spy(), d, cfg)
    fits = [e for e in Spy.log if e[0] == "fit"]
    assert len(fits) >= 5 and all(e[1] == d.index[0] for e in fits)                # expanding: always starts at the beginning
    assert [fits[i + 1][2] > fits[i][2] for i in range(len(fits) - 1)] == [True] * (len(fits) - 1)
    pred_dates = [e[1] for e in Spy.log if e[0] == "predict"]
    assert list(out.index) == pred_dates
    # a fit never includes data after the first origin it serves
    first_origin_after = {f[2]: min(p for p in pred_dates if p >= f[2]) for f in fits}
    assert all(k <= v for k, v in first_origin_after.items())
    # rolling window caps the training length
    Spy.log = []
    walk_forward(lambda: Spy(), d, WFConfig(horizon=5, min_train=300, refit_every=60, mode="rolling", window=250))
    assert max(e[3] for e in Spy.log if e[0] == "fit") <= 250


@pytest.mark.parametrize("name", ["arima", "garch", "hmm_regime", "mc_gbm"])
def test_walk_forward_has_no_lookahead_when_future_prices_change(name):
    """Corrupt every price after bar T. Forecasts made at origins up to T must not change at all."""
    d = prices(620, seed=8)
    T = 520
    d2 = d.copy()
    d2.iloc[T + 1:, d2.columns.get_loc("close")] *= np.exp(np.random.default_rng(0).normal(0, 0.2, len(d2) - T - 1).cumsum())
    cfg = WFConfig(horizon=5, min_train=300, refit_every=63, max_origins=None)
    a = walk_forward(lambda: reg.build(name, fast=True), d, cfg)
    b = walk_forward(lambda: reg.build(name, fast=True), d2, cfg)
    same = a.index[a.index <= d.index[T]]
    assert len(same) > 20
    np.testing.assert_allclose(a.loc[same, ["p_up", "p_flat", "p_down"]].to_numpy(), b.loc[same, ["p_up", "p_flat", "p_down"]].to_numpy(), atol=1e-9)
    assert not np.allclose(a["actual"].iloc[-5:], b["actual"].iloc[-5:])            # (the corrupted tail really differs)


def test_walk_forward_outputs_and_errors():
    d = prices(700, seed=4)
    out = walk_forward(lambda: reg.build("base_rate"), d, WFConfig(horizon=5, min_train=300))
    assert {"actual", "band", "p_up", "p_flat", "p_down", "vote", "label", "q5", "q95"} <= set(out.columns)
    assert out.attrs["horizon"] == 5 and out.attrs["stride"] == 5 and set(out["label"]) <= {"up", "flat", "down"}
    t = d.index.get_loc(out.index[3])
    assert out["actual"].iloc[3] == pytest.approx(math.log(d.close.iloc[t + 5] / d.close.iloc[t]))   # outcome = log(close[t+h]/close[t])
    with pytest.raises(ValueError, match="not enough data"):
        walk_forward(lambda: reg.build("base_rate"), d.iloc[:303], WFConfig(horizon=5, min_train=300))
    with pytest.raises(ValueError, match="mode"):
        walk_forward(lambda: reg.build("base_rate"), d, WFConfig(mode="bogus"))

    class Broken(Spy):
        def predict(self, history, horizon, **kw):
            raise RuntimeError("boom")
    with pytest.raises(RuntimeError, match="not usable"):
        walk_forward(lambda: Broken(), d, WFConfig(horizon=5, min_train=300))


# ---------------- end-to-end honesty: planted edge vs pure noise ----------------

def run_eval(df, names, h=5, max_origins=120):
    cfg = WFConfig(horizon=h, min_train=504, refit_every=126, max_origins=max_origins)
    preds = {n: walk_forward(lambda n=n: reg.build(n, fast=True), df, cfg) for n in names}
    out = {n: mt.evaluate(preds[n], preds["base_rate"], is_baseline=n == "base_rate") for n in names}
    mt.finalize_verdicts(out, {"base_rate"})
    return out


def test_a_planted_edge_is_detected():
    d = prices(1400, seed=5, phi=0.45, garch=False, drift=0.0)                    # strong daily momentum: next-day direction is predictable
    out = run_eval(d, ["arima", "base_rate"], h=1, max_origins=250)
    a = out["arima"]
    assert a["brier_skill"] > 0.05 and a["verdict"] == "demonstrated edge" and a["dm_p"] < 0.001
    assert a["directional"]["hit_rate"] > a["directional"]["naive_rate"] + 0.1 and a["rank_ic"]["ic"] > 0.3
    assert a["cum_skill"][-1]["v"] > a["cum_skill"][0]["v"]                       # cumulative skill line trends up


def test_a_faint_weekly_signal_is_not_overclaimed():
    """Even strong daily momentum is hard to confirm at a 5-day horizon with ~120 independent forecasts: the harness
    reports a small positive skill and a positive rank IC, but refuses to call it an edge. (Low statistical power.)"""
    d = prices(1400, seed=5, phi=0.45, garch=False, drift=0.0)
    a = run_eval(d, ["arima", "base_rate"], h=5, max_origins=120)["arima"]
    assert a["rank_ic"]["ic"] > 0.05 and a["brier_skill"] > 0 and a["verdict"] == "no demonstrated edge"


def test_pure_noise_is_not_called_an_edge():
    d = prices(1400, seed=6, phi=0.0, garch=True, drift=0.0)
    out = run_eval(d, ["arima", "garch", "mc_gbm", "mc_bootstrap", "base_rate"])
    assert all(r["verdict"] in ("no demonstrated edge", "baseline") for r in out.values())
    for n in ("garch", "mc_gbm", "mc_bootstrap"):
        assert 0.8 < out[n]["pinball"]["coverage_90"] <= 1.0                          # intervals are honestly wide enough


def test_evaluate_reports_every_section():
    d = prices(1200, seed=9)
    out = run_eval(d, ["garch", "base_rate"])["garch"]
    for k in ("brier", "directional", "confusion", "calibration_up", "pinball", "point", "rank_ic", "rolling_accuracy", "cum_skill",
              "dm_p", "brier_skill", "verdict", "verdict_reason", "n_effective", "class_shares"):
        assert k in out
    assert sum(out["class_shares"].values()) == pytest.approx(1.0)
    assert out["n_effective"] == out["n_forecasts"]                              # stride = horizon: no overlap discount


def test_a_model_with_many_failed_forecasts_cannot_claim_an_edge():
    good = res(failures=0, failure_rate=0.0)
    flaky = res(failures=12, failure_rate=0.2)
    r = {"a": good, "b": flaky, "base_rate": res()}
    mt.finalize_verdicts(r, {"base_rate"})
    assert r["a"]["verdict"] == "no demonstrated edge" or r["a"]["verdict"] == "demonstrated edge"      # p_adj uses 2 models
    solo = {"flaky": flaky}
    mt.finalize_verdicts(solo, set())
    assert solo["flaky"]["verdict"] == "no demonstrated edge" and "cannot be trusted" in solo["flaky"]["verdict_reason"]
    ok = {"fine": res(failures=1, failure_rate=0.02)}
    mt.finalize_verdicts(ok, set())
    assert ok["fine"]["verdict"] == "demonstrated edge"


def test_walk_forward_counts_failures_and_evaluate_reports_rate():
    from app.models.base import ModelError
    d = prices(700, seed=4)

    class Flaky(Spy):
        calls = 0
        def predict(self, history, horizon, **kw):
            Flaky.calls += 1
            if Flaky.calls % 7 == 0:
                raise ModelError("blew up")
            return reg.build("base_rate").fit(history).predict(history, horizon)
    Flaky.calls = 0
    out = walk_forward(lambda: Flaky(), d, WFConfig(horizon=5, min_train=300))
    assert 0 < out.attrs["failures"] < 0.2 * out.attrs["n_origins"] and len(out) == out.attrs["n_origins"] - out.attrs["failures"]
    base = walk_forward(lambda: reg.build("base_rate"), d, WFConfig(horizon=5, min_train=300))
    ev = mt.evaluate(out, base)
    assert ev["failures"] == out.attrs["failures"] and ev["failure_rate"] == pytest.approx(out.attrs["failures"] / out.attrs["n_origins"], rel=0.05)
