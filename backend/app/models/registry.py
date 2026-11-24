"""Model catalogue and run registry. Adding a model = one file + one line in MODEL_CLASSES."""
from __future__ import annotations

import json
import time
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.data.models import ModelRun
from app.models.arima import Arima, Ets
from app.models.base import Model, ModelView
from app.models.baselines import BaseRate, BuyHold, MaRule
from app.models.deep import DeepGru, DeepGruPooled, DeepLstm
from app.models.garch import Egarch, Garch, GjrGarch
from app.models.hmm import HmmRegime
from app.models.ml import Lgbm, LgbmCombined, LgbmSentiment, Logit, RandomForest, Xgb
from app.models.montecarlo import McBootstrap, McGbm

MODEL_CLASSES: dict[str, type[Model]] = {c.name: c for c in (
    Arima, Ets, Garch, GjrGarch, Egarch, McGbm, McBootstrap, HmmRegime, Lgbm, Xgb, RandomForest, Logit, LgbmSentiment, LgbmCombined,
    DeepGru, DeepLstm, DeepGruPooled, BaseRate, BuyHold, MaRule)}
BASELINES = {"base_rate", "buy_hold", "ma_rule"}
FEATURE_HASH = "ohlcv-close-v1"       # statistical models see daily closes only; ML models (Phase 8) record their feature hash here
HORIZONS = (1, 5, 10, 21, 42, 63)


def build(name: str, fast: bool = False, seed: int = 0, horizon: int = 5, aux: dict | None = None) -> Model:
    """`horizon` and `aux` ({"sentiment": DataFrame, "pool": {symbol: OHLCV}}) are used by the ML and deep models only."""
    if name not in MODEL_CLASSES:
        raise KeyError(f"unknown model {name!r}; available: {sorted(MODEL_CLASSES)}")
    return MODEL_CLASSES[name](fast=fast, seed=seed, horizon=horizon, aux=aux)


ENSEMBLE = "ensemble"


def group_of(cls: type[Model]) -> str:
    return {"statistical": "statistical", "baseline": "baseline", "ml": "machine learning", "deep": "deep (experimental)"}.get(cls.kind, cls.kind)


def catalogue() -> list[dict[str, Any]]:
    out = []
    for n, c in MODEL_CLASSES.items():
        ok, why = c.availability()
        out.append({"name": n, "kind": c.kind, "group": group_of(c), "description": c.description, "experimental": c.experimental,
                    "baseline": n in BASELINES, "available": ok, "unavailable_reason": why or None, "needs": c.needs})
    out.append({"name": ENSEMBLE, "kind": "ensemble", "group": "ensemble", "baseline": False, "experimental": False, "available": True,
                "unavailable_reason": None, "needs": None,
                "description": "Combines the models you pick, weighted by their recent out-of-sample performance (automatic when 2+ models are chosen)."})
    return out


def next_version(db: Session, symbol: str, model: str) -> int:
    return int(db.scalar(select(func.coalesce(func.max(ModelRun.version), 0)).where(ModelRun.symbol == symbol, ModelRun.model == model)) or 0) + 1


def save_run(db: Session, symbol: str, view: ModelView, params: dict[str, Any], metrics: dict[str, Any] | None) -> int:
    v = next_version(db, symbol, view.name)
    tw = view.training_window
    db.add(ModelRun(symbol=symbol, model=view.name, horizon=view.horizon, version=v, kind=view.kind, trained_at=int(time.time()),
                    train_start=tw.get("start", ""), train_end=tw.get("end", ""), n_train=int(tw.get("n", 0)), feature_hash=FEATURE_HASH,
                    params=json.dumps(params, default=float), view=json.dumps(view.to_dict(), default=float),
                    metrics=json.dumps(metrics, default=float) if metrics else ""))
    db.commit()
    return v


def latest_runs(db: Session, symbol: str, horizon: int) -> dict[str, ModelRun]:
    """Newest run of each model for this symbol and horizon."""
    rows = db.scalars(select(ModelRun).where(ModelRun.symbol == symbol, ModelRun.horizon == horizon).order_by(ModelRun.id)).all()
    return {r.model: r for r in rows}      # later rows overwrite earlier ones
