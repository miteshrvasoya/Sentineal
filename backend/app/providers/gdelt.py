"""GDELT DOC 2.0 API (keyless): global news breadth. Query = company name, India-focused."""
from datetime import UTC, datetime, timedelta

from app.providers.base import NewsProvider, NewsQuery, ProviderError, RawArticle
from app.providers.news_util import parse_ts


class GdeltProvider(NewsProvider):
    name = "gdelt"
    rate_limit = (1, 6.0)  # GDELT asks for roughly one request per 5 seconds

    async def fetch(self, q: NewsQuery) -> list[RawArticle]:
        start = (datetime.now(UTC) - timedelta(days=min(q.days, 90))).strftime("%Y%m%d%H%M%S")
        r = await self._get("https://api.gdeltproject.org/api/v2/doc/doc", {
            "query": f'"{q.company}" sourcelang:english', "mode": "artlist", "format": "json",
            "maxrecords": 75, "startdatetime": start, "sort": "datedesc"})
        try:
            data = r.json()
        except ValueError:  # GDELT answers plain text on bad queries / throttling
            raise ProviderError(f"gdelt non-JSON reply: {r.text[:80]!r}") from None
        return [RawArticle(url=a["url"], title=a["title"], source=a.get("domain", ""),
                           published=parse_ts(a["seendate"]), provider=self.name, tickers=[q.symbol])
                for a in data.get("articles", []) if a.get("url") and a.get("title")]
