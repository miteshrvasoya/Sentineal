import pytest

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


def test_news_and_sentiment_endpoints(client):
    import time

    from app.data.db import get_session
    from app.data.news_ingest import NewsRouter
    from app.data.prices import upsert_prices
    from app.deps import get_news_router
    from app.main import app
    from app.nlp import factory
    from app.nlp.vader import VaderScorer
    from app.providers.base import RawArticle
    from tests.conftest import make_frame
    from tests.test_news_ingest import FakeNews

    factory.set_scorer(VaderScorer())
    now = int(time.time())
    titles = ["Reliance Industries profit surges to record", "Reliance Industries faces probe, shares plunge",
              "Reliance Industries announces new plant"]
    arts = [RawArticle(url=f"https://n.com/{i}", title=f"{titles[i % 3]} #{i}", published=now - i * 86400 // 2, provider="fake")
            for i in range(60)]
    app.dependency_overrides[get_news_router] = lambda: NewsRouter([FakeNews("fake", arts)])
    upsert_prices(next(get_session()), "RELIANCE", "1d", make_frame(120), "fake")

    assert client.get("/news/RELIANCE").json()["count"] == 0
    assert client.get("/sentiment/RELIANCE").status_code == 404
    r = client.post("/news/RELIANCE/refresh?days=30").json()
    assert r["new"] == 60 and r["scored"] == 60 and r["model"] == "vader"
    n = client.get("/news/RELIANCE?days=60&limit=5").json()
    assert n["count"] == 5 and n["model"] == "vader" and n["articles"][0]["label"] in ("positive", "negative", "neutral")
    assert "RELIANCE" in n["articles"][0]["tickers"]
    s = client.get("/sentiment/RELIANCE?days=60").json()
    assert s["n_articles"] > 30 and s["daily"] and len(s["lead_lag"]) == 11 and s["top_terms"]
    assert any("VADER" in x for x in s["notes"]) and {"mean_sent", "volume_z", "recency_weighted"} <= set(s["daily"][-1])
    m = client.get("/sentiment/market?days=60").json()
    assert m["model"] == "vader" and m["series"]
    app.dependency_overrides.pop(get_news_router, None)
    factory.set_scorer(None)


def _llm_setup(client, provider_cfg):
    """Seed a few stored articles and point the app at a scripted LLM router."""
    import time

    from app.data.db import get_session
    from app.data.news_ingest import score_pending, store_articles
    from app.deps import get_llm_router
    from app.main import app
    from app.nlp.entities import AliasResolver
    from app.nlp.vader import VaderScorer
    from app.providers.base import RawArticle
    from tests.llm.fakes import make_router

    db = next(get_session())
    now = int(time.time())
    arts = [RawArticle(url=f"https://n.com/{i}", title=t, published=now - 86400 * i, provider="t")
            for i, t in enumerate(["Reliance Industries posts record profit, shares surge", "Reliance Industries faces fraud probe, shares plunge",
                                   "Reliance Industries AGM date announced"])]
    store_articles(db, arts, AliasResolver(), "RELIANCE")
    score_pending(db, VaderScorer())
    router = make_router({"a": provider_cfg})
    app.dependency_overrides[get_llm_router] = lambda: router
    return router


def test_llm_endpoints_degrade_gracefully_with_no_provider(client):
    from app.deps import get_llm_router
    from app.main import app
    from tests.llm.fakes import Scripted
    _llm_setup(client, Scripted("a", configured=False))
    st = client.get("/llm/status").json()
    assert st["available"] is False and st["budget"]["token_budget"] > 0 and "AI-generated" in st["badge"]
    e = client.post("/llm/enrich/RELIANCE").json()
    assert e["available"] is False and "API key" in e["reason"]
    n = client.get("/news/RELIANCE/enriched").json()
    assert n["llm_available"] is False and n["count"] == 3 and n["articles"][0]["event_type"] is None and n["agreement"]["n"] == 0
    assert client.get("/llm/eval").status_code == 503
    assert client.get("/llm/usage").json()["today"]["tokens"] == 0
    app.dependency_overrides.pop(get_llm_router, None)


def test_llm_enrich_then_enriched_view_with_forward_only_flag(client):
    from app.data.models import ArticleEnrichment
    from app.deps import get_llm_router
    from app.main import app
    from tests.llm.fakes import Scripted, enrich_items, sent_items

    def responder(kw):
        return sent_items(kw["user"], 0.6) if "financial sentiment" in kw["system"] else enrich_items(kw["user"], materiality="high")
    _llm_setup(client, Scripted("a", responder=responder))
    r = client.post("/llm/enrich/RELIANCE").json()
    assert r["available"] and r["enrichment"]["processed"] == 3 and r["sentiment"]["scored"] == 3
    n = client.get("/news/RELIANCE/enriched?min_materiality=high").json()
    assert n["count"] == 3 and n["agreement"]["n"] == 3 and n["forward_start"] is not None
    a = n["articles"][0]
    assert a["event_type"] == "earnings" and a["materiality"] == "high" and a["llm_label"] == "positive" and a["summary"]
    # Articles published before LLM collection began are flagged not valid for backtesting.
    flags = {x["id"]: x["valid_for_backtest"] for x in n["articles"]}
    assert not all(flags.values())
    st = client.get("/llm/status").json()
    assert st["available"] and st["forward_start"] == n["forward_start"] and st["budget"]["tokens"] > 0
    usage = client.get("/llm/usage").json()
    assert usage["rows"] and {x["task"] for x in usage["rows"]} == {"news_enrich", "sentiment_llm"}
    # Hard budget: once exhausted the endpoint reports it instead of failing.
    app.dependency_overrides.pop(get_llm_router, None)
    assert db_has(ArticleEnrichment, 3)


def db_has(model, n):
    from app.data.db import get_session
    return len(next(get_session()).query(model).all()) == n


# ---------------- Phase 6: fundamentals, risk, scorecard ----------------

class FakeFund:
    name = "fake_fund"

    def __init__(self, sector="Energy", fail=False, eps=5.0):
        self.sector, self.fail, self.eps = sector, fail, eps

    async def fetch(self, symbol):
        from app.providers.base import ProviderError
        from tests.test_fundamentals import frames
        if self.fail:
            raise ProviderError("down")
        cur = {"Total Revenue": 1000.0, "Gross Profit": 400.0, "Operating Income": 150.0, "EBIT": 150.0, "EBITDA": 200.0, "Net Income": 100.0,
               "Total Assets": 1000.0, "Current Assets": 400.0, "Current Liabilities": 200.0, "Total Debt": 300.0,
               "Cash And Cash Equivalents": 100.0, "Stockholders Equity": 500.0, "Retained Earnings": 300.0,
               "Ordinary Shares Number": 100.0, "Operating Cash Flow": 150.0, "Capital Expenditure": -40.0,
               "Total Liabilities Net Minority Interest": 600.0}
        prev = {**cur, "Total Revenue": 800.0, "Net Income": 80.0}
        inc, bal, cf = frames(cur, prev)
        return {"info": {"currentPrice": 100.0, "marketCap": 10000.0, "sharesOutstanding": 100.0, "sector": self.sector,
                         "trailingEps": self.eps, "bookValue": 50.0, "dividendRate": 2.0}, "income": inc, "balance": bal, "cashflow": cf}


def _fund(prov):
    from app.api.routes_fund import get_fund_provider
    from app.main import app
    app.dependency_overrides[get_fund_provider] = lambda: prov


def test_fundamentals_endpoints(client):
    _fund(FakeFund())
    assert client.get("/fundamentals/TCS").status_code == 404
    r = client.post("/fundamentals/TCS/refresh").json()
    assert r["sector"] == "Energy" and r["fields_found"] >= 15 and r["has_prior_year"] is True
    f = client.get("/fundamentals/TCS").json()
    assert f["ratios"]["pe"] == 20 and f["ratios"]["roe"] == 0.2 and f["piotroski"]["evaluated"] >= 5 and f["altman"]["applicable"] is True
    assert f["graham"]["value"] == pytest.approx(75.0, abs=0.01)                                   # sqrt(22.5*5*50)
    assert any("Sector percentiles need" in n for n in f["notes"]) and f["percentiles"]["pe"]["percentile"] is None
    base = f["dcf"]["intrinsic_per_share"]
    assert base > 0 and f["dcf"]["assumptions"] == {"r": 0.12, "g1": 0.2, "g2": 0.05, "years": 5} and f["dcf_defaults"]["g1"] == 0.2
    hi = client.get("/fundamentals/TCS?r=0.10&g1=0.10&g2=0.04&years=7").json()["dcf"]
    assert hi["assumptions"]["years"] == 7 and hi["intrinsic_per_share"] != base
    assert client.get("/fundamentals/TCS?r=0.04&g2=0.05").status_code == 422
    assert client.get("/fundamentals/TCS?years=99").status_code == 422
    _fund(FakeFund(fail=True))
    assert client.post("/fundamentals/INFY/refresh").status_code == 502


def test_sector_percentiles_appear_with_enough_peers(client):
    _fund(FakeFund())
    for s in ("AAA", "BBB", "CCC", "DDD"):
        client.post(f"/fundamentals/{s}/refresh")
    f = client.get("/fundamentals/AAA").json()
    assert f["peers_used"] == 3 and f["percentiles"]["pe"]["percentile"] == 50.0                  # all peers tie -> half
    _fund(FakeFund(sector="IT"))
    client.post("/fundamentals/EEE/refresh")
    assert client.get("/fundamentals/EEE").json()["peers_used"] == 0                               # different sector


def _store(symbol, n, seed, drift=0.0004):
    import numpy as np
    import pandas as pd

    from app.data.db import get_session
    from app.data.prices import upsert_prices
    rng = np.random.default_rng(seed)
    c = 100 * np.cumprod(1 + rng.normal(drift, 0.01, n))
    idx = pd.date_range(end=pd.Timestamp.now(tz="UTC").normalize(), periods=n, freq="B", tz="UTC")
    df = pd.DataFrame({"open": c, "high": c * 1.005, "low": c * 0.995, "close": c, "adj_close": c, "volume": 1e5}, index=idx)
    upsert_prices(next(get_session()), symbol, "1d", df, "t")


def test_risk_endpoint_correlation_and_notes(client):
    _store("AAA", 400, 1)
    j = client.get("/risk/AAA").json()
    assert j["benchmark"] is None and any("Benchmark" in n for n in j["notes"]) and j["summary"]["vs_benchmark"] is None if "vs_benchmark" in j["summary"] else True
    _store("NIFTY 50", 400, 2)
    j = client.get("/risk/AAA?rf=0.05&window=40").json()
    s = j["summary"]
    assert j["benchmark"] == "NIFTY 50" and s["rf"] == 0.05 and s["vs_benchmark"]["beta"] is not None and s["max_drawdown"] <= 0
    assert s["var_99"]["historical_var"] >= s["var_95"]["historical_var"] > 0 and "Display only" in s["kelly"]["warning"]
    ser = j["series"]
    assert len(ser["dates"]) == len(ser["equity"]) == len(ser["drawdown"]) == len(ser["beta"]) and ser["equity"][0] == pytest.approx(100, abs=3)
    assert client.get("/risk/ZZZ").status_code == 404
    _store("BBB", 400, 3)
    m = client.get("/risk/correlation?symbols=AAA,BBB,NIFTY%2050").json()
    assert m["symbols"] == ["AAA", "BBB", "NIFTY 50"] and m["matrix"][0][0] == pytest.approx(1.0)
    assert client.get("/risk/correlation?symbols=AAA").status_code == 404


def test_scorecard_and_watchlist_summary(client):
    for s, seed in (("RELIANCE", 1), ("TCS", 2)):
        _store(s, 300, seed)
    sc = client.get("/scorecard/RELIANCE").json()
    assert sc["composite"] is not None and set(sc["subscores"]) == {"trend", "momentum", "volume_flow", "volatility", "sentiment", "valuation"}
    assert sc["subscores"]["valuation"]["score"] is None and "disclaimer" in sc
    assert client.get("/scorecard/NOPE").status_code == 404
    w = {x["symbol"]: x for x in client.get("/watchlist/summary").json()}
    assert w["RELIANCE"]["label"] in ("leaning positive", "leaning negative", "mixed") and len(w["RELIANCE"]["spark"]) == 30
    assert w["RELIANCE"]["change_pct"] is not None and w["INFY"]["last"] is None and w["INFY"]["label"] is None   # no data: blank, not an error
