import numpy as np
import pandas as pd
import pytest

from app.data import calendar as cal
from app.features import sentiment as sf


def ep(s: str) -> int:
    """IST wall-clock string -> epoch seconds."""
    return int(pd.Timestamp(s, tz=cal.IST).timestamp())


def frame(rows):
    return pd.DataFrame(rows, columns=["published", "score"])


def test_post_close_articles_roll_to_next_day():
    d = sf.effective_date(frame([(ep("2026-01-05 10:00"), 0), (ep("2026-01-05 15:29"), 0), (ep("2026-01-05 15:30"), 0),
                                 (ep("2026-01-05 23:00"), 0)])["published"])
    assert [x.date().isoformat() for x in d] == ["2026-01-05", "2026-01-05", "2026-01-06", "2026-01-06"]


def test_daily_aggregates_hand_computed():
    f = sf.daily_features(frame([(ep("2026-01-05 10:00"), 0.5), (ep("2026-01-05 12:00"), -0.1),
                                 (ep("2026-01-05 14:00"), 0.9), (ep("2026-01-07 11:00"), -0.5)]))
    d5 = f.loc["2026-01-05"]
    assert d5["mean_sent"] == pytest.approx((0.5 - 0.1 + 0.9) / 3) and d5["n_articles"] == 3
    assert d5["sent_std"] == pytest.approx(np.std([0.5, -0.1, 0.9]))
    assert d5["pos_ratio"] == pytest.approx((2 + 1) / (0 + 1))           # 0.5 & 0.9 positive, none negative, add-one
    assert f.loc["2026-01-06", "n_articles"] == 0 and np.isnan(f.loc["2026-01-06", "mean_sent"])
    assert f.loc["2026-01-07", "pos_ratio"] == pytest.approx(1 / 2)


def test_recency_weighting_half_life_24h():
    # Day close = 15:30 IST. One article at the close (weight 1, score 0), one 24h earlier (weight 0.5, score 1).
    f = sf.daily_features(frame([(ep("2026-01-05 15:29:59"), 1.0), (ep("2026-01-06 15:29:59"), 0.0)]))
    assert f.loc["2026-01-06", "recency_weighted"] == pytest.approx(0.5 / 1.5, abs=1e-3)
    assert f.loc["2026-01-05", "recency_weighted"] == pytest.approx(1.0)


def test_volume_spike_flag():
    rows = [(ep(f"2026-01-{d:02d} 11:00"), 0.0) for d in range(1, 29) for _ in range(2)]   # 2/day baseline
    rows += [(ep("2026-01-29 11:00"), 0.0) for _ in range(12)]
    rows += [(ep("2026-01-29 12:00"), 0.0)]
    f = sf.daily_features(frame(rows))
    assert f.loc["2026-01-29", "volume_spike"] == 1 and f.loc["2026-01-20", "volume_spike"] == 0


def test_features_are_point_in_time_safe():
    rng = np.random.default_rng(1)
    base = [(ep("2026-01-01 11:00") + int(h * 3600), float(rng.uniform(-1, 1))) for h in range(0, 24 * 40, 5)]
    cutoff = ep("2026-02-05 15:30")
    past = [r for r in base if r[0] < cutoff]
    future = [(cutoff + 3600 * k, 1.0) for k in range(1, 30)]       # news arriving after the cut
    a = sf.daily_features(frame(past))
    b = sf.daily_features(frame(past + future))
    common = a.index[:-1]                                              # the last bucket may still be filling
    pd.testing.assert_frame_equal(a.loc[common], b.loc[common])


def test_divergence_flag():
    idx = pd.date_range("2026-01-01", periods=12, freq="D")
    close = pd.Series(np.linspace(100, 112, 12), index=idx)             # price rising
    mom = pd.Series(-0.1, index=idx)                                    # sentiment momentum falling
    assert sf.divergence(mom, close).iloc[-1] == 1
    assert sf.divergence(-mom, close).iloc[-1] == 0


def test_lead_lag_finds_planted_lead_and_ignores_noise():
    rng = np.random.default_rng(0)
    n = 400
    idx = pd.date_range("2025-01-01", periods=n, freq="D")
    s = pd.Series(rng.normal(0, 1, n), index=idx)
    ret = 0.01 * s.shift(1).fillna(0) + rng.normal(0, 0.005, n)          # sentiment leads price by 1 day
    close = 100 * (1 + ret).cumprod()
    ll = {r["lag"]: r for r in sf.lead_lag(s, close)}
    assert ll[1]["corr"] > 0.5 and ll[1]["p_bonferroni"] < 0.001
    assert all(abs(ll[k]["corr"]) < 0.25 for k in (-3, -2, 2, 3))
    noise = pd.Series(100 * (1 + rng.normal(0, 0.01, n)).cumprod(), index=idx)
    assert all((r["p_bonferroni"] or 1) > 0.05 for r in sf.lead_lag(s, noise))


def test_lead_lag_needs_enough_data():
    idx = pd.date_range("2026-01-01", periods=15, freq="D")
    out = sf.lead_lag(pd.Series(np.arange(15.0), index=idx), pd.Series(np.arange(100, 115.0), index=idx))
    assert all(r["corr"] is None for r in out)


def test_market_index():
    m = sf.market_index(frame([(ep("2026-01-05 10:00"), 0.4), (ep("2026-01-05 11:00"), -0.2), (ep("2026-01-06 11:00"), 0.1)]))
    assert m.loc["2026-01-05"] == pytest.approx(0.1) and sf.market_index(frame([])).empty
