"""NewsAPI.org (optional; free tier: 100 req/day, ~24h delayed, development use only)."""
from datetime import UTC, datetime, timedelta

from app.providers.base import NewsProvider, NewsQuery, RawArticle
from app.providers.news_util import parse_ts


class NewsApiProvider(NewsProvider):
    name = "newsapi"
    rate_limit = (5, 60.0)
    daily_budget = 100
    key_env = "NEWSAPI_KEY"

    async def fetch(self, q: NewsQuery) -> list[RawArticle]:
        r = await self._get("https://newsapi.org/v2/everything", {
            "q": f'"{q.company}"', "language": "en", "sortBy": "publishedAt", "pageSize": 50,
            "from": (datetime.now(UTC) - timedelta(days=min(q.days, 30))).strftime("%Y-%m-%d"), "apiKey": self.key})
        return [RawArticle(url=a["url"], title=a["title"], summary=a.get("description") or "",
                           source=(a.get("source") or {}).get("name", ""), published=parse_ts(a["publishedAt"]),
                           provider=self.name, tickers=[q.symbol])
                for a in r.json().get("articles", []) if a.get("url") and a.get("title") and a["title"] != "[Removed]"]
