import numpy as np
import pandas as pd

from app.features import patterns as pt
from tests.test_structure import mk


def series_with(rows, lead=None):
    """Prefix a gentle downtrend (so ATR and trend context exist) then explicit OHLC rows."""
    lead = lead if lead is not None else np.linspace(120, 100, 25)
    base = mk(lead, pad=0.5)
    add = pd.DataFrame(rows, columns=["open", "high", "low", "close"])
    add["volume"] = 1000.0
    add.index = pd.date_range(base.index[-1] + pd.offsets.BDay(1), periods=len(rows), freq="B", tz="UTC")
    return pd.concat([base, add])


def last(df, name):
    return bool(pt.detect(df)[name].iloc[-1])


def test_hammer_after_downtrend_only():
    df = series_with([(100, 101.2, 95, 101)])
    assert last(df, "hammer")
    up = series_with([(120, 121.2, 115, 121)], lead=np.linspace(100, 120, 25))
    assert not last(up, "hammer")                      # same shape but no prior decline


def test_shooting_star_after_uptrend():
    df = series_with([(120, 126, 119.9, 120.5)], lead=np.linspace(100, 120, 25))
    assert last(df, "shooting_star")


def test_doji_inside_outside():
    assert last(series_with([(100, 105, 95, 100.2)]), "doji")
    assert last(series_with([(100, 104, 96, 102), (100, 101, 99, 100.5)]), "inside_bar")
    assert last(series_with([(100, 101, 99, 100.5), (100, 105, 95, 104)]), "outside_bar")


def test_engulfing_pair():
    be = series_with([(101, 101.5, 98.5, 99), (98, 103, 97.5, 102.5)])
    assert last(be, "bullish_engulfing") and not last(be, "bearish_engulfing")
    bear = series_with([(99, 102, 98.5, 101.5), (102.5, 103, 97, 98)], lead=np.linspace(80, 100, 25))
    assert last(bear, "bearish_engulfing")


def test_morning_and_evening_star():
    ms = series_with([(104, 104.5, 98, 99), (98.5, 99, 97.5, 98.2), (98.5, 103, 98, 102.5)])
    assert last(ms, "morning_star")
    es = series_with([(96, 102, 95.5, 101), (101.5, 102.5, 101, 101.8), (101.2, 101.5, 95.5, 96)],
                     lead=np.linspace(80, 100, 25))
    assert last(es, "evening_star")


def test_harami():
    h = series_with([(104, 104.5, 98, 99), (100, 102, 99.8, 101.5)])
    assert last(h, "bullish_harami")


def test_three_soldiers_and_crows():
    s = series_with([(100, 103.1, 99.9, 103), (101.5, 105.1, 101.4, 105), (103.5, 107.1, 103.4, 107)])
    assert last(s, "three_white_soldiers")
    cr = series_with([(110, 110.1, 106.9, 107), (108.5, 108.6, 104.9, 105), (106.5, 106.6, 102.9, 103)],
                     lead=np.linspace(90, 110, 25))
    assert last(cr, "three_black_crows")


def test_detection_has_no_lookahead():
    rng = np.random.default_rng(3)
    df = mk(100 + np.cumsum(rng.normal(0, 1.5, 400)))
    full, part = pt.detect(df), pt.detect(df.iloc[:300])
    assert (full.iloc[:300].to_numpy() == part.to_numpy()).all()


def _walk(n=900, seed=0, signal_at=None, boost=0.05):
    rng = np.random.default_rng(seed)
    r = rng.normal(0, 0.01, n)
    if signal_at is not None:
        for t in signal_at:
            r[t + 1] = boost
    return mk(100 * np.cumprod(1 + r))


def test_planted_edge_is_detected_and_random_flags_are_not():
    idx = list(range(20, 800, 17))                       # ~46 signals, each followed by +5%
    df = _walk(signal_at=idx)
    flags = pd.DataFrame(False, index=df.index, columns=list(pt.DIRECTION))
    flags.iloc[idx, flags.columns.get_loc("hammer")] = True
    h1 = next(r for r in pt.edge_stats(df, flags) if r["pattern"] == "hammer")["horizons"]["1d"]
    assert h1["hit_rate"] == 1.0 and h1["verdict"].startswith("edge")

    rng = np.random.default_rng(9)
    df2 = _walk(seed=1)
    rnd = pd.DataFrame(rng.random((len(df2), len(pt.DIRECTION))) < 0.07, index=df2.index, columns=list(pt.DIRECTION))
    verdicts = [h["verdict"] for r in pt.edge_stats(df2, rnd) for h in r["horizons"].values() if "verdict" in h]
    assert not any(v.startswith("edge") for v in verdicts)


def test_small_samples_flagged_and_neutral_has_no_hit_rate():
    df = _walk(seed=2)
    flags = pd.DataFrame(False, index=df.index, columns=list(pt.DIRECTION))
    flags.iloc[[100, 200, 300], flags.columns.get_loc("hammer")] = True
    flags.iloc[::10, flags.columns.get_loc("doji")] = True
    stats = {r["pattern"]: r for r in pt.edge_stats(df, flags)}
    assert stats["hammer"]["horizons"]["5d"]["verdict"] == "insufficient sample"
    assert "hit_rate" not in stats["doji"]["horizons"]["5d"] and "avg_return_pct" in stats["doji"]["horizons"]["5d"]


def test_edge_stats_use_only_bars_with_full_forward_window():
    df = _walk(seed=3, n=200)
    flags = pd.DataFrame(False, index=df.index, columns=list(pt.DIRECTION))
    flags.iloc[[198], flags.columns.get_loc("hammer")] = True      # too close to the end for 5d/10d
    h = next(r for r in pt.edge_stats(df, flags) if r["pattern"] == "hammer")["horizons"]
    assert h["1d"]["n"] == 1 and h["5d"]["n"] == 0 and h["10d"]["n"] == 0
