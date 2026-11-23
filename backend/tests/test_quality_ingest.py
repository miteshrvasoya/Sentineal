import numpy as np
import pandas as pd

from app.data.ingest import backfill_symbol
from app.data.prices import load_prices, upsert_prices
from app.data.quality import quality_report
from app.providers.base import ProviderRouter
from tests.conftest import FakeProvider, make_frame


def stored(df, source="x"):
    out = df.copy()
    out.index = [int(t.timestamp()) for t in df.index]
    out["source"] = source
    return out


def ist_midnight_frame(days: list[str], close=None):
    idx = pd.DatetimeIndex([pd.Timestamp(d, tz="Asia/Kolkata").tz_convert("UTC") for d in days])
    c = np.array(close if close is not None else np.linspace(100, 110, len(days)), dtype=float)
    return pd.DataFrame({"open": c, "high": c + 1, "low": c - 1, "close": c, "adj_close": c, "volume": 1000.0}, index=idx)


def test_detects_missing_trading_day_and_holiday_awareness():
    # 2026-01-26 is a holiday (not "missing"); 2026-01-28 deliberately absent.
    days = ["2026-01-23", "2026-01-27", "2026-01-29", "2026-01-30"]
    rep = quality_report(stored(ist_midnight_frame(days)), "1d")
    miss = next(i for i in rep["issues"] if i["kind"] == "missing_days")
    assert miss["dates"] == ["2026-01-28"] and rep["checks"]["missing_days"] == 1


def test_flags_unadjusted_split_as_possible_corporate_action():
    days = [d.strftime("%Y-%m-%d") for d in pd.bdate_range("2026-02-02", periods=30)]
    close = np.full(30, 1000.0)
    close[15:] = 500.0  # raw 2:1 split
    df = ist_midnight_frame(days, close)
    df["adj_close"] = 500.0                                    # adjusted series is smooth
    rep = quality_report(stored(df), "1d")
    out = next(i for i in rep["issues"] if i["kind"] == "outliers")
    assert out["items"][0]["kind"] == "possible_corporate_action"


def test_ohlc_violation_is_error_and_empty_is_error():
    df = ist_midnight_frame(["2026-02-02", "2026-02-03"])
    df.iloc[0, df.columns.get_loc("high")] = 1.0
    assert quality_report(stored(df), "1d")["ok"] is False
    assert quality_report(pd.DataFrame(), "1d")["issues"][0]["kind"] == "no_data"


def test_mixed_sources_warned():
    df = stored(ist_midnight_frame(["2026-02-02", "2026-02-03"]))
    df["source"] = ["angelone", "yahoo"]
    assert any(i["kind"] == "mixed_sources" for i in quality_report(df, "1d")["issues"])


async def test_backfill_is_incremental(client):
    from app.data.db import get_session
    db = next(get_session())
    p = FakeProvider(frame=make_frame(40))
    r = ProviderRouter([p])
    first = await backfill_symbol(db, r, "TCS", "1d")
    assert first["ok"] and first["new_bars"] == 40
    again = await backfill_symbol(db, r, "TCS", "1d")
    assert again["new_bars"] == 0                              # overlap re-fetched, nothing duplicated
    assert len(load_prices(db, "TCS", "1d")) == 40
    bad = await backfill_symbol(db, ProviderRouter([FakeProvider(fail=True)]), "INFY", "1d")
    assert bad["ok"] is False and "boom" in bad["error"]


def test_quality_endpoint(client):
    from app.data.db import get_session
    db = next(get_session())
    upsert_prices(db, "SBIN", "1d", make_frame(30), "fake")
    j = client.get("/data-quality/sbin").json()
    assert j["symbol"] == "SBIN" and j["bars"] == 30 and "checks" in j
    assert client.get("/data-quality/SBIN?interval=3d").status_code == 422
    assert client.post("/ingest/backfill?interval=1d", json=["ITC"]).json()[0]["ok"] is True
