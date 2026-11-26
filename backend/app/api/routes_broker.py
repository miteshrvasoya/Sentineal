"""Angel One connection: status, read-only holdings sync, and saving imported holdings into your own records."""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app import broker
from app import portfolio as pf
from app.api.routes_fund import get_fund_provider, load_fundamentals
from app.data.db import get_session
from app.deps import get_angel, get_router

router = APIRouter()


async def refresh_holding_data(db: Session, symbols: list[str], r, fprov) -> dict:  # type: ignore[no-untyped-def]
    """Fetch prices (and company financials) for stocks you own so every screen and calculation includes them."""
    from app.data.ingest import backfill_many
    from app.screener import engine as scr
    prices = await backfill_many(db, r, symbols, "1d")
    funds_failed = []
    for s in symbols:
        try:
            await load_fundamentals(db, fprov, s)
        except Exception:  # noqa: BLE001  financials are a bonus
            funds_failed.append(s)
    scr._cache.clear()
    return {"price_problems": [x["symbol"] for x in prices if not x.get("ok")], "financials_missing": funds_failed}


@router.get("/broker/angelone/status")
def get_status(db: Session = Depends(get_session), angel=Depends(get_angel)) -> dict:  # type: ignore[no-untyped-def]
    return broker.status(db, angel)


@router.post("/broker/angelone/sync")
async def sync(db: Session = Depends(get_session), angel=Depends(get_angel), r=Depends(get_router), fprov=Depends(get_fund_provider)) -> dict:  # type: ignore[no-untyped-def]
    res = await broker.sync(db, angel)
    if res.get("ok"):
        res["data"] = await refresh_holding_data(db, pf.holding_symbols(db), r, fprov)
    return res


class Adopt(BaseModel):
    date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")


@router.post("/broker/angelone/adopt")
def adopt(body: Adopt, db: Session = Depends(get_session)) -> dict:
    """Add the broker-only holdings to your own records as purchases dated `date` (the broker feed has no purchase dates)."""
    if body.date > datetime.now().date().isoformat():
        raise HTTPException(422, "the date is in the future")
    try:
        n = pf.adopt_broker(db, body.date)
    except pf.PortfolioError as e:
        raise HTTPException(422, str(e)) from e
    return {"added": n}
