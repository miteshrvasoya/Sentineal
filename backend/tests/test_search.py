"""Stock search: covers the whole NSE list, names, nicknames, typos; live fallback degrades quietly."""
import httpx
import pytest

from app import search as sr


def top(q, n=5):
    return [r["symbol"] for r in sr.search_local(q, n)]


def test_universe_covers_the_whole_nse_list_and_keeps_curated_sectors():
    u = {e.symbol: e for e in sr.universe()}
    assert len(u) > 2000 and u["RELIANCE"].sector == "Energy" and u["20MICRONS"].exchange == "NSE" and u["TCS"].featured and not u["20MICRONS"].featured


@pytest.mark.parametrize("q,expected", [
    ("INFY", "INFY"), ("infy", "INFY"), ("tata consultancy", "TCS"), ("tcs", "TCS"), ("state bank", "SBIN"), ("sbi", "SBIN"), ("hul", "HINDUNILVR"),
    ("zomato", "ETERNAL"), ("l&t", "LT"), ("larsen", "LT"), ("m&m", "M&M"), ("hdfc bank", "HDFCBANK"), ("irctc", "IRCTC"), ("20 microns", "20MICRONS"),
    ("relience", "RELIANCE"), ("infosis", "INFY"), ("ola electric", "OLAELEC"), ("sbi cards", "SBICARD"),
])
def test_names_nicknames_and_typos_find_the_right_stock_first(q, expected):
    assert top(q)[0] == expected, (q, top(q))


def test_obscure_listed_companies_are_searchable_not_only_the_curated_list():
    assert "IRCTC" in top("indian railway catering") and top("20 microns") == ["20MICRONS"]
    names = {r["symbol"] for q in ("a", "b", "c") for r in sr.search_local(q, 30)}
    assert len(names) > 30


def test_prefix_beats_substring_and_exact_beats_prefix():
    r = top("itc")
    assert r[0] == "ITC" and r.index("ITC") < r.index("NITCO") if "NITCO" in r else r[0] == "ITC"
    assert top("tata")[0] in {"TATASTEEL", "TATAMOTORS", "TCS", "TATACONSUM", "TATAPOWER", "TATACHEM", "TATAELXSI"}      # well-known first


def test_nonsense_returns_nothing_and_empty_query_returns_featured():
    assert sr.search_local("qzxwvv") == []
    f = sr.search_local("", 10)
    assert len(f) == 10 and all(r["sector"] for r in f)


def test_only_strong_matches_are_shown_when_they_exist():
    assert all(r["symbol"] in ("OLAELEC",) or sr.score_of(r, "ola electric") >= sr.STRONG for r in sr.search_local("ola electric", 10))


async def test_live_search_maps_nse_and_bse_and_survives_failure(monkeypatch):
    payload = {"quotes": [{"symbol": "NEWCO.NS", "exchange": "NSI", "quoteType": "EQUITY", "longname": "New Co Ltd"},
                          {"symbol": "500325.BO", "exchange": "BSE", "quoteType": "EQUITY", "shortname": "RELIANCE"},
                          {"symbol": "AAPL", "exchange": "NMS", "quoteType": "EQUITY", "shortname": "Apple"},
                          {"symbol": "X.NS", "exchange": "NSI", "quoteType": "OPTION"}]}

    class FakeClient:
        def __init__(self, *a, **k): ...
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def get(self, url, params=None):
            return httpx.Response(200, json=payload, request=httpx.Request("GET", url))
    monkeypatch.setattr(sr.httpx, "AsyncClient", FakeClient)
    sr._live_cache.clear()
    live = await sr.search_live("newco")
    assert [(r["symbol"], r["exchange"]) for r in live] == [("NEWCO", "NSE"), ("500325.BO", "BSE")]
    merged = await sr.search("newco", 10)
    assert "NEWCO" in [r["symbol"] for r in merged]

    class Boom(FakeClient):
        async def get(self, url, params=None):
            raise httpx.ConnectError("offline")
    monkeypatch.setattr(sr.httpx, "AsyncClient", Boom)
    sr._live_cache.clear()
    assert await sr.search_live("anything") == []
    assert [r["symbol"] for r in await sr.search("infy", 5)][0] == "INFY"                           # local results unaffected


def test_api_endpoint_returns_exchange_and_works_offline(client, monkeypatch):
    async def none(q, limit=8, timeout=2.5):
        return []
    monkeypatch.setattr(sr, "search_live", none)
    r = client.get("/symbols/search?q=tata motors&limit=5").json()
    assert r[0]["exchange"] == "NSE" and r[0]["symbol"] and len(r) <= 5
    assert client.get("/symbols/search?q=").json()
    assert client.get("/symbols/search?q=zomato").json()[0]["symbol"] == "ETERNAL"
    assert client.get("/symbols/search?q=" + "x" * 100).status_code == 422
