"""Backfill 5y of daily bars plus 90 days of news (scored) for the default watchlist."""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.api.routes import symbol_table  # noqa: E402
from app.config import get_settings  # noqa: E402
from app.data import db  # noqa: E402
from app.data.ingest import backfill_many  # noqa: E402
from app.data.news_ingest import ingest_symbol  # noqa: E402
from app.deps import get_news_router, get_router  # noqa: E402
from app.nlp.entities import get_resolver  # noqa: E402
from app.nlp.factory import get_scorer  # noqa: E402


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


    # Fundamentals (Yahoo statements). Failures are reported, not fatal.
    import json as _json  # noqa: PLC0415,E401
    import time as _time

    from app.api.routes_fund import get_fund_provider  # noqa: PLC0415
    from app.data.models import FundamentalsSnapshot  # noqa: PLC0415
    from app.features import fundamentals as fd  # noqa: PLC0415
    from app.providers.base import ProviderError  # noqa: PLC0415

    for sym in get_settings().watchlist:
        try:
            raw = await get_fund_provider().fetch(sym)
            inp = fd.extract_inputs(sym, raw["info"], raw["income"], raw["balance"], raw["cashflow"], int(_time.time()))
            s.merge(FundamentalsSnapshot(symbol=sym, sector=inp.sector, fetched_at=inp.fetched_at, payload=_json.dumps(inp.to_dict())))
            s.commit()
            print({"fundamentals": sym, "sector": inp.sector})
        except ProviderError as e:
            print({"fundamentals": sym, "error": str(e)})


asyncio.run(main())
