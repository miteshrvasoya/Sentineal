"""Screener, relative strength, breadth and sector endpoints (Phase 10)."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.routes_fund import clean
from app.data.db import get_session
from app.screener import engine as eng

router = APIRouter()


class Condition(BaseModel):
    field: str
    op: str
    value: Any


class ScreenRequest(BaseModel):
    conditions: list[Condition] = Field(default_factory=list, max_length=12)
    sort: str = "rs_rank_126"
    desc: bool = True
    limit: int = Field(50, ge=1, le=200)


@router.get("/screener/fields")
def fields() -> dict:
    return {"fields": [f.__dict__ for f in eng.FIELDS], "ops": sorted(eng.OPS), "presets": eng.PRESETS}


@router.post("/screener/run")
def run(body: ScreenRequest, db: Session = Depends(get_session)) -> dict:
    rows = eng.universe(db)
    if not rows:
        raise HTTPException(404, "No stored stocks with enough history. Run make seed or open a few charts first.")
    try:
        res = eng.screen(rows, [c.model_dump() for c in body.conditions], body.sort, body.desc, body.limit)
    except ValueError as e:
        raise HTTPException(422, str(e)) from e
    return clean({**res, "disclaimer": "A screen filters today's numbers. It is not a forecast and not a recommendation."})


@router.get("/market/breadth")
def market_breadth(db: Session = Depends(get_session)) -> dict:
    return clean(eng.breadth(eng.universe(db)))


@router.get("/market/sectors")
def market_sectors(db: Session = Depends(get_session)) -> dict:
    return clean(eng.sectors(eng.universe(db)))
