"""Backfill 5y of daily bars for the default watchlist (news backfill arrives in Phase 5)."""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import get_settings  # noqa: E402
from app.data import db  # noqa: E402
from app.data.ingest import backfill_many  # noqa: E402
from app.deps import get_router  # noqa: E402


async def main() -> None:
    db.init_engine()
    s = next(db.get_session())
    for r in await backfill_many(s, get_router(), get_settings().watchlist + ["NIFTY 50", "INDIA VIX"], "1d"):
        print(r)


asyncio.run(main())
