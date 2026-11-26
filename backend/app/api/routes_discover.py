"""Discover: short- and long-term stock ideas, a per-stock verdict, and loading more stocks to compare."""
from __future__ import annotations

import csv
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import ideas
from app.api.routes import _known
from app.api.routes_fund import clean, get_fund_provider, load_fundamentals
from app.config import ROOT
from app.data import jobs
from app.data.db import get_session
from app.data.models import FundamentalsSnapshot, JobRecord, Price
from app.deps import _session_ctx, get_router
from app.screener import engine as scr

router = APIRouter()


def popular() -> list[dict[str, str]]:
    with open(ROOT / "data" / "popular.csv", newline="") as f:
        return list(csv.DictReader(f))


@router.get("/discover/status")
def status(db: Session = Depends(get_session)) -> dict:
    from app.portfolio import holding_symbols
    pop = [p["symbol"] for p in popular()]
    stored = set(db.scalars(select(Price.symbol).where(Price.interval == "1d").group_by(Price.symbol).having(func.count() >= scr.MIN_BARS)))
    funds = set(db.scalars(select(FundamentalsSnapshot.symbol)))
    return {"popular": len(pop), "loaded": len([s for s in pop if s in stored]), "with_company_numbers": len([s for s in pop if s in funds]),
            "stored_total": len(stored), "holdings_loaded": len([s for s in holding_symbols(db) if s in stored]), "enough_to_compare": len(stored) >= 20,
            "hint": "Rankings compare stocks against each other, so they are only as good as the set of stocks loaded. Press Load more stocks to add about 80 well-known companies."}


@router.post("/discover/load", status_code=202)
async def load(db: Session = Depends(get_session), r=Depends(get_router), fprov=Depends(get_fund_provider)) -> dict:  # type: ignore[no-untyped-def]
    """Fetch prices and company numbers for the popular stocks that are missing, as a background job (a few minutes)."""
    running = db.scalars(select(JobRecord).where(JobRecord.kind == "discover_load", JobRecord.status.in_(("queued", "running")))).first()
    if running:
        return jobs.job_dict(running)
    from app.portfolio import holding_symbols
    syms = list(dict.fromkeys([p["symbol"] for p in popular()] + holding_symbols(db)))      # your own stocks are always included
    jid = jobs.create_job(_session_ctx, "discover_load", "")

    async def work(progress):  # type: ignore[no-untyped-def]
        from app.data.ingest import backfill_symbol
        done, failed_prices, failed_funds = 0, [], []
        with _session_ctx() as s:
            have_f = set(s.scalars(select(FundamentalsSnapshot.symbol)))
            for i, sym in enumerate(syms):
                res = await backfill_symbol(s, r, sym, "1d")
                if not res["ok"]:
                    failed_prices.append(sym)
                    progress((i + 1) / len(syms))
                    continue
                if sym not in have_f:
                    try:
                        await load_fundamentals(s, fprov, sym)
                    except Exception:  # noqa: BLE001  company numbers are a bonus
                        failed_funds.append(sym)
                done += 1
                progress((i + 1) / len(syms))
        scr._cache.clear()
        return {"loaded": done, "price_problems": failed_prices, "company_number_problems": failed_funds, "total": len(syms)}
    jobs.spawn_async(_session_ctx, jid, work)
    return jobs.job_dict(db.get(JobRecord, jid))


@router.get("/discover/ideas")
def get_ideas(horizon: str = Query("short", pattern="^(short|long)$"), risk: str = Query("any", pattern="^(any|low|medium)$"), sector: str | None = None,
              limit: int = Query(8, ge=1, le=20), db: Session = Depends(get_session)) -> dict:
    rows = scr.universe(db)
    if not rows:
        raise HTTPException(404, "No stocks loaded yet. Press Load more stocks first.")
    from app.portfolio import holding_symbols
    owned = set(holding_symbols(db))
    out = ideas.top_ideas(db, rows, horizon, limit, risk, sector)
    for i in out["ideas"]:
        i["owned"] = i["symbol"] in owned
    out["sectors"] = sorted({r["sector"] for r in rows if r.get("sector")})
    return clean(out)


@router.get("/discover/stock/{symbol}")
def stock_view(symbol: str, db: Session = Depends(get_session)) -> dict:
    """Short- and long-term assessment of one stock in plain English."""
    sym = _known(symbol)
    rows = scr.universe(db)
    row: dict[str, Any] | None = next((x for x in rows if x["symbol"] == sym), None)
    if row is None:
        row = scr.snapshot_row(db, sym, "")
        if row is None:
            raise HTTPException(404, f"Not enough stored price history for {sym} yet (needs about 3 months).")
        row["rs_rank_126"] = row["rs_rank_63"] = None
    from app.portfolio import holding_symbols
    return clean({"symbol": sym, "short": ideas.assess_row(db, row, "short"), "long": ideas.assess_row(db, row, "long"), "compared_with": len(rows),
                  "owned": sym in set(holding_symbols(db)), "disclaimer": ideas.DISCLAIMER})


@router.get("/discover/holdings")
def holdings_review(db: Session = Depends(get_session)) -> dict:
    """How each stock you own scores for the short and the long term, so your own money gets the same scrutiny as new ideas."""
    from app.portfolio import holding_symbols
    syms = holding_symbols(db)
    rows = {x["symbol"]: x for x in scr.universe(db)}
    out = []
    for s in syms:
        row = rows.get(s) or scr.snapshot_row(db, s, "")
        if row is None:
            out.append({"symbol": s, "available": False})
            continue
        if s not in rows:
            row["rs_rank_126"] = row["rs_rank_63"] = None
        out.append({"symbol": s, "available": True, "short": ideas.assess_row(db, row, "short"), "long": ideas.assess_row(db, row, "long")})
    return clean({"holdings": out, "compared_with": len(rows), "disclaimer": ideas.DISCLAIMER})
