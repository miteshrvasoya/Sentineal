import numpy as np
import pandas as pd
import pytest

from app.features import structure as st


def path(waypoints, step=1.0):
    """Closes moving linearly through waypoints."""
    out = [waypoints[0]]
    for a, b in zip(waypoints, waypoints[1:], strict=False):
        n = int(abs(b - a) / step)
        out += list(np.linspace(a, b, n + 1)[1:])
    return np.array(out)


def mk(closes, pad=0.5, vol=1000.0):
    c = np.asarray(closes, float)
    o = np.concatenate([[c[0]], c[:-1]])
    df = pd.DataFrame({"open": o, "high": np.maximum(o, c) + pad, "low": np.minimum(o, c) - pad,
                       "close": c, "volume": vol},
                      index=pd.date_range("2024-01-01", periods=len(c), freq="B", tz="UTC"))
    return df


ZIG = path([10, 20, 14, 25, 18, 22, 12])


def test_swings_are_confirmed_k_bars_late():
    sw = st.raw_swings(mk(ZIG), k=2)
    assert sw and all(s.confirmed == s.i + 2 for s in sw)


def test_swing_labels_and_trend():
    events, seq, _ = st.structure_events(mk(ZIG), k=2)
    labels = {s.price: s.label for s in seq}                         # pad 0.5 around the waypoint closes
    assert labels[25.5] == "HH" and labels[17.5] == "HL" and labels[22.5] == "LH"
    assert [s.kind for s in seq] == ["high", "low", "high", "low", "high"]
    assert st.classify_trend(seq) == "range"


def test_bos_then_choch():
    events, _, _ = st.structure_events(mk(ZIG), k=2)
    kinds = [(e["kind"], e["dir"]) for e in events if e["kind"] in ("BOS", "CHoCH")]
    assert kinds == [("BOS", "bull"), ("CHoCH", "bear")]
    bos = next(e for e in events if e["kind"] == "BOS")
    assert bos["level"] == pytest.approx(20.5)


def test_liquidity_sweep_wick_through_level_closing_back():
    c = path([10, 20, 14, 18])
    df = mk(c)
    # Add a bar whose wick pierces the 20.5 swing high but closes below it.
    extra = pd.DataFrame({"open": [18.0], "high": [21.5], "low": [17.5], "close": [19.0], "volume": [1000.0]},
                         index=[df.index[-1] + pd.offsets.BDay(1)])
    ev, _, _ = st.structure_events(pd.concat([df, extra]), k=2)
    sw = [e for e in ev if e["kind"] == "sweep_high"]
    assert len(sw) == 1 and sw[0]["dir"] == "bear" and sw[0]["i"] == len(df)


def test_fvg_detected_and_filled():
    base = mk(np.full(20, 100.0))
    rows = [(100, 101, 99.5, 100.5), (100.5, 108, 100.4, 107.5), (107.5, 110, 104, 109),   # gap 101..104
            (109, 109.5, 100, 101)]                                                            # trades back through gap
    add = pd.DataFrame(rows, columns=["open", "high", "low", "close"])
    add["volume"] = 1000.0
    add.index = pd.date_range(base.index[-1] + pd.offsets.BDay(1), periods=4, freq="B", tz="UTC")
    df = pd.concat([base, add])
    f = st.fair_value_gaps(df)
    bull = [g for g in f if g["dir"] == "bull"]
    assert len(bull) == 1 and bull[0]["low"] == 101 and bull[0]["high"] == 104 and bull[0]["formed"] == 22
    st.annotate_resolution(df, bull, "fvg")
    assert bull[0]["resolved"] == 23


def test_order_block_is_last_down_candle_before_break():
    events, _, _ = st.structure_events(mk(ZIG), k=2)
    df = mk(ZIG)
    obs = st.order_blocks(df, events)
    bull = next(o for o in obs if o["dir"] == "bull")
    j = bull["i"]
    assert df.close.iloc[j] < df.open.iloc[j] and bull["formed"] > j


def test_fibonacci_levels():
    _, seq, _ = st.structure_events(mk(path([10, 20, 14, 25, 20])), k=2)
    fib = st.fibonacci(seq)
    assert fib["leg"] == "up"
    hi, lo = fib["end"], fib["start"]
    assert fib["retracements"]["0.5"] == pytest.approx((hi + lo) / 2)
    assert fib["retracements"]["0.618"] == pytest.approx(hi - 0.618 * (hi - lo))
    assert fib["extensions"]["1.618"] > hi


def test_pivot_formulas_hand_computed():
    p = st.pivot_set(110, 90, 100)           # P=100, range 20
    assert p["classic"]["P"] == 100 and p["classic"]["R1"] == 110 and p["classic"]["S1"] == 90
    assert p["classic"]["R2"] == 120 and p["classic"]["S2"] == 80
    assert p["classic"]["R3"] == 130 and p["classic"]["S3"] == 70
    assert p["fibonacci"]["R1"] == pytest.approx(100 + 0.382 * 20)
    assert p["camarilla"]["R4"] == pytest.approx(100 + 20 * 1.1 / 2)
    assert p["camarilla"]["S1"] == pytest.approx(100 - 20 * 1.1 / 12)


def test_pivots_use_last_completed_period():
    df = mk(path([100, 130, 110, 125, 105, 120]), pad=1)
    p = st.pivots(df)
    last = df.iloc[-1]
    assert p["daily"]["classic"]["P"] == pytest.approx((last.high + last.low + last.close) / 3)


def test_volume_profile_poc_and_value_area():
    n = 80
    c = np.concatenate([np.linspace(100, 110, 20), np.full(40, 105.0), np.linspace(105, 100, 20)])
    df = mk(c, pad=0.3)
    df["volume"] = np.where(np.abs(c - 105) < 0.5, 10000.0, 100.0)
    vp = st.volume_profile(df, window=n)
    assert 104 <= vp["poc"] <= 106 and vp["val"] <= vp["poc"] <= vp["vah"]
    assert sum(b["volume"] for b in vp["bins"]) == pytest.approx(df.volume.sum(), rel=1e-6)
    assert vp["vah"] - vp["val"] < 0.5 * (df.high.max() - df.low.min())


def test_sr_clusters_repeated_levels():
    c = path([100, 120, 105, 120, 104, 121, 106, 119, 105, 118, 110])
    df = mk(c, pad=0.3)
    _, seq, _ = st.structure_events(df, k=2)
    zones = st.sr_zones(seq, df)
    assert zones and zones[0]["touches"] >= 2
    assert any(z["low"] > 115 for z in zones) and any(z["high"] < 108 for z in zones)


def test_wyckoff_label_is_heuristic():
    rng = np.random.default_rng(1)
    c = 100 + rng.normal(0, 0.4, 80)
    out = st.wyckoff_heuristic(mk(c))
    assert out["heuristic"] is True and out["label"] in {"none", "accumulation_like", "distribution_like"}
    assert st.wyckoff_heuristic(mk(c[:20]))["label"] == "insufficient_data"


def test_events_fvg_ob_have_no_lookahead():
    rng = np.random.default_rng(4)
    c = 100 + np.cumsum(rng.normal(0, 1.5, 500))
    df = mk(c)
    cut = 350
    full_e, _, _ = st.structure_events(df, 3)
    part_e, _, _ = st.structure_events(df.iloc[:cut], 3)
    assert [e for e in full_e if e["i"] < cut] == part_e
    key = lambda z: (z["i"], z["formed"], z["dir"], z["low"], z["high"])  # noqa: E731
    assert [key(z) for z in st.fair_value_gaps(df) if z["formed"] < cut] == [key(z) for z in st.fair_value_gaps(df.iloc[:cut])]
    fo = [key(z) for z in st.order_blocks(df, full_e) if z["formed"] < cut]
    po = [key(z) for z in st.order_blocks(df.iloc[:cut], part_e)]
    assert fo == po


def test_analyze_smoke_and_json_safe():
    import json
    rng = np.random.default_rng(2)
    df = mk(100 + np.cumsum(rng.normal(0, 1.5, 400)))
    out = st.analyze(df)
    json.dumps(out)
    assert out["trend"] in {"uptrend", "downtrend", "range", "undetermined"}
    assert out["volume_profile"]["poc"] > 0 and "daily" in out["pivots"]


def test_sr_zone_width_is_capped_no_chaining():
    # A staircase of swing highs 1 ATR apart would chain into one zone under DBSCAN.
    c = path([100, 110, 102, 111, 103, 112, 104, 113, 105, 114, 106, 115, 107, 116, 108, 109])
    df = mk(c, pad=0.3)
    _, seq, _ = st.structure_events(df, k=2)
    a = float(st.atr(df).dropna().iloc[-1])
    for z in st.sr_zones(seq, df):
        assert z["high"] - z["low"] <= 1.0 * a + 1e-9


def test_dealing_range_flags_price_outside_range():
    seq = [st.Swing(1, "low", 100, 3), st.Swing(5, "high", 110, 8)]
    assert st.dealing_range(seq, 125)["zone"] == "above_range"
    assert st.dealing_range(seq, 95)["zone"] == "below_range"
    assert st.dealing_range(seq, 107)["zone"] == "premium"
