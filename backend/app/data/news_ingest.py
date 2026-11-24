"""News ingestion: fetch from all configured providers, dedupe, resolve tickers, score once."""
from __future__ import annotations

import asyncio
import hashlib
import logging
import re
import time
from collections.abc import Callable
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.data.models import Article, ArticleScore, ArticleTicker, ProviderHealth
from app.nlp.entities import AliasResolver
from app.nlp.scoring import Scorer
from app.providers.base import NewsProvider, NewsQuery, RawArticle, retry_with_backoff

log = logging.getLogger("quantlens.news")
TRACKING = re.compile(r"^(utm_|fbclid|gclid|mc_|ref$|ref_|cmpid|ocid|guccounter)", re.I)


def normalize_url(url: str) -> str:
    """Lower-case host, drop 'www.', tracking params, fragment and trailing slash; sort the query."""
    u = urlsplit(url.strip())
    host = u.netloc.lower().removeprefix("www.")
    q = sorted((k, v) for k, v in parse_qsl(u.query) if not TRACKING.match(k))
    return urlunsplit((u.scheme.lower(), host, u.path.rstrip("/") or "/", urlencode(q), ""))


def _h(s: str) -> str:
    return hashlib.sha1(s.encode()).hexdigest()[:16]


def article_id(url: str) -> str:
    return _h(normalize_url(url))


def title_hash(title: str) -> str:
    return _h(re.sub(r"[^a-z0-9]+", " ", title.lower()).strip())


def store_articles(db: Session, raws: list[RawArticle], resolver: AliasResolver, query_symbol: str | None = None) -> dict:
    """Insert new articles (dedupe by normalized URL and by title hash), tag tickers. Returns counts."""
    new = dup = 0
    now = int(time.time())
    for r in raws:
        aid, th = article_id(r.url), title_hash(r.title)
        existing = db.get(Article, aid) or db.scalar(select(Article).where(Article.title_hash == th))
        syms = resolver.resolve(f"{r.title}. {r.summary}", set(r.tickers) | ({query_symbol} if query_symbol else set()))
        if existing:
            dup += 1
            aid = existing.id
        else:
            db.add(Article(id=aid, title_hash=th, url=r.url, title=r.title.strip(), summary=r.summary[:1000],
                           source=r.source, provider=r.provider, published=r.published, fetched=now,
                           provider_score=r.provider_score))
            new += 1
        have = set(db.scalars(select(ArticleTicker.symbol).where(ArticleTicker.article_id == aid)))
        for s in syms - have:
            db.add(ArticleTicker(article_id=aid, symbol=s))
        db.flush()
    db.commit()
    return {"new": new, "duplicates": dup}


def score_pending(db: Session, scorer: Scorer, limit: int = 2000) -> int:
    """Score every article that has no score yet from this model (never scores twice)."""
    done = select(ArticleScore.article_id).where(ArticleScore.model == scorer.name)
    arts = db.scalars(select(Article).where(Article.id.not_in(done)).limit(limit)).all()
    if not arts:
        return 0
    probs = scorer.score([f"{a.title}. {a.summary[:300]}" for a in arts])
    now = int(time.time())
    for a, p in zip(arts, probs, strict=True):
        db.add(ArticleScore(article_id=a.id, model=scorer.name, pos=p.pos, neg=p.neg, neu=p.neu,
                            score=p.score, scored_at=now))
    db.commit()
    return len(arts)


class NewsRouter:
    """Queries every configured provider concurrently; one failing provider never breaks the rest."""

    def __init__(self, providers: list[NewsProvider], db_factory: Callable | None = None) -> None:  # type: ignore[type-arg]
        self.providers = providers
        self.db_factory = db_factory

    def _calls_today(self, name: str) -> int:
        if not self.db_factory:
            return 0
        from datetime import datetime  # noqa: PLC0415

        from app.data import calendar as cal  # noqa: PLC0415
        with self.db_factory() as db:
            h = db.get(ProviderHealth, name)
            return h.calls_today if h and h.day == datetime.now(cal.IST).strftime("%Y-%m-%d") else 0

    def _record(self, name: str, err: str | None) -> None:
        if self.db_factory:
            from app.data.prices import record_health  # noqa: PLC0415
            record_health(self.db_factory, name, err)

    async def _one(self, p: NewsProvider, q: NewsQuery) -> tuple[str, list[RawArticle], str | None]:
        if p.daily_budget is not None and self._calls_today(p.name) >= p.daily_budget:
            return p.name, [], f"daily budget of {p.daily_budget} calls used"
        try:
            await p.limiter.acquire()
            arts = await retry_with_backoff(lambda: p.fetch(q), attempts=2)
            self._record(p.name, None)
            return p.name, arts, None
        except Exception as e:  # noqa: BLE001
            msg = f"{type(e).__name__}: {e}"
            self._record(p.name, msg)
            log.warning("news provider %s failed for %s: %s", p.name, q.symbol, msg)
            return p.name, [], msg

    async def fetch_all(self, q: NewsQuery) -> tuple[list[RawArticle], dict[str, str]]:
        active = [p for p in self.providers if p.is_configured()]
        res = await asyncio.gather(*(self._one(p, q) for p in active))
        errors = {n: e for n, _, e in res if e}
        return [a for _, arts, _ in res for a in arts], errors


async def ingest_symbol(db: Session, router: NewsRouter, resolver: AliasResolver, scorer: Scorer,
                        symbol: str, company: str, days: int = 7) -> dict:
    raws, errors = await router.fetch_all(NewsQuery(symbol, company, days))
    counts = store_articles(db, raws, resolver, symbol)
    scored = await asyncio.to_thread(score_pending, db, scorer)
    return {"symbol": symbol, "fetched": len(raws), **counts, "scored": scored, "model": scorer.name, "errors": errors}
