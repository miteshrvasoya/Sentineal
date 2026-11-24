"""Providers against hand-written fixtures shaped like each API's documented response.
These shapes are from memory of the public docs and are NOT verified against live APIs."""
import json

import httpx
import pytest

from app.providers.alphavantage import AlphaVantageProvider
from app.providers.base import NewsQuery, ProviderError, RateLimitedError
from app.providers.finnhub import FinnhubProvider
from app.providers.gdelt import GdeltProvider
from app.providers.gnews_rss import GoogleNewsRssProvider
from app.providers.marketaux import MarketauxProvider
from app.providers.news_util import bare_symbol, parse_ts
from app.providers.newsapi import NewsApiProvider

Q = NewsQuery("RELIANCE", "Reliance Industries", 7)


def client(handler):
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def reply(body, status=200, text=None):
    return lambda req: httpx.Response(status, json=body) if text is None else httpx.Response(status, text=text)


async def test_finnhub():
    body = [{"headline": "Reliance Q2 profit up", "summary": "<p>Strong</p>", "url": "https://x.com/a", "source": "Reuters", "datetime": 1767571200}]
    seen = {}
    def h(req):
        seen.update(dict(req.url.params))
        return httpx.Response(200, json=body)
    a = (await FinnhubProvider(client(h), key="K").fetch(Q))[0]
    assert a.title == "Reliance Q2 profit up" and a.summary == "Strong" and a.published == 1767571200 and a.tickers == ["RELIANCE"]
    assert seen["symbol"] == "RELIANCE.NS" and seen["token"] == "K"


async def test_marketaux_entity_sentiment_and_tickers():
    body = {"data": [{"title": "Reliance and TCS rally", "description": "d", "url": "https://m.com/1", "source": "m.com",
                      "published_at": "2026-01-05T09:30:00.000000Z",
                      "entities": [{"symbol": "RELIANCE.NSE", "sentiment_score": 0.6}, {"symbol": "TCS.NSE", "sentiment_score": -0.2}]}]}
    a = (await MarketauxProvider(client(reply(body)), key="K").fetch(Q))[0]
    assert a.provider_score == pytest.approx(0.6) and set(a.tickers) == {"RELIANCE", "TCS"}
    assert a.published == parse_ts("2026-01-05T09:30:00Z")


GNEWS = """<?xml version="1.0"?><rss><channel>
<item><title>Reliance shares jump on Jio listing buzz - Mint</title><link>https://news.google.com/rss/articles/AAA</link>
<pubDate>Mon, 05 Jan 2026 09:30:00 GMT</pubDate><description>&lt;a href="x"&gt;Reliance shares jump&lt;/a&gt;</description><source url="https://mint.com">Mint</source></item>
<item><title>No link item</title></item></channel></rss>"""


async def test_gnews_rss_parses_and_strips_source_suffix():
    arts = await GoogleNewsRssProvider(client(reply(None, text=GNEWS))).fetch(Q)
    assert len(arts) == 1 and arts[0].title == "Reliance shares jump on Jio listing buzz" and arts[0].source == "Mint"
    assert arts[0].summary == "Reliance shares jump" and arts[0].published == parse_ts("Mon, 05 Jan 2026 09:30:00 GMT")


async def test_gnews_invalid_xml():
    with pytest.raises(ProviderError, match="invalid XML"):
        await GoogleNewsRssProvider(client(reply(None, text="<rss><oops"))).fetch(Q)


async def test_gdelt_and_non_json():
    body = {"articles": [{"url": "https://g.com/1", "title": "Reliance ramps up", "seendate": "20260105T093000Z", "domain": "g.com"}]}
    a = (await GdeltProvider(client(reply(body))).fetch(Q))[0]
    assert a.published == parse_ts("2026-01-05T09:30:00Z") and a.source == "g.com"
    with pytest.raises(ProviderError, match="non-JSON"):
        await GdeltProvider(client(reply(None, text="Please limit requests"))).fetch(Q)


async def test_alphavantage_score_and_quota_notice():
    body = {"feed": [{"title": "t", "url": "https://a.com/1", "time_published": "20260105T093000", "summary": "s",
                      "source": "AV", "overall_sentiment_score": 0.21}]}
    a = (await AlphaVantageProvider(client(reply(body)), key="K").fetch(Q))[0]
    assert a.provider_score == 0.21 and a.published == parse_ts("2026-01-05T09:30:00Z")
    with pytest.raises(ProviderError, match="quota"):
        await AlphaVantageProvider(client(reply({"Information": "rate limit"})), key="K").fetch(Q)


async def test_newsapi_skips_removed():
    body = {"articles": [{"title": "Reliance deal", "url": "https://n.com/1", "publishedAt": "2026-01-05T09:30:00Z",
                          "source": {"name": "N"}, "description": None}, {"title": "[Removed]", "url": "https://removed.com"}]}
    arts = await NewsApiProvider(client(reply(body)), key="K").fetch(Q)
    assert len(arts) == 1 and arts[0].source == "N" and arts[0].summary == ""


async def test_403_is_rate_limit_and_keys_never_leak_in_errors():
    with pytest.raises(RateLimitedError):
        await MarketauxProvider(client(reply({}, status=403)), key="SECRETKEY").fetch(Q)

    def boom(req):
        raise httpx.ConnectError("failed for " + str(req.url))
    with pytest.raises(ProviderError) as e:
        await FinnhubProvider(client(boom), key="SECRETKEY").fetch(Q)
    assert "SECRETKEY" not in str(e.value)


def test_keyed_providers_unconfigured_without_key():
    assert not FinnhubProvider(key="").is_configured() and not MarketauxProvider(key=None).is_configured()
    assert GoogleNewsRssProvider().is_configured() and GdeltProvider().is_configured()


def test_symbol_and_time_helpers():
    assert bare_symbol("RELIANCE.NSE") == "RELIANCE" and bare_symbol("NSE:TCS") == "TCS" and bare_symbol("infy.ns") == "INFY"
    assert parse_ts("20260105T093000Z") == parse_ts("2026-01-05T09:30:00+00:00") == parse_ts("Mon, 05 Jan 2026 09:30:00 +0000")
    json.dumps(bare_symbol("X"))
