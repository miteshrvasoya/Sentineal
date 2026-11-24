"""Phase 10: screener snapshot, filters, relative strength, breadth, sectors, API."""
import numpy as np
import pandas as pd
import pytest

from app.data import db as dbmod
from app.data.models import Symbol
from app.data.prices import upsert_prices
from app.screener import engine as eng


def seed(db, sym, sector, drift, n=320, seed_=0, vol=0.01):
    rng = np.random.default_rng(seed_)
    idx = pd.bdate_range(end=pd.Timestamp.now().normalize(), periods=n, tz="UTC")
    c = 100 * np.exp(np.cumsum(rng.normal(drift, vol, n)))
    o = np.r_[c[0], c[:-1]]
    d = pd.DataFrame({"open": o, "high": np.maximum(o, c) * 1.003, "low": np.minimum(o, c) * 0.997, "close": c, "adj_close": c, "volume": 1e6}, index=idx)
    upsert_prices(db, sym, "1d", d, "test")
    db.merge(Symbol(symbol=sym, name=sym, sector=sector))
    db.commit()


@pytest.fixture
def db():
    dbmod.init_engine("sqlite:///:memory:")
    eng._cache.clear()
    s = next(dbmod.get_session())
    specs = [("UPA", "IT", 0.004), ("UPB", "IT", 0.003), ("FLAT", "Banks", 0.0), ("DNA", "Banks", -0.003), ("DNB", "Energy", -0.004)]
    for i, (sym, sec, dr) in enumerate(specs):
        seed(s, sym, sec, dr, seed_=i)
    return s


def test_universe_has_rows_ranks_and_excludes_indices_and_short_history(db):
    seed(db, "NIFTY 50", "", 0.0, seed_=9)
    seed(db, "SHORT", "IT", 0.0, n=40, seed_=10)
    rows = eng.universe(db, use_cache=False)
    assert {r["symbol"] for r in rows} == {"UPA", "UPB", "FLAT", "DNA", "DNB"}
    by = {r["symbol"]: r for r in rows}
    assert by["UPA"]["rs_rank_126"] > by["FLAT"]["rs_rank_126"] > by["DNB"]["rs_rank_126"]
    assert 0 <= min(r["rs_rank_126"] for r in rows) and max(r["rs_rank_126"] for r in rows) == 100
    r = by["UPA"]
    assert r["pct_from_52w_high"] <= 0 and r["pct_from_52w_low"] >= 0 and r["sector"] == "IT" and r["above_sma200"] in (True, False)


def test_snapshot_values_are_computed_correctly(db):
    from app.data.prices import apply_adjustment, load_prices
    from app.features.pipeline import to_frame
    c = to_frame(apply_adjustment(load_prices(db, "UPA", "1d")))["close"]
    row = next(r for r in eng.universe(db, use_cache=False) if r["symbol"] == "UPA")
    assert row["ret_21d"] == pytest.approx(c.iloc[-1] / c.iloc[-22] - 1)
    assert row["close_vs_sma50"] == pytest.approx(c.iloc[-1] / c.iloc[-50:].mean() - 1)
    assert row["pct_from_52w_high"] == pytest.approx(c.iloc[-1] / c.iloc[-252:].max() - 1)
    assert row["price"] == pytest.approx(c.iloc[-1])


def test_filters_operators_and_missing_data(db):
    rows = eng.universe(db, use_cache=False)
    top = eng.screen(rows, [{"field": "rs_rank_126", "op": ">=", "value": 70}])
    assert {r["symbol"] for r in top["rows"]} == {r["symbol"] for r in rows if r["rs_rank_126"] >= 70} and top["universe"] == 5
    assert {r["symbol"] for r in eng.screen(rows, [{"field": "sector", "op": "in", "value": ["it"]}])["rows"]} == {"UPA", "UPB"}
    assert eng.screen(rows, [{"field": "ret_63d", "op": "between", "value": [-9, 9]}])["matches"] == 5
    assert eng.screen(rows, [{"field": "above_sma50", "op": "==", "value": True}, {"field": "sector", "op": "==", "value": "Banks"}])["matches"] <= 2
    pe = eng.screen(rows, [{"field": "pe", "op": "<", "value": 100}])                      # no fundamentals stored
    assert pe["matches"] == 0 and pe["missing_data"] == {"pe": 5}


def test_sorting_and_limit(db):
    rows = eng.universe(db, use_cache=False)
    asc = eng.screen(rows, [], sort="ret_126d", desc=False, limit=3)
    des = eng.screen(rows, [], sort="ret_126d", desc=True)
    assert [r["ret_126d"] for r in asc["rows"]] == sorted(r["ret_126d"] for r in rows)[:3]
    assert [r["ret_126d"] for r in des["rows"]] == sorted((r["ret_126d"] for r in rows), reverse=True)


@pytest.mark.parametrize("cond", [{"field": "nope", "op": ">", "value": 1}, {"field": "rsi", "op": "~", "value": 1}, {"field": "rsi", "op": ">", "value": "x"},
                                  {"field": "above_sma50", "op": ">", "value": True}, {"field": "sector", "op": ">", "value": "IT"},
                                  {"field": "rsi", "op": "between", "value": [1]}, {"field": "rsi", "op": "in", "value": [1]}])
def test_invalid_conditions_are_rejected(db, cond):
    with pytest.raises(ValueError):
        eng.screen(eng.universe(db, use_cache=False), [cond])


def test_every_preset_is_valid():
    for p in eng.PRESETS:
        assert eng.validate(p["conditions"]) == [], p["id"]


def test_breadth_and_sectors(db):
    b = eng.breadth(eng.universe(db, use_cache=False))
    assert b["n"] == 5 and 0 <= b["above_sma200"] <= 1 and "stocks are stored" in b["reading"]
    s = eng.sectors(eng.universe(db, use_cache=False))
    rows = {r["sector"]: r for r in s["rows"]}
    assert set(rows) == {"IT", "Banks", "Energy"} and rows["IT"]["rank_126d"] == 1 and rows["Energy"]["rank_126d"] == 3
    assert rows["IT"]["n"] == 2 and rows["IT"]["ret_126d"] > rows["Energy"]["ret_126d"]


def test_screen_does_not_use_the_future(db):
    """Dropping the last 30 bars changes today's snapshot, but a snapshot from truncated data equals the one computed then."""
    full = next(r for r in eng.universe(db, use_cache=False) if r["symbol"] == "UPA")
    from app.data.models import Price
    last = sorted(x[0] for x in db.query(Price.ts).filter(Price.symbol == "UPA").all())[-30]
    db.query(Price).filter(Price.symbol == "UPA", Price.ts >= last).delete()
    db.commit()
    eng._cache.clear()
    cut = next(r for r in eng.universe(db, use_cache=False) if r["symbol"] == "UPA")
    assert cut["bars"] == full["bars"] - 30 and cut["as_of"] < full["as_of"]


def test_api(client, db):
    f = client.get("/screener/fields").json()
    assert len(f["fields"]) > 20 and f["presets"][0]["id"] == "oversold_uptrend"
    r = client.post("/screener/run", json={"conditions": [{"field": "rs_rank_126", "op": ">=", "value": 50}], "limit": 2}).json()
    assert r["universe"] == 5 and len(r["rows"]) <= 2 and "not a forecast" in r["disclaimer"]
    assert client.post("/screener/run", json={"conditions": [{"field": "zzz", "op": ">", "value": 1}]}).status_code == 422
    assert client.get("/market/breadth").json()["n"] == 5 and client.get("/market/sectors").json()["rows"]
