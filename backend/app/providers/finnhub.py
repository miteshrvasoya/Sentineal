"""Finnhub company news (free tier ~60 calls/min). Its news-sentiment endpoint is premium, so we
score locally. NOTE: Indian-exchange coverage on the free plan is limited; failures degrade gracefully."""
from datetime import UTC, datetime, timedelta

from app.providers.base import NewsProvider, NewsQuery, RawArticle
from app.providers.news_util import strip_html


class FinnhubProvider(NewsProvider):
    name = "finnhub"
    rate_limit = (60, 60.0)
    key_env = "FINNHUB_KEY"

    async def fetch(self, q: NewsQuery) -> list[RawArticle]:
        end = datetime.now(UTC).date()
        r = await self._get("https://finnhub.io/api/v1/company-news", {
            "symbol": f"{q.symbol}.NS", "from": (end - timedelta(days=q.days)).isoformat(),
            "to": end.isoformat(), "token": self.key})
        return [RawArticle(url=a["url"], title=a["headline"], summary=strip_html(a.get("summary", "")),
                           source=a.get("source", ""), published=int(a["datetime"]), provider=self.name,
                           tickers=[q.symbol])
                for a in r.json() if a.get("url") and a.get("headline")]
