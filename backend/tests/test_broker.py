"""Angel One holdings: parsing, read-only client, snapshot storage, merge into the portfolio, and 'include my stocks everywhere'."""
import json
from datetime import date, timedelta

import httpx
import pytest

from app import broker
from app import portfolio as pf
from app.data import db as dbmod
from app.data.models import BrokerHolding, PortfolioTxn, WatchlistItem
from app.providers.angelone import AngelOneProvider, ScripMaster, normalize_holdings
from app.providers.base import ProviderError
from tests.test_screener import seed

CREDS = {"api_key": "k", "client": "C1", "pin": "1234", "totp": "JBSWY3DPEHPK3PXPJBSWY3DPEHPK3PXP"}
RAW = [
    {"tradingsymbol": "RELIANCE-EQ", "exchange": "NSE", "isin": "INE002A01018", "quantity": 10, "t1quantity": 0, "realisedquantity": 10, "averageprice": 2400.5, "ltp": 2894.0},
    {"tradingsymbol": "TCS-EQ", "exchange": "NSE", "quantity": 0, "t1quantity": 2, "realisedquantity": 3, "averageprice": 3300, "ltp": 3100},
    {"tradingsymbol": "ITC-BE", "exchange": "NSE", "quantity": 5, "averageprice": 400, "ltp": None},
    {"tradingsymbol": "ZERO-EQ", "exchange": "NSE", "quantity": 0, "averageprice": 10},
    {"tradingsymbol": "INFY-EQ", "exchange": "NSE", "quantity": 4, "averageprice": 1500},
    {"tradingsymbol": "INFY-EQ", "exchange": "NSE", "quantity": 6, "averageprice": 1600},
    {"tradingsymbol": "BSEONLY", "exchange": "BSE", "quantity": 7, "averageprice": 50},
    {"tradingsymbol": "BAD-EQ", "exchange": "NSE", "quantity": "x", "averageprice": 1},
]


def test_normalize_strips_suffixes_merges_duplicates_and_drops_empty_rows():
    out = {h["symbol"]: h for h in normalize_holdings(RAW)}
    assert set(out) == {"RELIANCE", "TCS", "ITC", "INFY", "BSEONLY.BO"}
    assert out["TCS"]["qty"] == 5 and out["ITC"]["ltp"] is None and out["RELIANCE"]["avg_price"] == 2400.5
    assert out["INFY"]["qty"] == 10 and out["INFY"]["avg_price"] == pytest.approx((4 * 1500 + 6 * 1600) / 10)


def provider(handler):
    sm = ScripMaster()
    sm.load([])
    return AngelOneProvider(httpx.AsyncClient(transport=httpx.MockTransport(handler)), sm, CREDS)


async def test_client_logs_in_then_reads_holdings_with_get_only():
    calls = []

    def h(req: httpx.Request):
        calls.append((req.method, req.url.path))
        if "loginByPassword" in req.url.path:
            return httpx.Response(200, json={"status": True, "data": {"jwtToken": "J", "refreshToken": "R"}})
        assert req.headers["Authorization"] == "Bearer J" and req.headers["X-PrivateKey"] == "k"
        return httpx.Response(200, json={"status": True, "data": {"holdings": RAW, "totalholding": {}}})
    out = await provider(h).fetch_holdings()
    assert {x["symbol"] for x in out} >= {"RELIANCE", "TCS"} and calls[-1] == ("GET", "/rest/secure/angelbroking/portfolio/v1/getAllHolding")
    assert not any(m not in ("GET", "POST") or "order" in p.lower() for m, p in calls)               # no order endpoints are ever called
    assert [p for m, p in calls if m == "POST"] == ["/rest/auth/angelbroking/user/v1/loginByPassword"]


async def test_falls_back_to_the_plain_endpoint_and_relogs_in_after_a_401():
    state = {"n401": 0, "paths": []}

    def h(req: httpx.Request):
        state["paths"].append(req.url.path)
        if "loginByPassword" in req.url.path:
            return httpx.Response(200, json={"status": True, "data": {"jwtToken": "J"}})
        if "getAllHolding" in req.url.path:
            return httpx.Response(200, json={"status": False, "errorcode": "AB1004", "message": "not available"})
        if state["n401"] == 0:
            state["n401"] += 1
            return httpx.Response(401, json={})
        return httpx.Response(200, json={"status": True, "data": RAW})
    out = await provider(h).fetch_holdings()
    assert len(out) == 5 and state["paths"].count("/rest/auth/angelbroking/user/v1/loginByPassword") == 2 and "/rest/secure/angelbroking/portfolio/v1/getHolding" in state["paths"]


@pytest.fixture
def db():
    dbmod.init_engine("sqlite:///:memory:")
    s = next(dbmod.get_session())
    for i, (sym, sec) in enumerate([("RELIANCE", "Energy"), ("TCS", "IT"), ("ITC", "FMCG"), ("INFY", "IT")]):
        seed(s, sym, sec, 0.001, n=300, seed_=i)
    return s


class FakeAngel:
    def __init__(self, configured=True, rows=None, error=None):
        self.configured, self.rows, self.error = configured, rows if rows is not None else normalize_holdings(RAW), error
        self.creds = dict(CREDS) if configured else {"api_key": "", "client": "", "pin": "", "totp": ""}

    def is_configured(self):
        return self.configured

    async def fetch_holdings(self):
        if self.error:
            raise ProviderError(self.error)
        return self.rows


async def test_sync_stores_a_snapshot_and_reports_what_changed(db):
    r1 = await broker.sync(db, FakeAngel())
    assert r1["ok"] and r1["count"] == 5 and sorted(r1["added"]) == ["BSEONLY.BO", "INFY", "ITC", "RELIANCE", "TCS"]
    rows = normalize_holdings(RAW)
    rows = [x for x in rows if x["symbol"] != "ITC"]
    rows[0]["qty"] += 1
    r2 = await broker.sync(db, FakeAngel(rows=rows))
    assert r2["removed"] == ["ITC"] and len(r2["changed"]) == 1 and r2["added"] == [] and db.query(BrokerHolding).count() == 4


async def test_sync_without_credentials_explains_how_to_set_up_and_errors_are_friendly(db):
    r = await broker.sync(db, FakeAngel(configured=False))
    assert not r["ok"] and r["configured"] is False and "ANGEL_API_KEY" in r["missing"] and len(r["steps"]) == 4
    e = await broker.sync(db, FakeAngel(error="angelone error AB1050: Invalid totp"))
    assert not e["ok"] and "TOTP" in e["message"] and db.query(BrokerHolding).count() == 0


def test_broker_only_holdings_join_the_portfolio_with_their_own_cost(db):
    db.add_all([BrokerHolding(source="angelone", symbol="RELIANCE", qty=10, avg_price=2000, synced_at=1), BrokerHolding(source="angelone", symbol="TCS", qty=5, avg_price=3000, synced_at=1)])
    db.commit()
    p = pf.summarize(db)
    assert not p["empty"] and p["summary"]["holdings"] == 2 and p["summary"]["invested"] == pytest.approx(10 * 2000 + 5 * 3000)
    r = next(x for x in p["positions"] if x["symbol"] == "RELIANCE")
    assert r["source"] == "angelone" and r["needs_date"] and r["avg_cost"] == 2000 and r["pl"] == pytest.approx(r["value"] - 20000) and r["weight"] > 0
    assert p["summary"]["annual_return"] is None and "Angel One" in (p["summary"]["annual_return_note"] or "")
    assert any("without purchase dates" in c["title"] for c in p["checkup"]) and p["broker"]["only"] == ["RELIANCE", "TCS"]
    assert sum(x["weight"] for x in p["positions"]) == pytest.approx(1.0) and p["allocation"]["by_sector"]


def ago(n):
    return (date.today() - timedelta(days=n)).isoformat()


def test_your_own_records_win_and_a_quantity_mismatch_is_reported(db):
    db.add(PortfolioTxn(symbol="RELIANCE", side="buy", qty=8, price=100, fees=0, date=ago(200), note="", created=0))
    db.add(BrokerHolding(source="angelone", symbol="RELIANCE", qty=10, avg_price=105, synced_at=1))
    db.commit()
    p = pf.summarize(db)
    r = p["positions"][0]
    assert r["source"] == "records" and r["qty"] == 8 and r["avg_cost"] == 100 and p["broker"]["mismatches"] == [{"symbol": "RELIANCE", "records_qty": 8, "broker_qty": 10}]
    assert any("disagree" in c["title"] for c in p["checkup"]) and p["summary"]["annual_return"] is not None


def test_adopting_broker_holdings_turns_them_into_dated_purchases(db):
    db.add_all([BrokerHolding(source="angelone", symbol="RELIANCE", qty=10, avg_price=2000, synced_at=1), BrokerHolding(source="angelone", symbol="TCS", qty=5, avg_price=3000, synced_at=1)])
    db.add(PortfolioTxn(symbol="TCS", side="buy", qty=5, price=3000, fees=0, date=ago(100), note="", created=0))             # already in your records
    db.commit()
    assert pf.adopt_broker(db, ago(60)) == 1
    p = pf.summarize(db)
    assert all(r["source"] == "records" and not r["needs_date"] for r in p["positions"]) and p["broker"]["only"] == [] and p["broker"]["mismatches"] == []
    with pytest.raises(pf.PortfolioError):
        pf.validate_new([], [PortfolioTxn(symbol="X", side="buy", qty=1, price=1, fees=0, date="2999-01-01", note="", created=0)])


def test_owned_stocks_are_tracked_everywhere_even_when_not_on_the_watchlist(db):
    db.add(WatchlistItem(symbol="TCS", added_at=1))
    db.add(BrokerHolding(source="angelone", symbol="ITC", qty=3, avg_price=400, synced_at=1))
    db.add(PortfolioTxn(symbol="INFY", side="buy", qty=2, price=1500, fees=0, date=ago(30), note="", created=0))
    db.commit()
    assert pf.holding_symbols(db) == ["INFY", "ITC"]
    assert {"TCS", "ITC", "INFY"} <= set(pf.tracked_symbols(db))
    sold = PortfolioTxn(symbol="RELIANCE", side="buy", qty=1, price=1, fees=0, date=ago(20), note="", created=0)
    db.add(sold)
    db.add(PortfolioTxn(symbol="RELIANCE", side="sell", qty=1, price=2, fees=0, date=ago(10), note="", created=0))
    db.commit()
    assert "RELIANCE" not in pf.holding_symbols(db)                                                # fully sold stocks are no longer 'owned'


def test_every_calculation_surface_includes_your_stocks(client, db):
    from app.main import app
    db.add(BrokerHolding(source="angelone", symbol="ITC", qty=3, avg_price=400, synced_at=1))
    db.commit()
    wl = {r["symbol"]: r for r in client.get("/watchlist/summary").json()}
    assert wl["ITC"]["held"] is True
    assert "ITC" in [r["symbol"] for r in client.get("/redflags").json()]
    from app.llm.tasks.assistant import briefing_pack
    pack = briefing_pack(db)
    assert pack["facts"].get("watch.ITC.owned") is True and "watch.ITC.ret_1d" in pack["facts"]
    names = {j["name"] for j in app.state.scheduler.status()}
    assert "sync_holdings" in names
    rev = client.get("/discover/holdings").json()
    assert [h["symbol"] for h in rev["holdings"]] == ["ITC"] and rev["holdings"][0]["short"]["label"]
    assert client.get("/discover/stock/ITC").json()["owned"] is True
    ideas = client.get("/discover/ideas?horizon=short&limit=10").json()
    assert any(i["symbol"] == "ITC" and i["owned"] for i in ideas["ideas"])


def test_the_chat_assistant_can_see_your_portfolio_read_only(db):
    from app.agent import tools as tl
    with pytest.raises(tl.ToolError, match="not added any holdings"):
        tl.call(db, "my_portfolio", {})
    db.add(BrokerHolding(source="angelone", symbol="ITC", qty=3, avg_price=400, synced_at=1))
    db.commit()
    r = tl.call(db, "my_portfolio", {})
    assert r["positions"][0]["symbol"] == "ITC" and r["summary"]["holdings"] == 1
    assert "my_portfolio" in tl.TOOLS and not any(w in "my_portfolio" for w in ("order", "buy", "sell", "trade", "delete", "write"))


def test_api_status_sync_and_adopt(client, db):
    from app.deps import get_angel
    from app.main import app
    s = client.get("/broker/angelone/status").json()
    assert s["configured"] is False and s["read_only"] is True and s["holdings"] == 0 and len(s["steps"]) == 4
    r = client.post("/broker/angelone/sync").json()
    assert r["ok"] is False and r["configured"] is False
    app.dependency_overrides[get_angel] = lambda: FakeAngel()
    ok = client.post("/broker/angelone/sync").json()
    assert ok["ok"] and ok["count"] == 5 and "data" in ok
    st = client.get("/broker/angelone/status").json()
    assert st["configured"] and st["holdings"] == 5 and st["last_sync"]
    pfo = client.get("/portfolio").json()
    assert pfo["broker"]["connected"] and pfo["broker"]["count"] == 5
    assert client.post("/broker/angelone/adopt", json={"date": "2999-01-01"}).status_code == 422
    a = client.post("/broker/angelone/adopt", json={"date": ago(30)})
    assert a.status_code == 200 and a.json()["added"] == 5
    assert client.get("/portfolio").json()["broker"]["only"] == []
    app.dependency_overrides.pop(get_angel, None)
    _ = json
