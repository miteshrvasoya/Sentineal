"""Machine-learning layer: features, labels, purged CV, tabular models, SHAP, deep models, ensemble."""
import math

import numpy as np
import pandas as pd
import pytest

from app.eval import metrics as mt
from app.eval.purged_cv import PurgedKFold
from app.eval.walkforward import WFConfig, walk_forward
from app.models import ensemble as ens
from app.models import registry as reg
from app.models.base import ModelError
from app.models.ml import ClassWrapper, shrink_to_prior
from app.models.ml_features import (
    PRICE_COLS,
    SENT_COLS,
    band_series,
    build_dataset,
    frac_diff,
    price_features,
    sentiment_coverage,
    sentiment_features,
    triple_barrier_labels,
)
from tests.test_models_stat import prices


def sent_frame(df: pd.DataFrame, horizon: int = 1, informative: bool = True, seed: int = 0) -> pd.DataFrame:
    """Daily sentiment indexed by naive IST date. When informative, today's sentiment leans toward the NEXT move
    (this is test data standing in for news that anticipates price)."""
    rng = np.random.default_rng(seed)
    lc = np.log(df["close"])
    fwd = (lc.shift(-horizon) - lc).fillna(0).to_numpy()
    sig = np.nanstd(fwd) or 1.0
    s = (np.tanh(fwd / sig) * 0.6 if informative else 0.0) + rng.normal(0, 0.25, len(df))
    ist = df.index.tz_convert("Asia/Kolkata").tz_localize(None).normalize() if df.index.tz is not None else df.index
    return pd.DataFrame({"mean_sent": s, "sent_std": 0.2, "n_articles": 3.0, "volume_z": rng.normal(size=len(df)), "pos_ratio": 1.0 + s,
                         "recency_weighted": s * 0.9, "sent_mom": s - s.mean()}, index=ist)


def utc(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out.index = out.index.tz_localize("UTC")
    return out


@pytest.fixture(scope="module")
def noise():
    return utc(prices(900, seed=3))


@pytest.fixture(scope="module")
def momentum():
    return utc(prices(1000, seed=5, phi=0.5, garch=False, drift=0.0))


# ---------------- features and labels ----------------

def test_price_features_are_stationary_causal_and_complete(noise):
    f = price_features(noise)
    assert list(f.columns) == PRICE_COLS and len(f) == len(noise) and not np.isinf(f.to_numpy(float)).any()
    cut = 600
    part = price_features(noise.iloc[:cut])
    np.testing.assert_allclose(f.iloc[:cut].to_numpy(float), part.to_numpy(float), atol=1e-9, equal_nan=True)   # prefix invariance


def test_labels_are_purged_at_the_end_and_use_only_forward_returns(noise):
    h = 5
    ds = build_dataset(noise, h)
    assert ds.index.max() <= noise.index[-1 - h]                          # last h rows have no label window: dropped, never guessed
    t = noise.index.get_loc(ds.index[10])
    expect = math.log(noise.close.iloc[t + h] / noise.close.iloc[t])
    assert ds.ret[10] == pytest.approx(expect)
    band = band_series(noise.close, h).iloc[t]
    assert ds.band[10] == pytest.approx(band) and ds.y[10] == (0 if expect > band else 2 if expect < -band else 1)
    assert set(np.unique(ds.y)) <= {0, 1, 2}


def test_training_rows_never_depend_on_data_after_the_cut(noise):
    """Fitting on data up to day T must give the same labelled rows whether or not later prices exist."""
    T, h = 700, 5
    full, trunc = build_dataset(noise, h), build_dataset(noise.iloc[:T + 1], h)
    keep = full.index <= noise.index[T - h]
    assert list(trunc.index) == list(full.index[keep])
    np.testing.assert_allclose(trunc.X.to_numpy(float), full.X[keep].to_numpy(float), equal_nan=True)
    assert (trunc.y == full.y[keep]).all()


def test_sentiment_alignment_keeps_gaps_as_nan(noise):
    sf = sent_frame(utc(prices(300, seed=1)).iloc[:300])
    dropped = sf.drop(sf.index[10:20])
    idx = utc(prices(300, seed=1)).index
    al = sentiment_features(dropped, idx)
    assert list(al.columns) == SENT_COLS and al.iloc[10:20].isna().all().all() and al.iloc[20:].notna().all().all()   # no filling
    assert sentiment_features(None, idx).isna().all().all()
    cov = sentiment_coverage(dropped.assign(n_articles=[0] * 5 + [2] * (len(dropped) - 5)))
    assert cov["days_with_news"] == len(dropped) - 5


# ---------------- optional advanced tools ----------------

def test_triple_barrier_hand_cases():
    rng = np.random.default_rng(0)
    base = 100 * np.exp(np.cumsum(rng.normal(0, 0.01, 120)))
    c = pd.Series(base, index=pd.bdate_range("2024-01-01", periods=120))
    c.iloc[81:] = c.iloc[80] * 1.12                                       # a 12% jump right after day 80
    lab = triple_barrier_labels(c, horizon=5)
    assert lab.iloc[80] == 1.0 and lab.iloc[-5:].isna().all() and lab.iloc[:60].isna().all()
    dn = c.copy()
    dn.iloc[81:] = dn.iloc[80] * 0.88
    assert triple_barrier_labels(dn, horizon=5).iloc[80] == -1.0
    flat = pd.Series(100 * np.exp(np.cumsum(np.r_[rng.normal(0, 0.01, 70), np.zeros(50)])), index=c.index)
    assert triple_barrier_labels(flat, horizon=5).iloc[100] == 0.0       # no barrier touched: the time barrier decides


def test_fractional_differentiation():
    rng = np.random.default_rng(1)
    s = pd.Series(np.cumsum(rng.normal(0, 1, 800)) + 50, index=pd.bdate_range("2020-01-01", periods=800))
    assert np.allclose(frac_diff(s, 1.0).dropna(), s.diff().dropna())     # d = 1 is the ordinary difference
    assert np.allclose(frac_diff(s, 0.0).dropna(), s.loc[frac_diff(s, 0.0).dropna().index])
    fd = frac_diff(s, 0.4)
    np.testing.assert_allclose(fd.iloc[:600].dropna(), frac_diff(s.iloc[:600], 0.4).dropna())      # causal
    from statsmodels.tsa.stattools import adfuller
    assert adfuller(fd.dropna())[1] < adfuller(s)[1]                      # closer to stationary than the raw random walk


# ---------------- purged and embargoed K-fold ----------------

def test_purged_kfold_geometry_and_no_overlap():
    n, h, emb = 500, 10, 7
    cv = PurgedKFold(5, horizon=h, embargo=emb)
    folds = list(cv.split(n))
    assert len(folds) == 5 == cv.get_n_splits()
    all_test = np.concatenate([te for _, te in folds])
    assert sorted(all_test) == list(range(n))                             # every row is tested exactly once
    for tr, te in folds:
        lo, hi = te.min(), te.max() + 1
        assert (np.diff(te) == 1).all()                                   # test blocks are contiguous in time
        assert not set(tr) & set(te)
        assert not any(lo <= t + h and t < lo for t in tr)                # purge: no train label window reaches into the test block
        assert not any(hi <= t < hi + emb for t in tr)                    # embargo after the block
        assert (tr[tr < lo].max() + h < lo) if (tr < lo).any() else True
    assert len(folds[2][0]) < n - len(folds[2][1])                        # purging/embargo really removed rows
    frac = list(PurgedKFold(4, horizon=5, embargo=0.02).split(400))
    assert all(len(tr) > 0 for tr, _ in frac)
    with pytest.raises(ValueError):
        PurgedKFold(1)
    with pytest.raises(ValueError):
        list(PurgedKFold(5).split(6))


# ---------------- helpers ----------------

def test_shrink_to_prior_math():
    p = np.array([[0.7, 0.2, 0.1], [0.1, 0.1, 0.8]])
    prior = np.array([0.4, 0.2, 0.4])
    assert np.allclose(shrink_to_prior(p, prior, 0.0), p) and np.allclose(shrink_to_prior(p, prior, 1.0), np.tile(prior, (2, 1)))
    mid = shrink_to_prior(p, prior, 0.25)
    assert np.allclose(mid.sum(axis=1), 1.0) and np.allclose(mid[0], 0.75 * p[0] + 0.25 * prior)


def test_class_wrapper_handles_a_missing_class():
    import xgboost as xgb
    rng = np.random.default_rng(0)
    X = rng.normal(size=(200, 4))
    y = np.where(X[:, 0] > 0, 0, 2)                                       # no "flat" rows at all
    w = ClassWrapper(xgb.XGBClassifier(n_estimators=20, max_depth=2, tree_method="hist")).fit(X, y)
    p = w.proba(X[:5])
    assert p.shape == (5, 3) and np.allclose(p.sum(axis=1), 1.0) and (p[:, 1] < 0.01).all()      # unseen class: very unlikely, not impossible
    assert (p[X[:5, 0] > 0.5, 0] > 0.5).all()


# ---------------- the tabular models ----------------

TABULAR = ["lgbm", "xgb", "rf", "logit"]


@pytest.mark.parametrize("name", TABULAR)
def test_tabular_models_produce_valid_views(name, noise):
    m = reg.build(name, fast=True, horizon=5).fit(noise.iloc[:800])
    v = m.predict(noise.iloc[:800], 5)
    assert v.p_up + v.p_flat + v.p_down == pytest.approx(1.0) and min(v.p_up, v.p_flat, v.p_down) >= 0
    q = [v.quantiles[k] for k in ("5", "25", "50", "75", "95")]
    assert q == sorted(q) and q[0] < q[-1] and v.kind == "ml" and v.vote in ("up", "flat", "down")
    cal = v.extras["calibration"]
    assert 0 <= cal["trust_in_model"] <= 1 and cal["calibrated"] <= cal["raw"] + 1e-9           # calibration never makes held-out loss worse
    assert cal["calibrated"] <= cal["base_rate_loss"] + 1e-9                                      # and never worse than the base rate it can fall back to
    assert v.training_window["labelled_rows"] > 150 and v.drivers


@pytest.mark.parametrize("name", TABULAR)
def test_tabular_models_are_deterministic(name, noise):
    a = reg.build(name, fast=True, seed=2, horizon=5).fit(noise.iloc[:800]).predict(noise.iloc[:800], 5, detail=False)
    b = reg.build(name, fast=True, seed=2, horizon=5).fit(noise.iloc[:800]).predict(noise.iloc[:800], 5, detail=False)
    assert (a.p_up, a.p_flat, a.p_down) == pytest.approx((b.p_up, b.p_flat, b.p_down), abs=1e-9)
    assert list(a.quantiles.values()) == pytest.approx(list(b.quantiles.values()), abs=1e-9)


def test_models_refuse_wrong_horizon_and_too_little_data(noise):
    m = reg.build("lgbm", fast=True, horizon=5).fit(noise.iloc[:800])
    with pytest.raises(ModelError, match="5-day horizon"):
        m.predict(noise.iloc[:800], 21)
    with pytest.raises(ValueError, match="at least"):                                 # base-class check: <120 bars
        reg.build("lgbm", fast=True, horizon=5).fit(noise.iloc[:80])
    with pytest.raises(ModelError, match="labelled rows"):
        reg.build("lgbm", fast=True, horizon=5).fit(noise.iloc[:200])


def test_noise_earns_little_trust_but_real_signal_earns_a_lot(noise, momentum):
    trust_noise = [reg.build(n, fast=True, horizon=1).fit(noise.iloc[:800]).val_loss["trust_in_model"] for n in ("lgbm", "xgb", "rf", "logit")]
    trust_signal = [reg.build(n, fast=True, horizon=1).fit(momentum.iloc[:900]).val_loss["trust_in_model"] for n in ("lgbm", "xgb", "logit")]
    assert max(trust_noise) <= 0.1                                                     # a model with nothing to learn falls back to the base rate
    assert min(trust_signal) >= 0.2 and np.mean(trust_signal) >= 0.3                   # one with a real signal earns real (but cautious) trust
    assert min(trust_signal) > max(trust_noise) + 0.15


def test_walk_forward_ml_has_no_lookahead_when_the_future_changes():
    d = utc(prices(640, seed=8))
    T = 540
    d2 = d.copy()
    d2.iloc[T + 1:, d2.columns.get_loc("close")] *= np.exp(np.random.default_rng(0).normal(0, 0.04, len(d2) - T - 1).cumsum())
    cfg = WFConfig(horizon=5, min_train=300, refit_every=63)
    for name in ("lgbm", "logit"):
        a = walk_forward(lambda n=name: reg.build(n, fast=True, horizon=5), d, cfg)
        b = walk_forward(lambda n=name: reg.build(n, fast=True, horizon=5), d2, cfg)
        same = a.index[a.index <= d.index[T]]
        assert len(same) > 20
        np.testing.assert_allclose(a.loc[same, ["p_up", "p_flat", "p_down"]].to_numpy(), b.loc[same, ["p_up", "p_flat", "p_down"]].to_numpy(), atol=1e-9)


def test_planted_signal_is_detected_by_the_walk_forward_test(momentum):
    cfg = WFConfig(horizon=1, min_train=400, refit_every=126, max_origins=200)
    pr = {n: walk_forward(lambda n=n: reg.build(n, fast=True, horizon=1), momentum, cfg) for n in ("lgbm", "logit", "base_rate")}
    ev = {n: mt.evaluate(pr[n], pr["base_rate"], is_baseline=n == "base_rate") for n in pr}
    mt.finalize_verdicts(ev, {"base_rate"})
    assert ev["logit"]["brier_skill"] > 0.03 and ev["logit"]["rank_ic"]["ic"] > 0.2 and ev["lgbm"]["brier_skill"] > 0
    assert "equity" in ev["logit"] and ev["logit"]["equity"]["note"].startswith("Diagnostic only") and len(ev["logit"]["brier_series"]) == len(pr["logit"])


def test_noise_is_not_called_an_edge_for_ml_models(noise):
    cfg = WFConfig(horizon=5, min_train=400, refit_every=126, max_origins=60)
    names = ["lgbm", "xgb", "rf", "logit", "base_rate"]
    pr = {n: walk_forward(lambda n=n: reg.build(n, fast=True, horizon=5), noise, cfg) for n in names}
    ev = {n: mt.evaluate(pr[n], pr["base_rate"], is_baseline=n == "base_rate") for n in names}
    mt.finalize_verdicts(ev, {"base_rate"})
    assert all(ev[n]["verdict"] != "demonstrated edge" for n in names)


# ---------------- interpretation: SHAP, permutation importance, partial dependence ----------------

def test_shap_is_additive_and_global_importance_finds_the_driver(momentum):
    from app.models.ml import shap_values
    m = reg.build("lgbm", fast=True, horizon=1).fit(momentum.iloc[:900])
    v = m.predict(momentum.iloc[:900], 1)
    row = m.Xv.iloc[[-1]]
    sv = shap_values(m, m.clf, row)[0]                                                # (features, 3)
    import shap
    ev = shap.TreeExplainer(m.clf.model).expected_value
    raw = m.clf.model.predict_proba(row, raw_score=True)[0]
    present = m.clf.present
    for k, c in enumerate(present):
        assert ev[k] + sv[:, c].sum() == pytest.approx(raw[k], abs=1e-4)              # SHAP values add up to the model's own output
    top = [d["feature"] for d in v.extras["shap_global"][:6]]
    assert "ret_1d" in top and all(d["mean_abs_shap"] >= 0 for d in v.extras["shap_global"])
    assert len(v.extras["shap_now"]) == 10 and v.extras["shap_note"]
    assert all(set(d) >= {"feature", "toward_up", "toward_down"} for d in v.extras["shap_now"])


def test_permutation_importance_and_partial_dependence(momentum):
    m = reg.build("logit", fast=True, horizon=1).fit(momentum.iloc[:900])
    v = m.predict(momentum.iloc[:900], 1)
    pi = v.extras["permutation_importance"]
    assert pi[0]["feature"] in ("ret_1d", "roc", "zscore_20", "connors_rsi", "rsi", "stoch_k", "williams_r", "cci", "bb_pctb", "tsi", "stoch_rsi", "macd_hist_pct") and pi[0]["importance"] > 0
    assert [d["importance"] for d in pi] == sorted((d["importance"] for d in pi), reverse=True)
    pd_ = {d["feature"]: d for d in v.extras["partial_dependence"]}
    assert len(pd_) >= 1
    for d in pd_.values():
        assert len(d["grid"]) == len(d["p_up"]) >= 3 and all(0 <= x <= 1 for x in d["p_up"])
    r1 = m.partial_dependence(["ret_1d"])[0]
    assert r1["p_up"][-1] > r1["p_up"][0] + 0.1                                       # strong momentum: higher yesterday-return, higher P(up)


# ---------------- sentiment models and the ablation ----------------

def test_sentiment_models_need_news_and_use_it_when_present(momentum):
    d = momentum.iloc[:900]
    with pytest.raises(ModelError):
        reg.build("lgbm_sentiment", fast=True, horizon=1).fit(d)                     # no aux: refuses instead of guessing
    aux = {"sentiment": sent_frame(d, horizon=1, informative=True)}
    sm = reg.build("lgbm_sentiment", fast=True, horizon=1, aux=aux).fit(d)
    cm = reg.build("lgbm_combined", fast=True, horizon=1, aux=aux).fit(d)
    assert set(sm.features) == set(SENT_COLS) and set(cm.features) == set(PRICE_COLS) | set(SENT_COLS)
    assert sm.val_loss["trust_in_model"] >= 0.6                                        # informative news is learnable
    # random news must not be trusted (checked over several seeds: a single small validation set can be fooled by luck,
    # which is exactly what the one-standard-error rule guards against)
    useless = [reg.build("lgbm_sentiment", fast=True, horizon=1, aux={"sentiment": sent_frame(d, horizon=1, informative=False, seed=k)}).fit(d)
               .val_loss["trust_in_model"] for k in range(3)]
    assert np.mean(useless) <= 0.2 and max(useless) <= 0.4


def test_registry_availability_metadata():
    cat = {c["name"]: c for c in reg.catalogue()}
    assert cat["lgbm"]["group"] == "machine learning" and cat["lgbm_sentiment"]["needs"] == "sentiment" and cat["deep_gru_pooled"]["needs"] == "pool"
    assert cat["deep_gru"]["experimental"] and cat["ensemble"]["kind"] == "ensemble" and cat["arima"]["available"]
    with pytest.raises(KeyError):
        reg.build("nope")


# ---------------- deep models ----------------

def test_deep_models_fit_predict_and_are_deterministic(noise):
    pytest.importorskip("torch", reason="deep models need `uv sync --extra deep`")
    d = noise.iloc[:700]
    a = reg.build("deep_gru", fast=True, seed=1, horizon=5).fit(d).predict(d, 5)
    b = reg.build("deep_gru", fast=True, seed=1, horizon=5).fit(d).predict(d, 5)
    assert a.p_up + a.p_flat + a.p_down == pytest.approx(1.0) and a.kind == "deep" and "EXPERIMENTAL" in a.notes[0]
    assert (a.p_up, a.p_down) == pytest.approx((b.p_up, b.p_down), abs=1e-5)
    q = [a.quantiles[k] for k in ("5", "25", "50", "75", "95")]
    assert q == sorted(q)
    lstm = reg.build("deep_lstm", fast=True, horizon=5).fit(d).predict(d, 5)
    assert lstm.name == "deep_lstm" and 0 <= lstm.extras["calibration"]["trust_in_model"] <= 1


def test_pooled_deep_model_never_sees_other_stocks_future(noise):
    pytest.importorskip("torch", reason="deep models need `uv sync --extra deep`")
    d = noise.iloc[:700]
    other = utc(prices(900, seed=11))
    cut = d.index[-1]
    other2 = other.copy()
    other2.loc[other2.index > cut, "close"] *= np.exp(np.random.default_rng(1).normal(0, 0.3, (other2.index > cut).sum()).cumsum())
    a = reg.build("deep_gru_pooled", fast=True, seed=1, horizon=5, aux={"pool": {"B": other}}).fit(d).predict(d, 5)
    b = reg.build("deep_gru_pooled", fast=True, seed=1, horizon=5, aux={"pool": {"B": other2}}).fit(d).predict(d, 5)
    assert (a.p_up, a.p_flat, a.p_down) == pytest.approx((b.p_up, b.p_flat, b.p_down), abs=1e-6)     # data after the cut cannot matter
    solo = reg.build("deep_gru_pooled", fast=True, seed=1, horizon=5, aux={"pool": {}}).fit(d)
    assert any(x["name"].startswith("extra rows") for x in a.drivers) and a.drivers[-1]["value"] > 0 and solo._pool_rows == 0


def test_deep_models_report_unavailable_without_torch(monkeypatch, noise):
    import app.models.deep as deep
    monkeypatch.setattr(deep, "torch_available", lambda: (False, "PyTorch is not installed"))
    ok, why = deep.DeepGru.availability()
    assert not ok and "PyTorch" in why
    cat = {c["name"]: c for c in reg.catalogue()}
    assert cat["deep_gru"]["available"] is False and cat["deep_gru"]["unavailable_reason"]
    with pytest.raises(ModelError, match="PyTorch"):
        reg.build("deep_gru", fast=True, horizon=5).fit(noise.iloc[:700])


# ---------------- ensemble ----------------

def fake_preds(n=60, seed=0, skill=(0.0, 0.0)):
    """Two components with controllable quality on the same origins."""
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2024-01-01", periods=n)
    lab = rng.choice(["up", "flat", "down"], size=n, p=[0.4, 0.2, 0.4])
    out = {}
    for name, sk in zip(("a", "b"), skill, strict=True):
        P = np.tile([0.4, 0.2, 0.4], (n, 1)).astype(float)
        for i, l in enumerate(lab):
            P[i, ["up", "flat", "down"].index(l)] += sk
        P /= P.sum(axis=1, keepdims=True)
        d = pd.DataFrame(P, columns=["p_up", "p_flat", "p_down"], index=idx)
        d["actual"], d["band"], d["label"] = 0.0, 0.01, lab
        d["vote"] = d[["p_up", "p_flat", "p_down"]].idxmax(axis=1).str[2:]
        for q, v in zip((5, 25, 50, 75, 95), (-0.04, -0.01, 0.0, 0.01, 0.04), strict=True):
            d[f"q{q}"] = v * (1 + (0.0 if name == "a" else 1.0))
        d.attrs.update(horizon=5, stride=5, failures=0, mode="expanding")
        out[name] = d
    return out


def test_weights_favour_the_lower_loss_model():
    w = ens.weights_from_losses({"good": 0.55, "bad": 0.65})
    assert sum(w.values()) == pytest.approx(1.0) and w["good"] > w["bad"] and w["bad"] == pytest.approx(math.exp(-0.1 / ens.TAU) * w["good"])
    eq = ens.weights_from_losses({"x": 0.6, "y": 0.6})
    assert eq["x"] == pytest.approx(0.5) and ens.weights_from_losses({}) == {}
    assert ens.weights_from_losses({"x": 0.6, "y": 0.9}, tau=0.001)["x"] > 0.999


def test_ensemble_probabilities_and_weights_follow_performance():
    preds = fake_preds(skill=(0.5, 0.0))                                  # model a knows the answer, b does not
    e = ens.combine_walkforward(preds, horizon=5, stride=5)
    assert e.attrs["weights_last"]["a"] > 0.9 and np.allclose(e[["p_up", "p_flat", "p_down"]].sum(axis=1), 1.0)
    first = np.mean([preds["a"]["p_up"].iloc[0], preds["b"]["p_up"].iloc[0]])
    assert e["p_up"].iloc[0] == pytest.approx(first)                       # no resolved history yet: plain equal-weight average
    assert e["q95"].iloc[-1] > 0.04 and e["q95"].iloc[-1] < 0.08          # quantiles are a weighted blend of 0.04 and 0.08
    cur = ens.current_weights(preds, 5, 5)
    assert cur["a"] > 0.9 and sum(cur.values()) == pytest.approx(1.0)


def test_ensemble_weights_are_causal():
    """Corrupting a model's forecasts from origin k onward must not change ANY ensemble weight used before k."""
    k = 35
    base = fake_preds(skill=(0.3, 0.3))
    changed = {n: d.copy() for n, d in base.items()}
    changed["b"].iloc[k:, changed["b"].columns.get_loc("p_up")] = 0.01
    changed["b"].iloc[k:, changed["b"].columns.get_loc("p_down")] = 0.01
    changed["b"].iloc[k:, changed["b"].columns.get_loc("p_flat")] = 0.98
    a, b = ens.combine_walkforward(base, 5, 5), ens.combine_walkforward(changed, 5, 5)
    # an ensemble row i mixes component rows i with weights from rows < i, so rows before k are untouched
    pd.testing.assert_frame_equal(a.iloc[:k][["p_up", "p_flat", "p_down"]], b.iloc[:k][["p_up", "p_flat", "p_down"]])
    assert not np.allclose(a.iloc[k:][["p_up"]].to_numpy(), b.iloc[k:][["p_up"]].to_numpy())


def test_combine_views_blends_probabilities_and_quantiles(noise):
    d = noise.iloc[:800]
    va = reg.build("base_rate").fit(d).predict(d, 5)
    vb = reg.build("ma_rule").fit(d).predict(d, 5)
    ev = ens.combine_views({"base_rate": va, "ma_rule": vb}, {"base_rate": 3.0, "ma_rule": 1.0}, 5)
    assert ev.name == "ensemble" and ev.kind == "ensemble" and ev.extras["weights"]["base_rate"] == pytest.approx(0.75)
    assert ev.p_up == pytest.approx(0.75 * va.p_up + 0.25 * vb.p_up) and ev.p_up + ev.p_flat + ev.p_down == pytest.approx(1.0)
    assert ev.quantiles["50"] == pytest.approx(0.75 * va.quantiles["50"] + 0.25 * vb.quantiles["50"])


# ---------------- metrics additions ----------------

def test_equity_curve_hand_computed():
    idx = pd.bdate_range("2024-01-01", periods=3)
    d = pd.DataFrame({"p_up": [0.6, 0.2, 0.6], "p_flat": [0.1, 0.1, 0.1], "p_down": [0.3, 0.7, 0.3], "label": ["up", "down", "up"],
                      "actual": [math.log(1.10), math.log(0.80), math.log(1.05)], "vote": ["up", "down", "up"]}, index=idx)
    for q in (5, 25, 50, 75, 95):
        d[f"q{q}"] = 0.0
    d["band"] = 0.01
    d.attrs.update(horizon=1, stride=1, failures=0, mode="expanding")
    eq = mt.evaluate(d)["equity"]
    assert [round(x["v"], 3) for x in eq["series"]] == [110.0, 110.0, 115.5]            # long, cash while it said down, long again
    assert [round(x["v"], 3) for x in eq["buy_hold"]] == [110.0, 88.0, 92.4] and eq["exposure"] == pytest.approx(2 / 3)
    assert eq["total_return"] == pytest.approx(0.155) and eq["buy_hold_return"] == pytest.approx(-0.076)


def test_linear_models_stay_sane_when_a_feature_is_extreme(noise):
    """A stock that suddenly moves 10x puts features far outside anything seen in training. Linear models must not extrapolate to
    absurd forecasts (standardised features are clipped to +/-5 sigma)."""
    d = noise.iloc[:800]
    m = reg.build("logit", fast=True, horizon=5).fit(d)
    wild = d.copy()
    wild.iloc[-3:, wild.columns.get_loc("close")] = d["close"].iloc[-4] * np.array([1.8, 4.0, 10.0])
    wild[["open", "high", "low"]] = wild[["close"]].to_numpy().repeat(3, axis=1)
    v = m.predict(wild, 5, detail=False)
    q = list(v.quantiles.values())
    assert all(np.isfinite(q)) and max(abs(math.log1p(x)) for x in q) <= 2.0 and v.p_up + v.p_flat + v.p_down == pytest.approx(1.0)


def test_one_standard_error_rule_prefers_the_simpler_model_when_gain_is_noise():
    from app.models.ml import choose_shrink
    rng = np.random.default_rng(0)
    y = rng.choice(3, size=150, p=[0.4, 0.2, 0.4])
    prior = np.array([0.4, 0.2, 0.4])
    noisy = np.clip(prior + rng.normal(0, 0.05, (150, 3)), 0.05, None)
    noisy /= noisy.sum(axis=1, keepdims=True)
    lam, losses = choose_shrink(y, noisy, prior)
    assert lam >= 0.8 and len(losses) == 11                                  # a model that is just the prior plus jitter: fall back to the base rate
    good = np.full((150, 3), 0.05)
    good[np.arange(150), y] = 0.90                                          # a model that is right: keep its trust
    assert choose_shrink(y, good, prior)[0] <= 0.2
