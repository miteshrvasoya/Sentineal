"""Backfill 5y of daily bars for the default watchlist (news backfill arrives in Phase 5)."""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import get_settings  # noqa: E402
from app.data import db  # noqa: E402
from app.data.prices import ensure_prices  # noqa: E402
from app.deps import get_router  # noqa: E402
from app.providers.base import ProviderError  # noqa: E402


async def main() -> None:
    db.init_engine()
    s = next(db.get_session())
    router = get_router()
    for sym in get_settings().watchlist + ["NIFTY 50", "INDIA VIX"]:
        try:
            res = await ensure_prices(s, router, sym, "1d", force=True)
            print(f"{sym}: {len(res.df) if res else 0} bars from {res.source if res else 'cache'}")
        except ProviderError as e:
            print(f"{sym}: FAILED {e}")


asyncio.run(main())
