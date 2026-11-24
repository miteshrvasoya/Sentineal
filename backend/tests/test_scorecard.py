import numpy as np
import pandas as pd

from app.data.analysis import scorecard_for
from app.features.pipeline import compute_features
from app.llm.guardrails import contains_advice
from app.models import scorecard as sc


def trending(n=400, drift=0.002, seed=1):
    rng = np.random.default_rng(seed)
    c = 100 * np.cumprod(1 + rng.normal(drift, 0.008, n))
    o = np.concatenate([[c[0]], c[:-1]])
    return pd.DataFrame({"open": o, "high": np.maximum(o, c) * 1.004, "low": np.minimum(o, c) * 0.996, "close": c,
                         "volume": rng.integers(1e5, 1e6, n).astype(float)}, index=pd.bdate_range("2023-01-02", periods=n, tz="UTC"))


def card(df, **kw):
    f = compute_features(df)
    return sc.build(f.iloc[-1], float(df.close.iloc[-1]), obv_series=f["obv"], up_day=bool(df.close.iloc[-1] > df.close.iloc[-2]), **kw)


def test_uptrend_scores_positive_downtrend_negative():
    up, down = card(trending(drift=0.003)), card(trending(drift=-0.003))
    assert up["subscores"]["trend"]["score"] > 50 and down["subscores"]["trend"]["score"] < -50
    assert up["composite"] > down["composite"] and up["label"] == "leaning positive" and down["label"] == "leaning negative"


def test_every_subscore_is_explained_by_rules_that_fired():
    c = card(trending())
    for s in c["subscores"].values():
        for r in s["rules"]:
            assert {"id", "rule", "value", "vote", "why"} <= set(r) and r["vote"] in (-1, 0, 1) and r["why"]
        assert s["fired"] == [r["id"] for r in s["rules"] if r["vote"] != 0]
        if s["rules"]:
            assert s["score"] == round(100 * sum(r["vote"] for r in s["rules"]) / len(s["rules"]))
        else:
            assert s["score"] is None and not s["available"]


def test_missing_data_is_excluded_and_weights_renormalised():
    last = pd.Series({"ema_50": 90.0, "ema_20": 95.0})
    c = sc.build(last, 100.0)
    assert c["subscores"]["trend"]["score"] == 100 and c["composite"] == 100                  # only trend had data
    assert "News sentiment" in c["missing"] and "Valuation & quality" in c["missing"] and c["subscores"]["sentiment"]["score"] is None
    empty = sc.build(pd.Series(dtype=float), 100.0)
    assert empty["composite"] is None and empty["label"] is None


def test_rule_thresholds():
    mixed = sc.build(pd.Series({"ema_50": 90.0, "ema_20": 80.0}), 100.0)                       # one +1, one -1
    assert mixed["subscores"]["trend"]["score"] == 0 and mixed["label"] == "mixed"
    rsi_hi = sc.momentum_rules(pd.Series({"rsi": 80.0}))[0]
    assert rsi_hi["vote"] == 0                                                                  # stretched: abstains
    assert sc.momentum_rules(pd.Series({"rsi": 60.0}))[0]["vote"] == 1 and sc.momentum_rules(pd.Series({"rsi": 40.0}))[0]["vote"] == -1
    adx_weak = [r for r in sc.trend_rules(pd.Series({"adx": 15.0, "plus_di": 30.0, "minus_di": 10.0}), 1.0, None) if r["id"] == "adx_direction"][0]
    assert adx_weak["vote"] == 0                                                                # weak trend: direction ignored
    assert sc.volatility_rules(pd.Series({"ttm_squeeze": 1.0}))[0]["vote"] == 0                 # squeeze has no direction


def test_sentiment_and_valuation_rules():
    s = sc.sentiment_rules({"recency_weighted": 0.4, "sent_mom": -0.1})
    assert [r["vote"] for r in s] == [1, -1] and sc.sentiment_rules(None) == []
    f = {"percentiles": {"pe": {"percentile": 20.0}, "pb": {"percentile": 90.0}}, "piotroski": {"score": 8, "evaluated": 9},
         "altman": {"applicable": True, "zone": "grey", "z": 2.0}, "graham": {"price_vs_graham": -0.2}, "dcf": {"upside_pct": 35.0}}
    votes = {r["id"]: r["vote"] for r in sc.valuation_rules(f)}
    assert votes == {"pe_sector_pct": 1, "pb_sector_pct": -1, "piotroski": 1, "altman": 0, "graham": 1, "dcf": 1}
    assert sc.valuation_rules({"piotroski": {"score": 2, "evaluated": 4}}) == []              # too few evaluated criteria
    assert sc.valuation_rules({"altman": {"applicable": False, "zone": None}}) == []


def test_scorecard_text_never_reads_as_advice():
    c = card(trending(), sentiment={"recency_weighted": 0.5, "sent_mom": 0.1},
             fundamentals={"percentiles": {"pe": {"percentile": 10.0}}, "piotroski": {"score": 9, "evaluated": 9},
                           "altman": {"applicable": True, "zone": "safe", "z": 4}, "graham": {"price_vs_graham": -0.3}, "dcf": {"upside_pct": 50}})
    texts = [c["label"], c["disclaimer"]] + [x for s in c["subscores"].values() for r in s["rules"] for x in (r["rule"], r["why"])]
    assert all(contains_advice(t) == [] for t in texts)
    assert not any(w in " ".join(texts).lower() for w in ("buy", "sell", "bullish", "bearish", "target"))


def test_scorecard_for_needs_enough_history(client):
    from app.data.db import get_session
    from app.data.prices import upsert_prices
    from tests.conftest import make_frame
    db = next(get_session())
    upsert_prices(db, "SHORT", "1d", make_frame(20), "t")
    assert scorecard_for(db, "SHORT") is None and scorecard_for(db, "NOPE") is None
    upsert_prices(db, "LONGER", "1d", make_frame(300), "t")
    out = scorecard_for(db, "LONGER")
    assert out["bars"] == 300 and out["composite"] is not None and "Valuation & quality" in out["missing"]
