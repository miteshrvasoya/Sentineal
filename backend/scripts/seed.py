"""Backfill 5y of daily bars plus 90 days of news (scored) for the default watchlist."""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import get_settings  # noqa: E402
from app.api.routes import symbol_table  # noqa: E402
from app.data import db  # noqa: E402
from app.data.news_ingest import ingest_symbol  # noqa: E402
from app.nlp.entities import get_resolver  # noqa: E402
from app.nlp.factory import get_scorer  # noqa: E402
from app.data.ingest import backfill_many  # noqa: E402
from app.deps import get_news_router, get_router  # noqa: E402


async def main() -> None:
    db.init_engine()
    s = next(db.get_session())
    for r in await backfill_many(s, get_router(), get_settings().watchlist + ["NIFTY 50", "INDIA VIX"], "1d"):
        print(r)
    # 90 days of news for the default stocks (providers that are unreachable are reported, not fatal).
    names = {x.symbol: x.name for x in symbol_table()}
    for sym in get_settings().watchlist:
        out = await ingest_symbol(s, get_news_router(), get_resolver(), get_scorer(), sym, names.get(sym, sym), 90)
        print({k: v for k, v in out.items()})


asyncio.run(main())
