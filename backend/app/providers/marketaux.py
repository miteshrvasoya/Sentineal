"""Marketaux (free: 100 requests/day, ticker-tagged, entity sentiment)."""
from datetime import UTC, datetime, timedelta

from app.providers.base import NewsProvider, NewsQuery, RawArticle
from app.providers.news_util import bare_symbol, parse_ts


class MarketauxProvider(NewsProvider):
    name = "marketaux"
    rate_limit = (5, 60.0)
    daily_budget = 100
    key_env = "MARKETAUX_KEY"

    async def fetch(self, q: NewsQuery) -> list[RawArticle]:
        after = (datetime.now(UTC) - timedelta(days=q.days)).strftime("%Y-%m-%dT%H:%M")
        r = await self._get("https://api.marketaux.com/v1/news/all", {
            "symbols": f"{q.symbol}.NSE", "filter_entities": "true", "language": "en",
            "published_after": after, "limit": 50, "api_token": self.key})
        out = []
        for a in r.json().get("data", []):
            ents = a.get("entities") or []
            mine = [e for e in ents if bare_symbol(e.get("symbol", "")) == q.symbol]
            scores = [e["sentiment_score"] for e in mine if e.get("sentiment_score") is not None]
            out.append(RawArticle(
                url=a["url"], title=a["title"], summary=a.get("description") or "", source=a.get("source", ""),
                published=parse_ts(a["published_at"]), provider=self.name,
                provider_score=sum(scores) / len(scores) if scores else None,
                tickers=[bare_symbol(e["symbol"]) for e in ents if e.get("symbol")]))
        return out
