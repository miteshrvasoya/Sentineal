"""My Investments: average-cost bookkeeping, profit, XIRR, history, check-up, API."""
from datetime import date, timedelta

import pytest

from app import portfolio as pf
from app.data import db as dbmod
from app.data.models import PortfolioTxn
from tests.test_screener import seed


def T(symbol, side, qty, price, d, fees=0.0, id_=None):
    return PortfolioTxn(id=id_, symbol=symbol, side=side, qty=qty, price=price, date=d, fees=fees, note="", created=0)


def test_average_cost_and_realised_profit_hand_checked():
    p = pf.replay([T("AAA", "buy", 10, 100, "2024-01-01", id_=1), T("AAA", "buy", 10, 120, "2024-02-01", id_=2), T("AAA", "sell", 5, 150, "2024-03-01", id_=3)])["AAA"]
    assert p.avg_cost == pytest.approx(110) and p.qty == 15
    assert p.realised == pytest.approx(5 * (150 - 110)) and p.cost == pytest.approx(15 * 110)


def test_fees_raise_cost_and_lower_proceeds():
    p = pf.replay([T("AAA", "buy", 10, 100, "2024-01-01", fees=20, id_=1), T("AAA", "sell", 10, 110, "2024-02-01", fees=30, id_=2)])["AAA"]
    assert p.realised == pytest.approx((10 * 110 - 30) - (10 * 100 + 20)) and p.qty == 0 and p.cost == 0


def test_cannot_sell_more_than_held_and_same_day_buy_counts_first():
    with pytest.raises(pf.PortfolioError, match="only held 5"):
        pf.replay([T("AAA", "buy", 5, 10, "2024-01-01", id_=1), T("AAA", "sell", 6, 11, "2024-01-02", id_=2)])
    with pytest.raises(pf.PortfolioError):
        pf.replay([T("AAA", "sell", 1, 11, "2024-01-01", id_=1), T("AAA", "buy", 5, 10, "2024-01-02", id_=2)])           # sold before buying
    assert pf.replay([T("AAA", "sell", 5, 11, "2024-01-01", id_=1), T("AAA", "buy", 5, 10, "2024-01-01", id_=2)])["AAA"].qty == 0


def test_validation_messages():
    today = date.today().isoformat()
    for bad in (T("A", "buy", 0, 1, today), T("A", "buy", 1, -1, today), T("A", "buy", 1, 1, "31-12-2024"), T("A", "buy", 1, 1, (date.today() + timedelta(days=3)).isoformat()), T("A", "hold", 1, 1, today)):
        with pytest.raises(pf.PortfolioError):
            pf.validate_new([], [bad])


def test_xirr_known_values():
    d0 = date(2024, 1, 1)
    r = pf.xirr([(d0, -100.0), (d0 + timedelta(days=365), 110.0)])
    assert r == pytest.approx(0.10, abs=1e-4)
    assert pf.xirr([(d0, -100.0), (d0 + timedelta(days=730), 121.0)]) == pytest.approx(0.10, abs=1e-3)
    assert pf.xirr([(d0, -100.0)]) is None and pf.xirr([(d0, 100.0), (d0, 50.0)]) is None
    assert pf.xirr([(d0, -100.0), (d0 + timedelta(days=365), 50.0)]) == pytest.approx(-0.5, abs=1e-3)


@pytest.fixture
def db():
    dbmod.init_engine("sqlite:///:memory:")
    s = next(dbmod.get_session())
    seed(s, "RELIANCE", "Energy", 0.001, n=400, seed_=1)
    seed(s, "TCS", "IT", 0.0005, n=400, seed_=2)
    seed(s, "INFY", "IT", -0.001, n=400, seed_=3)
    return s


def ago(n):
    return (date.today() - timedelta(days=n)).isoformat()


def test_summary_values_pl_and_allocation(db):
    from app.data.analysis import close_series
    db.add_all([T("RELIANCE", "buy", 10, 100, ago(200)), T("TCS", "buy", 5, 200, ago(150))])
    db.commit()
    s = pf.summarize(db)
    last = close_series(db, "RELIANCE", adjusted=False).iloc[-1]
    row = next(r for r in s["positions"] if r["symbol"] == "RELIANCE")
    assert row["value"] == pytest.approx(10 * last) and row["pl"] == pytest.approx(10 * last - 1000) and row["avg_cost"] == 100
    assert s["summary"]["invested"] == pytest.approx(2000) and s["summary"]["holdings"] == 2
    assert sum(r["weight"] for r in s["positions"]) == pytest.approx(1.0) and {a["sector"] for a in s["allocation"]["by_sector"]} == {"Energy", "IT"}
    assert s["summary"]["pl"] == pytest.approx(s["summary"]["value"] - 2000) and s["summary"]["annual_return"] is not None


def test_closed_positions_report_realised_profit_and_short_history_hides_annual_return(db):
    db.add_all([T("INFY", "buy", 10, 100, ago(30)), T("INFY", "sell", 10, 110, ago(10))])
    db.commit()
    s = pf.summarize(db)
    assert s["positions"] == [] and s["closed"][0]["realised"] == pytest.approx(100) and s["summary"]["annual_return"] is None and s["summary"]["realised"] == pytest.approx(100)


def test_empty_portfolio(db):
    s = pf.summarize(db)
    assert s["empty"] and s["positions"] == [] and s["checkup"] == []


def test_checkup_flags_concentration_sector_and_big_losers(db):
    from app.data.analysis import close_series
    last = float(close_series(db, "RELIANCE", adjusted=False).iloc[-1])
    db.add_all([T("RELIANCE", "buy", 100, last, ago(100)), T("TCS", "buy", 1, 1000, ago(100))])           # RELIANCE dominates
    db.add(T("INFY", "buy", 100, float(close_series(db, "INFY", adjusted=False).iloc[-1]) * 2, ago(100)))   # bought at double today's price
    db.commit()
    s = pf.summarize(db)
    titles = " | ".join(i["title"] for i in s["checkup"])
    assert "RELIANCE is" in titles and "own 3 stocks" in titles and "down more than 25%" in titles
    assert s["checkup"][0]["level"] in ("high", "medium") and all(i["text"] for i in s["checkup"])
    assert all("buy " not in i["text"].lower() and "you should" not in i["text"].lower() for i in s["checkup"])        # observations, not advice


def test_a_balanced_portfolio_gets_a_good_note(db):
    from app.data.analysis import close_series
    for i, s in enumerate(("RELIANCE", "TCS", "INFY")):
        p = float(close_series(db, s, adjusted=False).iloc[-1])
        db.add(T(s, "buy", 100 / p, p, ago(60 + i)))
    db.commit()
    levels = {i["level"] for i in pf.summarize(db)["checkup"]}
    assert "good" not in levels or "high" not in levels


def test_history_tracks_value_and_money_put_in(db):
    db.add_all([T("RELIANCE", "buy", 10, 100, ago(100)), T("TCS", "buy", 5, 200, ago(50))])
    db.commit()
    h = pf.history(db)["points"]
    assert h[0]["put_in"] == pytest.approx(1000) and h[-1]["put_in"] == pytest.approx(2000) and h[-1]["value"] > 0
    assert [p["date"] for p in h] == sorted(p["date"] for p in h) and pf.history.__name__ == "history"


def test_api_add_bulk_delete_rules_and_refresh(client, db):
    ok = client.post("/portfolio/transactions", json={"symbol": "reliance", "side": "buy", "qty": 10, "price": 100, "date": ago(120), "fees": 5})
    assert ok.status_code == 201 and ok.json()["added"] == 1
    assert client.post("/portfolio/transactions", json={"symbol": "RELIANCE", "side": "sell", "qty": 99, "price": 100, "date": ago(10)}).status_code == 422
    assert client.post("/portfolio/transactions", json={"symbol": "X", "side": "buy", "qty": 1, "price": 1, "date": "2999-01-01"}).status_code == 422
    assert client.post("/portfolio/transactions", json={"symbol": "X", "side": "buy", "qty": -1, "price": 1, "date": ago(1)}).status_code == 422
    bulk = client.post("/portfolio/transactions", json={"transactions": [
        {"symbol": "TCS", "side": "buy", "qty": 4, "price": 50, "date": ago(90)}, {"symbol": "TCS", "side": "sell", "qty": 1, "price": 60, "date": ago(30)}]})
    assert bulk.status_code == 201 and bulk.json()["added"] == 2
    bad_bulk = client.post("/portfolio/transactions", json={"transactions": [
        {"symbol": "INFY", "side": "buy", "qty": 1, "price": 5, "date": ago(9)}, {"symbol": "INFY", "side": "sell", "qty": 5, "price": 5, "date": ago(8)}]})
    assert bad_bulk.status_code == 422 and not [t for t in client.get("/portfolio/transactions").json() if t["symbol"] == "INFY"]       # all or nothing
    p = client.get("/portfolio").json()
    assert not p["empty"] and p["summary"]["holdings"] == 2 and p["positions"][0]["name"]
    txns = client.get("/portfolio/transactions").json()
    buy_tcs = next(t for t in txns if t["symbol"] == "TCS" and t["side"] == "buy")
    assert client.delete(f"/portfolio/transactions/{buy_tcs['id']}").status_code == 409                       # a later sale depends on it
    assert client.delete("/portfolio/transactions/9999").status_code == 404
    assert client.get("/portfolio/history").json()["points"]
    r = client.post("/portfolio/refresh").json()
    assert r["refreshed"] >= 1
    sell = next(t for t in txns if t["side"] == "sell")
    assert client.delete(f"/portfolio/transactions/{sell['id']}").status_code == 200
