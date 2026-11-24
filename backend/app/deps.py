"""FastAPI dependencies: DB session and provider router (overridable in tests)."""
from functools import lru_cache

from app.data import db as dbmod
from app.data.prices import record_health
from app.providers.angelone import AngelOneProvider
from app.providers.base import ProviderRouter
from app.providers.yahoo import YahooProvider


def _session_ctx():  # type: ignore[no-untyped-def]
    if dbmod._SessionLocal is None:
        dbmod.init_engine()
    assert dbmod._SessionLocal is not None
    return dbmod._SessionLocal()


@lru_cache
def get_router() -> ProviderRouter:
    # Priority order. Angel One (Phase 2) is inserted ahead of Yahoo when configured.
    providers = [AngelOneProvider(), YahooProvider()]  # AngelOne skipped unless configured
    return ProviderRouter(
        providers,
        on_success=lambda n: record_health(_session_ctx, n, None),
        on_error=lambda n, m: record_health(_session_ctx, n, m),
    )


@lru_cache
def get_news_router():  # type: ignore[no-untyped-def]
    """All six news providers; the keyed ones are skipped unless a key is present."""
    from app.config import get_settings
    from app.data.news_ingest import NewsRouter
    from app.providers.alphavantage import AlphaVantageProvider
    from app.providers.finnhub import FinnhubProvider
    from app.providers.gdelt import GdeltProvider
    from app.providers.gnews_rss import GoogleNewsRssProvider
    from app.providers.marketaux import MarketauxProvider
    from app.providers.newsapi import NewsApiProvider

    s = get_settings()
    return NewsRouter([
        FinnhubProvider(key=s.finnhub_key), MarketauxProvider(key=s.marketaux_key),
        GoogleNewsRssProvider(), GdeltProvider(),
        AlphaVantageProvider(key=s.alphavantage_key), NewsApiProvider(key=s.newsapi_key),
    ], db_factory=_session_ctx)


@lru_cache
def get_llm_router():  # type: ignore[no-untyped-def]
    from app.llm.router import build_router
    return build_router(_session_ctx)
