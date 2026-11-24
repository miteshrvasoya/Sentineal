"""Seasonality, pairs, consensus, registry, jobs, run planning and the Phase 7 API."""
import json

import numpy as np
import pandas as pd
import pytest

from app.data import db as dbmod
from app.data import jobs
from app.data.models import JobRecord
from app.eval.runner import plan_config, run_models
from app.models import consensus as cons
from app.models import pairs as pr
from app.models import registry as reg
from app.models import seasonality as sn
from tests.llm.fakes import session_ctx
from tests.test_models_stat import prices


def series(n, seed, mondays=0.0, cycle=0.0):
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2016-01-04", periods=n)
    r = rng.normal(0.0003, 0.01, n) + np.where(idx.day_of_week == 0, mondays, 0.0) + cycle * np.sin(2 * np.pi * np.arange(n) / 21)
    return pd.Series(100 * np.exp(np.cumsum(r)), index=idx)


# ---------------- seasonality ----------------

def test_planted_monday_effect_is_significant_and_others_are_not():
    out = sn.analyse(series(2500, 1, mondays=0.006))
    rows = {r["group"]: r for r in out["day_of_week"]["rows"]}
    assert rows["Mon"]["significant"] and rows["Mon"]["p_bonferroni"] < 0.05 and rows["Mon"]["mean_pct"] > 0.5
    assert not any(rows[d]["significant"] for d in ("Tue", "Wed", "Thu", "Fri")) and out["day_of_week"]["kruskal_p"] < 0.01


def test_no_calendar_effect_in_random_data():
    for seed in (2, 3):
        out = sn.analyse(series(2500, seed))
        assert not out["day_of_week"]["any_significant"] and not out["month"]["any_significant"]


def test_stl_detects_a_repeating_cycle_and_not_a_random_walk():
    strong = sn.stl_decomposition(series(800, 4, cycle=0.01))
    weak = sn.stl_decomposition(series(800, 5))
    assert strong["seasonal_strength"] > 0.5 > weak["seasonal_strength"] + 0.1 and strong["period"] == 21
    assert len(strong["dates"]) == len(strong["seasonal_pct"]) == 500


# ---------------- pairs ----------------

def cointegrated(n=900, phi=0.9, seed=1, split_break=False):
    rng = np.random.default_rng(seed)
    x = np.cumsum(rng.normal(0, 0.01, n)) + 4.0
    noise = np.zeros(n)
    for t in range(1, n):
        noise[t] = phi * noise[t - 1] + rng.normal(0, 0.01)
    y = 0.8 * x + noise + 1.0
    idx = pd.bdate_range("2018-01-01", periods=n)
    return pd.Series(np.exp(y), index=idx), pd.Series(np.exp(x), index=idx)


def test_pairs_finds_a_planted_cointegrated_pair_and_a_sensible_half_life():
    y, x = cointegrated()
    rng = np.random.default_rng(7)
    indep = pd.Series(np.exp(np.cumsum(rng.normal(0, 0.012, len(y))) + 4), index=y.index)
    out = pr.analyse("Y", {"Y": y, "X": x, "R": indep})
    byp = {r["peer"]: r for r in out["peers"]}
    assert byp["X"]["p"] < 0.01 and byp["X"]["candidate"] and byp["X"]["stable"]
    assert byp["X"]["hedge_ratio"] == pytest.approx(0.8, abs=0.1)
    assert byp["X"]["half_life_days"] == pytest.approx(-np.log(2) / np.log(0.9), rel=0.5)            # ~6.6 days
    assert not byp["R"]["candidate"] and out["best"] == "X" and out["best_spread"]["std"] > 0
    assert out["tested"] == 2 and byp["X"]["p_bonferroni"] == pytest.approx(min(1.0, byp["X"]["p"] * 2))


def test_pairs_skips_short_overlap_and_requires_the_target():
    y, x = cointegrated(200)
    out = pr.analyse("Y", {"Y": y, "X": x})
    assert out["tested"] == 0 and out["peers"][0]["skipped"]
    with pytest.raises(ValueError):
        pr.analyse("Z", {"Y": y})


def test_half_life_formula():
    rng = np.random.default_rng(0)
    s = np.zeros(5000)
    for t in range(1, 5000):
        s[t] = 0.95 * s[t - 1] + rng.normal()
    assert pr.half_life(s) == pytest.approx(-np.log(2) / np.log(0.95), rel=0.25)
    assert pr.half_life(np.cumsum(rng.normal(size=500)) * 0 + 1.0) is None


# ---------------- consensus ----------------

def view(name, p_up, p_down, vote=None, kind="statistical"):
    flat = 1 - p_up - p_down
    v = vote or max((("up", p_up), ("flat", flat), ("down", p_down)), key=lambda x: x[1])[0]
    return {"name": name, "kind": kind, "vote": v, "p_up": p_up, "p_flat": flat, "p_down": p_down, "conviction": max(p_up, flat, p_down),
            "quantiles": {"50": 0.0}}


def test_consensus_agreement_disagreement_and_edge_handling():
    metrics_edge = {"a": {"verdict": "demonstrated edge", "directional": {"hit_rate": 0.6, "naive_rate": 0.5}, "brier_skill": 0.05, "n_effective": 100},
                    "b": {"verdict": "demonstrated edge", "directional": {"hit_rate": 0.58}, "brier_skill": 0.04, "n_effective": 100}}
    agree = cons.build({"a": view("a", 0.6, 0.2), "b": view("b", 0.58, 0.22), "base_rate": view("base_rate", 0.4, 0.4, kind="baseline")},
                       metrics_edge, {"base_rate"})
    assert agree["disagreement"] == "low" and agree["majority"] == "up" and agree["n_edge"] == 2 and agree["conviction"] == "moderate"
    assert agree["n_models"] == 2 and len(agree["baselines"]) == 1 and agree["votes"]["up"] == 2            # baselines do not vote
    split = cons.build({"a": view("a", 0.6, 0.2), "b": view("b", 0.2, 0.6), "c": view("c", 0.55, 0.25)}, {}, set())
    assert split["disagreement"] == "high" and split["conviction"] == "low" and "disagree" in split["headline"]
    noedge = cons.build({"a": view("a", 0.5, 0.3), "b": view("b", 0.5, 0.3)}, {"a": {"verdict": "no demonstrated edge"}, "b": {"verdict": "no demonstrated edge"}}, set())
    assert noedge["n_edge"] == 0 and noedge["conviction"] == "low" and "none has a demonstrated edge" in noedge["headline"]
    assert cons.build({}, {}, set())["headline"] == "No models have been run yet."
    assert "nothing to compare" in cons.build({"a": view("a", 0.5, 0.3)}, {}, set())["headline"]


# ---------------- registry, jobs, planning ----------------

@pytest.fixture
def mem():
    dbmod.init_engine("sqlite:///:memory:")


def test_registry_versions_and_latest(mem):
    d = prices(400, seed=2)
    m = reg.build("base_rate").fit(d)
    with session_ctx() as db:
        v1 = reg.save_run(db, "TCS", m.predict(d, 5), m.params(), None)
        v2 = reg.save_run(db, "TCS", m.predict(d, 5), m.params(), {"verdict": "baseline"})
        other = reg.save_run(db, "INFY", m.predict(d, 5), {}, None)
        assert (v1, v2, other) == (1, 2, 1)
        latest = reg.latest_runs(db, "TCS", 5)
        assert latest["base_rate"].version == 2 and latest["base_rate"].feature_hash == reg.FEATURE_HASH
        assert reg.latest_runs(db, "TCS", 21) == {}
    names = {c["name"] for c in reg.catalogue()}
    assert {"arima", "ets", "garch", "gjr_garch", "egarch", "mc_gbm", "mc_bootstrap", "hmm_regime", "base_rate", "buy_hold", "ma_rule"} == names
    assert all(c["baseline"] == (c["name"] in reg.BASELINES) for c in reg.catalogue())


async def test_job_lifecycle_success_and_failure(mem):
    jid = jobs.create_job(session_ctx, "demo", "X")
    seen = []

    def work(progress):
        progress(0.4)
        seen.append("ran")
        return {"answer": 42}
    await jobs.run_job(session_ctx, jid, work)
    with session_ctx() as db:
        j = jobs.job_dict(db.get(JobRecord, jid))
    assert j["status"] == "done" and j["progress"] == 1.0 and j["result"] == {"answer": 42} and j["error"] is None and seen == ["ran"]
    bad = jobs.create_job(session_ctx, "demo", "X")

    def boom(progress):
        raise RuntimeError("kaput")
    await jobs.run_job(session_ctx, bad, boom)
    with session_ctx() as db:
        jb = jobs.job_dict(db.get(JobRecord, bad))
    assert jb["status"] == "failed" and "kaput" in jb["error"] and jb["result"] is None


def test_plan_config_requires_enough_history():
    cfg, why = plan_config(2000, 5, "expanding", False)
    assert why is None and cfg.min_train == 504 and cfg.refit_every == 63
    assert plan_config(800, 5, "expanding", False)[0].min_train == 504
    cfg2, why2 = plan_config(400, 21, "expanding", False)
    assert cfg2 is None and "Not enough history" in why2 and "21-day" in why2
    assert plan_config(700, 5, "rolling", True)[0].refit_every == 126


def test_run_models_end_to_end(mem):
    d = prices(800, seed=3)
    progress = []
    out = run_models(session_ctx, "TST", d, ["garch", "mc_gbm"], 5, True, "expanding", True, [float(d.close.iloc[-1]) * 1.05], progress.append)
    assert out["evaluated"] and set(out["models"]) == {"garch", "mc_gbm", "base_rate", "buy_hold", "ma_rule"} and out["walk_forward"]["forecasts"] >= 30
    assert progress and progress[-1] <= 0.99 and sorted(progress) == progress
    with session_ctx() as db:
        runs = reg.latest_runs(db, "TST", 5)
        m = json.loads(runs["garch"].metrics)
        assert m["verdict"] in ("demonstrated edge", "no demonstrated edge", "insufficient sample") and json.loads(runs["base_rate"].metrics)["verdict"] == "baseline"
        assert "fan" in json.loads(runs["mc_gbm"].view)["extras"] and "vol_cone" in json.loads(runs["garch"].view)["extras"]
    short = run_models(session_ctx, "TST2", prices(320, seed=3), ["garch"], 21, True, "expanding", True)
    assert short["evaluated"] is False and any("Not enough history" in w for w in short["warnings"])
    with pytest.raises(ValueError, match="at least"):
        run_models(session_ctx, "S", prices(150), ["garch"], 5)
    with pytest.raises(ValueError, match="unknown"):
        run_models(session_ctx, "S", prices(400), ["nope"], 5)


# ---------------- API ----------------

def _store(symbol, n=700, seed=1, **kw):
    from app.data.db import get_session
    from app.data.prices import upsert_prices
    d = prices(n, seed=seed, **kw)
    d = d.assign(adj_close=d.close)
    d.index = d.index.tz_localize("UTC")
    upsert_prices(next(get_session()), symbol, "1d", d, "t")


def test_api_run_analysis_evaluation_registry(client):
    _store("RELIANCE")
    cat = client.get("/models").json()
    assert 5 in cat["horizons"] and any(m["name"] == "arima" for m in cat["models"])
    r = client.post("/models/reliance/run", json={"models": ["garch", "mc_bootstrap"], "horizon": 5, "fast": True, "wait": True,
                                                  "levels": [3000, 2000]})
    assert r.status_code == 202
    job = r.json()
    assert job["status"] == "done" and job["result"]["evaluated"] and job["progress"] == 1.0 and job["symbol"] == "RELIANCE"
    assert client.get(f"/jobs/{job['id']}").json()["status"] == "done" and client.get("/jobs/nope").status_code == 404

    a = client.get("/analysis/RELIANCE?horizon=5").json()
    c = a["consensus"]
    assert {m["name"] for m in c["models"]} == {"garch", "mc_bootstrap"} and {m["name"] for m in c["baselines"]} == {"base_rate", "buy_hold", "ma_rule"}
    assert c["headline"] and set(a["views"]) >= {"garch", "mc_bootstrap", "base_rate"} and a["views"]["garch"]["extras"]["vol_cone"]["horizons"]
    assert a["views"]["mc_bootstrap"]["extras"]["fan"]["touch"] and a["scorecard"]["composite"] is not None and a["versions"]["garch"] == 1

    e = client.get("/models/RELIANCE/evaluation?horizon=5").json()
    rows = {x["model"]: x for x in e["leaderboard"]}
    assert rows["base_rate"]["baseline"] and rows["base_rate"]["verdict"] == "baseline" and rows["garch"]["verdict"] in ("no demonstrated edge", "demonstrated edge")
    assert e["leaderboard"][-1]["baseline"] and "calibration_up" in e["details"]["garch"] and e["period"]["forecasts"] >= 30 and e["notes"]
    reg_rows = client.get("/models/RELIANCE/registry?model=garch").json()
    assert reg_rows[0]["version"] == 1 and reg_rows[0]["feature_hash"] and reg_rows[0]["verdict"]
    client.post("/models/RELIANCE/run", json={"models": ["garch"], "horizon": 5, "fast": True, "wait": True})
    assert client.get("/analysis/RELIANCE?horizon=5").json()["versions"]["garch"] == 2             # retraining writes a new version


def test_api_validation_and_missing_data(client):
    assert client.get("/analysis/NONE?horizon=5").status_code == 404
    assert client.get("/models/NONE/evaluation").status_code == 404
    assert client.post("/models/NONE/run", json={"models": ["garch"]}).status_code == 404            # no stored prices
    _store("TCS", 700)
    run = lambda **kw: client.post("/models/TCS/run", json=kw)  # noqa: E731
    assert run(models=["garch"], horizon=7).status_code == 422
    assert run(models=["nope"]).status_code == 422
    assert run(models=["base_rate"]).status_code == 422                                              # baselines alone are not a model run
    assert run(models=["garch"], mode="sideways").status_code == 422
    _store("TINY", 200)
    assert client.post("/models/TINY/run", json={"models": ["garch"]}).status_code == 422


def test_api_seasonality_and_pairs(client):
    _store("INFY", 900, seed=1)
    _store("WIPRO", 900, seed=2)
    s = client.get("/analysis/seasonality/INFY").json()
    assert len(s["day_of_week"]["rows"]) == 5 and len(s["month"]["rows"]) == 12 and s["stl"]["period"] == 21 and s["notes"]
    p = client.get("/analysis/pairs/INFY?peers=WIPRO").json()
    assert p["tested"] == 1 and p["peers"][0]["peer"] == "WIPRO" and "p_bonferroni" in p["peers"][0] and p["notes"]
    assert client.get("/analysis/pairs/INFY?peers=ZZZ").status_code == 404
    assert client.get("/analysis/seasonality/NONE").status_code == 404
    _store("SHORTY", 100)
    assert client.get("/analysis/seasonality/SHORTY").status_code == 404


def test_run_models_skips_a_model_that_fails_and_reports_why(mem, monkeypatch):
    from app.models.base import Model

    class Boom(Model):
        name = "boom"
        description = "always fails"

        def fit(self, train):
            raise RuntimeError("cannot fit")

        def predict(self, history, horizon, **kw):
            raise AssertionError("unreachable")
    monkeypatch.setitem(reg.MODEL_CLASSES, "boom", Boom)
    out = run_models(session_ctx, "TST", prices(700, seed=3), ["garch", "boom"], 5, True, "expanding", True)
    assert "boom" not in out["models"] and "garch" in out["models"] and out["evaluated"]
    assert any("boom was skipped" in w and "cannot fit" in w for w in out["warnings"])
    with session_ctx() as db:
        assert "boom" not in reg.latest_runs(db, "TST", 5) and "garch" in reg.latest_runs(db, "TST", 5)
