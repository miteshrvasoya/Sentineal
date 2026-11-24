"""Phase 9: costs, engine timing and accounting, strategies, bootstrap, luck test, parameter search, API."""
import numpy as np
import pandas as pd
import pytest

from app.backtest import costs as cm
from app.backtest import stats
from app.backtest import strategies as st
from app.backtest.engine import BTConfig, run
from app.backtest.service import backtest


def frame(n=900, seed=0, drift=0.0003, vol=0.012, start="2018-01-01"):
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range(start, periods=n)
    c = 100 * np.exp(np.cumsum(rng.normal(drift, vol, n)))
    o = np.r_[c[0], c[:-1]] * np.exp(rng.normal(0, 0.002, n))
    return pd.DataFrame({"open": o, "high": np.maximum(o, c) * 1.004, "low": np.minimum(o, c) * 0.996, "close": c, "volume": 1e6}, index=idx)


# ---------------- costs ----------------

def test_delivery_costs_match_hand_calculation():
    c = cm.INDIA_DELIVERY.charges("buy", 100_000)
    assert c["stt"] == pytest.approx(100) and c["stamp"] == pytest.approx(15) and c["exchange"] == pytest.approx(2.97) and c["sebi"] == pytest.approx(0.1)
    assert c["gst"] == pytest.approx(0.18 * (0 + 2.97 + 0.1)) and c["dp"] == 0
    s = cm.INDIA_DELIVERY.charges("sell", 100_000)
    assert s["stt"] == pytest.approx(100) and s["stamp"] == 0 and s["dp"] == 15.34
    assert c["total"] == pytest.approx(sum(v for k, v in c.items() if k != "total"))


def test_brokerage_cap_and_overrides_and_validation():
    m = cm.from_overrides("india_delivery", {"brokerage_pct": 0.001, "brokerage_cap": 20})
    assert m.charges("buy", 1_000_000)["brokerage"] == 20 and m.charges("buy", 5_000)["brokerage"] == pytest.approx(5)
    assert all(v == 0 for v in cm.NO_COSTS.charges("sell", 1e6).values())
    for bad in ({"nope": 1}, {"stt_buy": -1}):
        with pytest.raises(ValueError):
            cm.from_overrides("india_delivery", bad)
    with pytest.raises(ValueError):
        cm.from_overrides("zzz", None)


# ---------------- engine ----------------

def test_signal_is_filled_at_the_next_open_not_the_signal_bar():
    d = frame(300)
    sig = np.zeros(len(d), int)
    sig[100:110] = 1                                   # decided at close of bar 100..109
    res = run(d, sig, BTConfig(costs=cm.NO_COSTS, start=0))
    t = res.trades[0]
    assert t["entry_date"] == str(d.index[101].date()) and t["entry_price"] == pytest.approx(d["open"].iloc[101], abs=1e-3)
    assert t["exit_date"] == str(d.index[111].date()) and t["exit_price"] == pytest.approx(d["open"].iloc[111], abs=1e-3)   # signal turns off at close of 110


def test_trades_before_a_point_do_not_depend_on_the_future():
    d = frame(700, seed=1)
    sig, warm = st.get("ma_cross").signal(d)
    a = run(d, sig, BTConfig(start=warm)).trades
    d2 = d.copy()
    d2.iloc[500:, d2.columns.get_loc("close")] *= 3
    d2["high"] = np.maximum(d2["high"], d2["close"])
    d2["open"] = d2["open"].where(d2.index < d2.index[500], d2["close"])
    sig2, _ = st.get("ma_cross").signal(d2)
    b = run(d2, sig2, BTConfig(start=warm)).trades
    cut = str(d.index[498].date())
    assert [t for t in a if t["exit_date"] < cut] == [t for t in b if t["exit_date"] < cut] and a


@pytest.mark.parametrize("name", list(st.STRATEGIES))
def test_strategy_signals_are_prefix_invariant(name):
    d = frame(600, seed=2)
    s = st.get(name)
    full, _ = s.signal(d)
    for k in (300, 450):
        part, _ = s.signal(d.iloc[:k])
        assert np.array_equal(full[:k], part), name


def test_accounting_identity_and_cash_never_negative():
    d = frame(900, seed=3)
    for name in st.STRATEGIES:
        sig, warm = st.get(name).signal(d)
        res = run(d, sig, BTConfig(costs=cm.INDIA_DELIVERY, start=warm, stop_loss=0.1))
        assert res.equity.min() > 0
        assert res.equity.iloc[-1] == pytest.approx(1_000_000 + sum(t["net_pnl"] for t in res.trades), rel=1e-6, abs=1.0)
        assert all(t["costs"] > 0 for t in res.trades)


def test_costs_reduce_final_equity_and_zero_cost_run_has_no_charges():
    d = frame(900, seed=4)
    sig, warm = st.get("rsi_reversion").signal(d)
    a = run(d, sig, BTConfig(costs=cm.INDIA_DELIVERY, start=warm))
    b = run(d, sig, BTConfig(costs=cm.NO_COSTS, start=warm))
    assert a.equity.iloc[-1] < b.equity.iloc[-1] and sum(b.paid.values()) == 0 and b.slippage_paid == 0 and sum(a.paid.values()) > 0


def test_stop_loss_fills_at_the_stop_and_at_the_open_on_a_gap():
    d = frame(120, seed=5, vol=0.0001, drift=0)
    d = d.copy()
    sig = np.zeros(len(d), int)
    sig[20:100] = 1
    entry = d["open"].iloc[21]
    d.iloc[40, d.columns.get_loc("low")] = entry * 0.90                       # intraday dip through a 5% stop
    res = run(d, sig, BTConfig(costs=cm.NO_COSTS, stop_loss=0.05, start=0))
    t = res.trades[0]
    assert t["exit_reason"] == "stop" and t["exit_price"] == pytest.approx(entry * 0.95, rel=1e-6) and t["exit_date"] == str(d.index[40].date())
    gap = d.copy()
    gap.iloc[40, gap.columns.get_loc("open")] = entry * 0.80
    gap.iloc[40, gap.columns.get_loc("low")] = entry * 0.78
    t2 = run(gap, sig, BTConfig(costs=cm.NO_COSTS, stop_loss=0.05, start=0)).trades[0]
    assert t2["exit_price"] == pytest.approx(entry * 0.80, rel=1e-6)         # gapped through the stop: filled at the open, a worse price
    assert len(run(d, sig, BTConfig(costs=cm.NO_COSTS, stop_loss=0.05, start=0)).trades) == 1   # no immediate re-entry while the signal stays on


def test_open_position_is_closed_at_the_end_and_flagged():
    d = frame(200, seed=6)
    sig = np.ones(len(d), int)
    res = run(d, sig, BTConfig(costs=cm.NO_COSTS))
    assert res.trades[-1]["exit_reason"] == "end of test" and res.equity.iloc[-1] == pytest.approx(1_000_000 + res.trades[-1]["net_pnl"], rel=1e-6, abs=1)


def test_position_sizing_never_overspends():
    d = frame(100, seed=7)
    res = run(d, np.ones(len(d), int), BTConfig(capital=50_000, costs=cm.INDIA_DELIVERY))
    t = res.trades[0]
    assert t["qty"] * t["entry_price"] + 0.0 <= 50_000 and t["qty"] > 0


# ---------------- stats ----------------

def test_metrics_hand_checked():
    idx = pd.bdate_range("2020-01-01", periods=5)
    eq = pd.Series([100, 110, 99, 99, 120.0], index=idx)
    m = stats.metrics(eq, [{"net_pnl": 5, "return_pct": .05, "bars": 3}, {"net_pnl": -2, "return_pct": -.02, "bars": 2}], rf=0)
    assert m["total_return"] == pytest.approx(0.2) and m["max_drawdown"] == pytest.approx(-0.1) and m["win_rate"] == 0.5 and m["profit_factor"] == pytest.approx(2.5)


def test_stationary_bootstrap_indices_are_valid_and_block_structured():
    rng = np.random.default_rng(0)
    idx = stats.stationary_bootstrap_indices(500, 50, 10, rng)
    assert idx.shape == (50, 500) and idx.min() >= 0 and idx.max() < 500
    steps = np.diff(idx, axis=1) % 500
    assert 0.8 < (steps == 1).mean() < 0.97                                  # mostly consecutive, a restart about every 10 steps


def test_bootstrap_detects_real_drift_and_not_noise():
    rng = np.random.default_rng(1)
    good = rng.normal(0.002, 0.01, 750)
    noise = rng.normal(0.0, 0.01, 750)
    g, n = stats.bootstrap(good, rf=0.0, reps=1000), stats.bootstrap(noise, rf=0.0, reps=1000)
    assert g["p_value"] < 0.01 and g["sharpe_ci90"][0] > 0
    assert n["p_value"] > 0.05 and n["sharpe_ci90"][0] < 0 < n["sharpe_ci90"][1]
    assert stats.bootstrap(noise, reps=1000, trials=20)["p_adjusted"] == min(1.0, 20 * stats.bootstrap(noise, reps=1000)["p_value"])
    assert stats.bootstrap(good, reps=500, seed=3) == stats.bootstrap(good, reps=500, seed=3)
    assert not stats.bootstrap(good[:20])["available"]


def test_false_positive_rate_of_the_bootstrap_test_is_controlled():
    hits = sum(stats.bootstrap(np.random.default_rng(s).normal(0, 0.01, 500), rf=0.0, reps=400, seed=s)["p_value"] < 0.05 for s in range(40))
    assert hits <= 8                                                         # 5% nominal; allow slack for 40 trials


def test_luck_test_ranks_real_timing_high_and_random_timing_middle():
    rng = np.random.default_rng(2)
    r = rng.normal(0, 0.01, 1500)
    perfect = np.r_[(r[1:] > 0).astype(int), 0]                              # position that foresees the next day (cheating): signal[t-1] held at t
    cheat = stats.luck_test(perfect, r, reps=500)
    assert cheat["available"] and cheat["percentile"] > 0.99 and cheat["p_value"] < 0.01
    rand = (rng.random(1500) < 0.5).astype(int)
    mid = stats.luck_test(rand, r, reps=500)
    assert 0.02 < mid["percentile"] < 0.98
    assert not stats.luck_test(np.zeros(1500), r)["available"]


# ---------------- service ----------------

def test_backtest_end_to_end_structure_and_buyhold_comparison():
    d = frame(1000, seed=8)
    out = backtest(d, st.get("ma_cross"), {}, costs=cm.INDIA_DELIVERY, oos_fraction=0.3, reps=300)
    for k in ("metrics", "buy_hold", "costs", "series", "trades", "bootstrap", "luck_test", "held_out", "verdict", "reviewer_input", "no_cost"):
        assert k in out
    assert out["costs"]["total_drag"] > 0 and out["costs"]["return_lost_to_costs"] > 0
    assert out["held_out"]["split_date"] > out["first_trade_allowed"] and out["series"]["equity"][0]["v"] == pytest.approx(100, abs=0.5)
    assert out["reviewer_input"]["costs_included"] is True and out["reviewer_input"]["oos_fraction"] == 0.3


def test_no_costs_preset_is_reported_as_no_costs():
    out = backtest(frame(500, seed=9), st.get("momentum"), {}, costs=cm.NO_COSTS, reps=200)
    assert out["reviewer_input"]["costs_included"] is False and out["costs"]["total_drag"] == 0


def test_optimizing_noise_looks_good_in_sample_and_is_exposed_out_of_sample():
    """The classic trap: search enough parameters on random data and one will look great in-sample."""
    gaps, ins, oos_s = [], [], []
    for seed in range(12):
        d = frame(1100, seed=100 + seed, drift=0.0)
        out = backtest(d, st.get("breakout"), {}, costs=cm.NO_COSTS, oos_fraction=0.4, optimize=True, reps=100, seed=seed, rf=0.0)
        ho = out["held_out"]
        gaps.append(ho["in_sample"]["sharpe"] - ho["out_of_sample"]["sharpe"])
        ins.append(ho["in_sample"]["sharpe"])
        oos_s.append(ho["out_of_sample"]["sharpe"])
        assert out["search"]["trials"] == 12 and out["reviewer_input"]["n_params_tuned"] == 12
    assert np.mean(gaps) > 0.15 and np.mean(ins) > np.mean(oos_s)                          # selection bias: in-sample flatters, held-out does not
    assert out["verdict"]["label"] == "no demonstrated edge"


def test_optimize_requires_held_out_data_and_inputs_are_validated():
    d = frame(500)
    with pytest.raises(ValueError, match="held-out"):
        backtest(d, st.get("ma_cross"), {}, costs=cm.NO_COSTS, optimize=True)
    with pytest.raises(ValueError, match="at least"):
        backtest(d.iloc[:100], st.get("ma_cross"), {}, costs=cm.NO_COSTS)
    with pytest.raises(ValueError):
        st.get("ma_cross").signal(d, fast=60, slow=50)
    with pytest.raises(ValueError):
        st.get("ma_cross").signal(d, bogus=1)
    with pytest.raises(ValueError):
        st.get("nope")


def test_backtest_is_deterministic():
    d = frame(600, seed=10)
    a = backtest(d, st.get("rsi_reversion"), {}, costs=cm.INDIA_DELIVERY, reps=200)
    b = backtest(d, st.get("rsi_reversion"), {}, costs=cm.INDIA_DELIVERY, reps=200)
    assert a["metrics"] == b["metrics"] and a["bootstrap"] == b["bootstrap"] and a["trades"] == b["trades"]


def test_reviewer_red_flags_fire_on_a_weak_backtest():
    from app.llm.tasks.analyst import backtest_red_flags
    out = backtest(frame(500, seed=11), st.get("momentum"), {}, costs=cm.NO_COSTS, reps=200)
    ids = {f["id"] for f in backtest_red_flags(out["reviewer_input"])}
    assert {"costs_ignored", "no_out_of_sample"} <= ids


# ---------------- API ----------------

def test_api_lists_strategies_and_runs_a_backtest(client):
    s = client.get("/backtest/strategies").json()
    assert {x["name"] for x in s["strategies"]} == set(st.STRATEGIES) and "india_delivery" in s["cost_presets"] and s["strategies"][0]["grid_size"] > 0
    client.get("/prices/RELIANCE")
    r = client.post("/backtest/RELIANCE", json={"strategy": "ma_cross"})
    assert r.status_code == 422 and "bars" in r.json()["detail"]                       # the fake provider only has 60 bars
    assert client.post("/backtest/RELIANCE", json={"strategy": "zzz"}).status_code == 422
    assert client.post("/backtest/RELIANCE", json={"cost_overrides": {"x": 1}}).status_code == 422
    assert client.post("/backtest/NOTASTOCK", json={}).status_code in (404, 422)


def test_api_end_to_end_with_enough_history(client):
    from app.data import db as dbmod
    from app.data.prices import upsert_prices
    d = frame(700, seed=12)
    d["adj_close"] = d["close"]
    d.index = d.index.tz_localize("UTC")
    db = next(dbmod.get_session())
    upsert_prices(db, "RELIANCE", "1d", d, "test")
    r = client.post("/backtest/RELIANCE", json={"strategy": "breakout", "oos_fraction": 0.3, "optimize": True, "reps": 200}).json()
    assert r["symbol"] == "RELIANCE" and r["search"]["trials"] == 12 and r["held_out"] and r["verdict"]["label"] in ("no demonstrated edge", "survives these tests")
    assert r["reviewer_input"]["n_params_tuned"] == 12
