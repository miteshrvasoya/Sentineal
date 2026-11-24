"""Google News RSS (keyless). One query per company; `when:Nd` limits recency."""
import xml.etree.ElementTree as ET  # noqa: S405  (feed from a fixed trusted host; no entity expansion of local files)

from app.providers.base import NewsProvider, NewsQuery, ProviderError, RawArticle
from app.providers.news_util import parse_ts, strip_html


class GoogleNewsRssProvider(NewsProvider):
    name = "gnews"
    rate_limit = (10, 60.0)

    async def fetch(self, q: NewsQuery) -> list[RawArticle]:
        r = await self._get("https://news.google.com/rss/search", {
            "q": f'"{q.company}" stock when:{max(1, q.days)}d', "hl": "en-IN", "gl": "IN", "ceid": "IN:en"})
        try:
            root = ET.fromstring(r.content)  # noqa: S314
        except ET.ParseError as e:
            raise ProviderError(f"gnews returned invalid XML: {e}") from None
        out = []
        for it in root.iter("item"):
            title, link, pub = it.findtext("title"), it.findtext("link"), it.findtext("pubDate")
            if not (title and link and pub):
                continue
            src = it.findtext("source") or ""
            if src and title.endswith(f" - {src}"):
                title = title[: -len(src) - 3]
            out.append(RawArticle(url=link, title=title.strip(), summary=strip_html(it.findtext("description") or ""),
                                  source=src, published=parse_ts(pub), provider=self.name, tickers=[q.symbol]))
        return out
