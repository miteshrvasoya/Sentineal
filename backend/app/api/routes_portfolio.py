"""My Investments: transactions, positions, profit and loss, history and check-up."""
from __future__ import annotations

import time
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import portfolio as pf
from app.api.routes_fund import clean
from app.data.db import get_session
from app.data.models import PortfolioTxn
from app.deps import get_router

router = APIRouter()


class TxnIn(BaseModel):
    symbol: str = Field(min_length=1, max_length=32)
    side: str = Field(pattern="^(buy|sell)$")
    qty: float = Field(gt=0, le=1e9)
    price: float = Field(gt=0, le=1e8)
    date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    fees: float = Field(0.0, ge=0, le=1e8)
    note: str = Field("", max_length=300)


class Bulk(BaseModel):
    transactions: list[TxnIn] = Field(max_length=500)


def _row(t: PortfolioTxn) -> dict:
    return {"id": t.id, "symbol": t.symbol, "side": t.side, "qty": t.qty, "price": t.price, "fees": t.fees, "date": t.date, "note": t.note, "amount": t.qty * t.price}


def _to_orm(x: TxnIn) -> PortfolioTxn:
    return PortfolioTxn(symbol=x.symbol.upper().strip(), side=x.side, qty=x.qty, price=x.price, fees=x.fees, date=x.date, note=x.note.strip(), created=int(time.time()))


async def _fetch_prices(db: Session, symbols: list[str], r) -> list[dict]:  # type: ignore[no-untyped-def]
    from app.data.ingest import backfill_many
    try:
        return await backfill_many(db, r, symbols, "1d")
    except Exception as e:  # noqa: BLE001  saving the transaction must never fail because a price provider is down
        return [{"symbol": s, "ok": False, "error": str(e)[:100]} for s in symbols]


@router.get("/portfolio")
def get_portfolio(db: Session = Depends(get_session)) -> dict:
    return clean(pf.summarize(db))


@router.get("/portfolio/history")
def get_history(db: Session = Depends(get_session)) -> dict:
    return clean(pf.history(db))


@router.get("/portfolio/transactions")
def list_txns(db: Session = Depends(get_session)) -> list[dict]:
    return [_row(t) for t in sorted(db.scalars(select(PortfolioTxn)), key=lambda t: (t.date, t.id), reverse=True)]


@router.post("/portfolio/transactions", status_code=201)
async def add_txn(body: Bulk | TxnIn, db: Session = Depends(get_session), r=Depends(get_router)) -> dict:  # type: ignore[no-untyped-def]
    items = body.transactions if isinstance(body, Bulk) else [body]
    new = [_to_orm(x) for x in items]
    existing = list(db.scalars(select(PortfolioTxn)))
    try:
        pf.validate_new(existing, new)
    except pf.PortfolioError as e:
        raise HTTPException(422, str(e)) from e
    db.add_all(new)
    db.commit()
    syms = sorted({t.symbol for t in new})
    fetched = await _fetch_prices(db, syms, r)
    missing = [f["symbol"] for f in fetched if not f.get("ok")]
    return {"added": len(new), "ids": [t.id for t in new], "price_problems": missing,
            "message": "Saved." + (f" Could not fetch prices for {', '.join(missing)} yet (check the symbol or your internet connection); use Refresh prices later." if missing else "")}


@router.delete("/portfolio/transactions/{txn_id}")
def delete_txn(txn_id: int, db: Session = Depends(get_session)) -> dict:
    t = db.get(PortfolioTxn, txn_id)
    if t is None:
        raise HTTPException(404, "no such transaction")
    rest = [x for x in db.scalars(select(PortfolioTxn)) if x.id != txn_id]
    try:
        pf.replay(rest)
    except pf.PortfolioError as e:
        raise HTTPException(409, f"Deleting this would make a later sale impossible. {e}") from e
    db.delete(t)
    db.commit()
    return {"deleted": txn_id}


@router.post("/portfolio/refresh")
async def refresh(db: Session = Depends(get_session), r=Depends(get_router)) -> dict:  # type: ignore[no-untyped-def]
    syms = sorted({t.symbol for t in db.scalars(select(PortfolioTxn))})
    if not syms:
        return {"refreshed": 0, "problems": []}
    res = await _fetch_prices(db, syms, r)
    from app.screener import engine as scr
    scr._cache.clear()
    return {"refreshed": sum(bool(x.get("ok")) for x in res), "problems": [{"symbol": x["symbol"], "error": x.get("error", "")} for x in res if not x.get("ok")],
            "at": datetime.now().isoformat(timespec="seconds")}
