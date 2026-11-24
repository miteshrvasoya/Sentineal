"""Backtester endpoints (Phase 9)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.routes import _known
from app.api.routes_fund import clean
from app.backtest import costs as costmod
from app.backtest import service
from app.backtest import strategies as strat
from app.data.db import get_session
from app.data.prices import apply_adjustment, load_prices
from app.features.pipeline import to_frame

router = APIRouter()


class BacktestRequest(BaseModel):
    strategy: str = "ma_cross"
    params: dict[str, float] = Field(default_factory=dict)
    cost_preset: str = "india_delivery"
    cost_overrides: dict[str, float] = Field(default_factory=dict)
    capital: float = Field(1_000_000.0, ge=10_000, le=1e9)
    alloc: float = Field(1.0, gt=0, le=1)
    stop_loss: float | None = Field(None, gt=0, lt=0.9)
    oos_fraction: float = Field(0.0, ge=0, le=0.6)
    optimize: bool = False
    reps: int = Field(2000, ge=200, le=5000)
    seed: int = 0


@router.get("/backtest/strategies")
def strategies() -> dict:
    return {"strategies": [{"name": s.name, "title": s.title, "description": s.description, "defaults": s.defaults,
                            "grid": s.grid, "grid_size": len(s.combos())} for s in strat.STRATEGIES.values()],
            "cost_presets": {k: v.describe() for k, v in costmod.PRESETS.items()},
            "cost_note": "Rates are approximate defaults for NSE delivery trades. Check your broker's current rate card and edit them."}


@router.post("/backtest/{symbol}")
def run_backtest(symbol: str, body: BacktestRequest, db: Session = Depends(get_session)) -> dict:
    sym = _known(symbol)
    p = load_prices(db, sym, "1d")
    if p.empty:
        raise HTTPException(404, f"no stored daily prices for {sym}; open its chart or run make seed first")
    try:
        cm = costmod.from_overrides(body.cost_preset, body.cost_overrides)
        out = service.backtest(to_frame(apply_adjustment(p)), strat.get(body.strategy), body.params, costs=cm, capital=body.capital, alloc=body.alloc,
                               stop_loss=body.stop_loss, oos_fraction=body.oos_fraction, optimize=body.optimize, reps=body.reps, seed=body.seed)
    except ValueError as e:
        raise HTTPException(422, str(e)) from e
    return clean({"symbol": sym, **out})
