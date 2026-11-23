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
