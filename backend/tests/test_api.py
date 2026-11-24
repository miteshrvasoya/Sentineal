
from app.deps import get_router
from app.main import app
from app.providers.base import ProviderRouter
from tests.conftest import FakeProvider


def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200 and r.json()["status"] == "ok"


def test_prices_fetch_store_and_adjust(client, fake):
    r = client.get("/prices/reliance?interval=1d&adjusted=false")
    assert r.status_code == 200
    j = r.json()
    assert j["symbol"] == "RELIANCE" and j["count"] == 60 and j["source"] == "fake"
    raw_close = j["bars"][-1]["c"]
    adj = client.get("/prices/RELIANCE?interval=1d&adjusted=true").json()["bars"][-1]["c"]
    assert abs(adj - raw_close * 0.98) < 1e-6
    # second call served from DB (fresh) -> no extra provider call
    calls = fake.calls
    client.get("/prices/RELIANCE?interval=1d")
    assert fake.calls == calls


def test_prices_bad_interval_and_date(client):
    assert client.get("/prices/TCS?interval=2d").status_code == 422
    assert client.get("/prices/TCS?from=notadate").status_code == 422


def test_prices_provider_down_no_cache_gives_clear_error(client):
    bad = ProviderRouter([FakeProvider("down", fail=True)])
    app.dependency_overrides[get_router] = lambda: bad
    r = client.get("/prices/INFY")
    assert r.status_code == 502 and "down" in r.json()["detail"]


def test_prices_provider_down_serves_cache_with_warning(client):
    client.get("/prices/SBIN?interval=1d")
    bad = ProviderRouter([FakeProvider("down", fail=True)])
    app.dependency_overrides[get_router] = lambda: bad
    r = client.get("/prices/SBIN?interval=1d&refresh=true")
    assert r.status_code == 200 and r.json()["warnings"]


def test_limit_caps_bars(client):
    j = client.get("/prices/ITC?limit=10").json()
    assert j["count"] == 10 and j["downsampled"] is True


def test_quote_and_search_and_watchlist(client):
    q = client.get("/quote/TCS").json()
    assert q["change_pct"] == 1.0
    assert client.get("/symbols/search?q=hdfc").json()[0]["symbol"] == "HDFCBANK"
    assert "RELIANCE" in client.get("/watchlist").json()
    assert "ZOMATO" in client.post("/watchlist", json={"symbol": "zomato"}).json()
    assert "ZOMATO" not in client.delete("/watchlist/ZOMATO").json()


def test_providers_health_shape(client):
    r = client.get("/providers/health").json()
    assert r[0]["name"] == "fake" and "calls_today" in r[0]


def test_indicators_endpoint(client):
    from app.data.db import get_session
    from app.data.prices import upsert_prices
    from tests.conftest import make_frame
    upsert_prices(next(get_session()), "TCS", "1d", make_frame(300), "fake")
    j = client.get("/indicators/tcs?set=momentum,trend&limit=50").json()
    assert len(j["t"]) == 50 and len(j["series"]["rsi"]) == 50 and 0 <= j["latest"]["rsi"] <= 100
    assert "feature_hash" in j and "macd" in j["series"]
    j2 = client.get('/indicators/tcs?set=momentum&params={"momentum":{"rsi_period":7}}').json()
    assert j2["latest"]["rsi"] != j["latest"]["rsi"]
    assert client.get("/indicators/tcs?set=nope").status_code == 422
    assert client.get("/indicators/tcs?params=%7Bbad").status_code == 422
    assert client.get("/indicators/ZZZ").status_code == 404


def test_structure_and_patterns_endpoints(client):
    from app.data.db import get_session
    from app.data.prices import upsert_prices
    from tests.conftest import make_frame
    upsert_prices(next(get_session()), "TCS", "1d", make_frame(400), "fake")
    s = client.get("/structure/tcs?limit=300").json()
    for key in ("swings", "events", "fvg", "order_blocks", "sr_zones", "pivots", "volume_profile", "fibonacci", "wyckoff", "trend"):
        assert key in s
    assert all(sw["confirmed_t"] >= sw["t"] for sw in s["swings"])
    p = client.get("/patterns/tcs").json()
    assert len(p["stats"]) == 13 and p["notes"] and isinstance(p["recent"], list)
    assert client.get("/structure/tcs?interval=9d").status_code == 422
    assert client.get("/structure/NOPE").status_code == 404
    assert client.get("/patterns/NOPE").status_code == 404
