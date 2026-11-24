"""Alpha Vantage NEWS_SENTIMENT (optional; free tier is ~25 calls/day). Mostly US-ticker oriented."""
from app.providers.base import NewsProvider, NewsQuery, ProviderError, RawArticle
from app.providers.news_util import parse_ts


class AlphaVantageProvider(NewsProvider):
    name = "alphavantage"
    rate_limit = (5, 60.0)
    daily_budget = 25
    key_env = "ALPHAVANTAGE_KEY"

    async def fetch(self, q: NewsQuery) -> list[RawArticle]:
        r = await self._get("https://www.alphavantage.co/query", {
            "function": "NEWS_SENTIMENT", "tickers": f"NSE:{q.symbol}", "limit": 100, "apikey": self.key})
        j = r.json()
        if "Note" in j or "Information" in j:   # quota / premium notices arrive as HTTP 200
            raise ProviderError("alphavantage quota or plan limit reached")
        out = []
        for a in j.get("feed", []):
            out.append(RawArticle(url=a["url"], title=a["title"], summary=a.get("summary", ""),
                                  source=a.get("source", ""), published=parse_ts(a["time_published"]),
                                  provider=self.name, provider_score=a.get("overall_sentiment_score"),
                                  tickers=[q.symbol]))
        return out
