"""Forecast models, walk-forward evaluation, consensus, seasonality and pairs endpoints."""
from __future__ import annotations

import json
from typing import Any

import pandas as pd
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.routes import _known, symbol_table
from app.api.routes_fund import clean
from app.data import jobs
from app.data.analysis import close_series, pool_frames, scorecard_for, sentiment_daily
from app.data.db import get_session
from app.data.models import JobRecord, ModelRun
from app.data.prices import apply_adjustment, load_prices
from app.deps import _session_ctx
from app.eval.runner import MIN_BARS, _precheck, run_models
from app.features.pipeline import to_frame
from app.models import consensus as cons
from app.models import pairs as pairs_mod
from app.models import registry as reg
from app.models import seasonality as seas

router = APIRouter()


class RunRequest(BaseModel):
    models: list[str] = Field(default_factory=lambda: ["arima", "garch", "mc_bootstrap", "hmm_regime"])
    horizon: int = 5
    evaluate: bool = True
    mode: str = "expanding"
    fast: bool = False
    levels: list[float] = Field(default_factory=list, max_length=6)
    ensemble: bool = True
    wait: bool = False


def _ohlcv(db: Session, symbol: str) -> pd.DataFrame:
    p = load_prices(db, symbol, "1d")
    if p.empty:
        raise HTTPException(404, f"no stored daily prices for {symbol}; open its chart or run make seed first")
    return to_frame(apply_adjustment(p))


@router.get("/models")
def list_models() -> dict:
    return {"models": reg.catalogue(), "horizons": list(reg.HORIZONS),
            "note": "Baselines always run alongside your selection: they are the yardstick every model must beat."}


@router.post("/models/{symbol}/run", status_code=202)
async def run(symbol: str, body: RunRequest, db: Session = Depends(get_session)) -> dict:
    """Start training/forecasting (and walk-forward validation) as a background job. Poll GET /jobs/{id}."""
    sym = _known(symbol)
    if body.horizon not in reg.HORIZONS:
        raise HTTPException(422, f"horizon must be one of {list(reg.HORIZONS)}")
    if body.mode not in ("expanding", "rolling"):
        raise HTTPException(422, "mode must be 'expanding' or 'rolling'")
    bad = [m for m in body.models if m not in reg.MODEL_CLASSES]
    if bad:
        raise HTTPException(422, f"unknown model(s) {bad}; see GET /models")
    if not [m for m in body.models if m not in reg.BASELINES]:
        raise HTTPException(422, "choose at least one non-baseline model")
    df = _ohlcv(db, sym)
    if len(df) < MIN_BARS:
        raise HTTPException(422, f"need at least {MIN_BARS} daily bars for {sym}, have {len(df)}")
    chosen = [m for m in body.models if m not in reg.BASELINES]
    needs = {reg.MODEL_CLASSES[m].needs for m in chosen}
    aux: dict = {}
    if "sentiment" in needs:
        sd = sentiment_daily(db, sym)
        if sd is not None:
            aux["sentiment"] = sd
    if "pool" in needs:
        from app.portfolio import tracked_symbols
        aux["pool"] = pool_frames(db, sym, tracked_symbols(db))
    reasons = {m: _precheck(m, aux) for m in chosen}
    if all(reasons.values()):
        raise HTTPException(422, "None of the selected models can run: " + "; ".join(f"{m}: {w}" for m, w in reasons.items()))
    jid = jobs.create_job(_session_ctx, "model_run", sym)
    task = jobs.spawn(_session_ctx, jid, lambda progress: run_models(
        _session_ctx, sym, df, body.models, body.horizon, body.evaluate, body.mode, body.fast, body.levels or None, progress, aux, body.ensemble))
    if body.wait:
        await task
    j = db.get(JobRecord, jid)
    db.refresh(j)
    return jobs.job_dict(j)


@router.get("/jobs/{job_id}")
def get_job(job_id: str, db: Session = Depends(get_session)) -> dict:
    j = db.get(JobRecord, job_id)
    if not j:
        raise HTTPException(404, "unknown job id")
    return jobs.job_dict(j)


def _views_and_metrics(db: Session, sym: str, horizon: int) -> tuple[dict[str, dict], dict[str, dict], dict[str, ModelRun]]:
    runs = reg.latest_runs(db, sym, horizon)
    views = {k: json.loads(r.view) for k, r in runs.items()}
    metrics = {k: json.loads(r.metrics) for k, r in runs.items() if r.metrics}
    return views, metrics, runs


@router.get("/analysis/seasonality/{symbol}")
def seasonality(symbol: str, db: Session = Depends(get_session)) -> dict:
    sym = _known(symbol)
    c = close_series(db, sym)
    if c is None or len(c) < 250:
        raise HTTPException(404, f"need at least 250 stored daily bars for {sym}")
    return clean(seas.analyse(c))


@router.get("/analysis/pairs/{symbol}")
def pairs(symbol: str, peers: str | None = None, db: Session = Depends(get_session)) -> dict:
    sym = _known(symbol)
    if peers:
        names = [_known(p) for p in peers.split(",") if p.strip()]
    else:
        table = {s.symbol: s.sector for s in symbol_table()}
        mine = table.get(sym)
        names = [s for s, sec in table.items() if s != sym and sec == mine and sec != "Index"] or [s for s in table if s != sym and table[s] != "Index"][:8]
    closes = {s: c for s in [sym, *names[:10]] if (c := close_series(db, s)) is not None}
    if sym not in closes or len(closes) < 2:
        raise HTTPException(404, "need stored daily prices for the symbol and at least one peer (pass ?peers=A,B)")
    try:
        return clean(pairs_mod.analyse(sym, closes))
    except ValueError as e:
        raise HTTPException(422, str(e)) from e


@router.get("/analysis/{symbol}")
def analysis(symbol: str, horizon: int = Query(5), db: Session = Depends(get_session)) -> dict:
    """Consensus panel + latest model views + the rules-based scorecard."""
    sym = _known(symbol)
    views, metrics, runs = _views_and_metrics(db, sym, horizon)
    if not views:
        raise HTTPException(404, f"no model runs for {sym} at horizon {horizon}. POST /models/{sym}/run first.")
    try:
        card = scorecard_for(db, sym)
    except Exception:  # noqa: BLE001
        card = None
    asof = max(v["asof"] for v in views.values())
    return clean({"symbol": sym, "horizon": horizon, "asof": asof, "consensus": cons.build(views, metrics, reg.BASELINES),
                  "views": views, "scorecard": card, "versions": {k: r.version for k, r in runs.items()},
                  "trained_at": max(r.trained_at for r in runs.values())})


@router.get("/models/{symbol}/evaluation")
def evaluation(symbol: str, horizon: int = Query(5), db: Session = Depends(get_session)) -> dict:
    """Latest walk-forward results: leaderboard, baselines, calibration, errors. Verdicts are Bonferroni-corrected."""
    sym = _known(symbol)
    _, metrics, runs = _views_and_metrics(db, sym, horizon)
    if not metrics:
        raise HTTPException(404, f"no evaluation stored for {sym} at horizon {horizon}. Run with evaluate=true.")
    board = []
    for name, m in metrics.items():
        board.append({"model": name, "baseline": name in reg.BASELINES, "verdict": m.get("verdict"), "brier": m["brier"], "brier_skill": m.get("brier_skill"),
                      "hit_rate": m["directional"]["hit_rate"], "naive_rate": m["directional"]["naive_rate"], "p_vs_naive": m["directional"]["p_vs_naive"],
                      "accuracy3": m["confusion"]["accuracy3"], "ece": m["calibration_up"]["ece"], "mase": m["point"]["mase"],
                      "pinball": m["pinball"]["mean"], "coverage_90": m["pinball"]["coverage_90"], "rank_ic": m["rank_ic"]["ic"],
                      "dm_p": m.get("dm_p"), "p_adjusted": m.get("p_adjusted"), "n_effective": m["n_effective"], "version": runs[name].version})
    board.sort(key=lambda r: (r["baseline"], r["brier"]))
    first = next(iter(metrics.values()))
    return clean({"symbol": sym, "horizon": horizon, "period": {"first": first["first"], "last": first["last"], "forecasts": first["n_forecasts"],
                                                                 "mode": first["mode"], "stride": first["stride"]},
                  "leaderboard": board, "details": metrics,
                  "notes": ["Brier skill is measured against the base-rate baseline: positive means better than naive.",
                            "Verdicts use a Diebold-Mariano test (overlap-robust) with a Bonferroni correction for the number of models tried.",
                            "A past edge can vanish: re-run regularly and watch the cumulative-skill and rolling-accuracy lines."]})


@router.get("/models/{symbol}/registry")
def registry_history(symbol: str, model: str | None = None, db: Session = Depends(get_session)) -> list[dict[str, Any]]:
    q = select(ModelRun).where(ModelRun.symbol == _known(symbol)).order_by(ModelRun.id.desc()).limit(200)
    if model:
        q = q.where(ModelRun.model == model)
    out = []
    for r in db.scalars(q):
        m = json.loads(r.metrics) if r.metrics else {}
        out.append({"model": r.model, "horizon": r.horizon, "version": r.version, "trained_at": r.trained_at, "train_start": r.train_start,
                    "train_end": r.train_end, "n_train": r.n_train, "feature_hash": r.feature_hash, "verdict": m.get("verdict"),
                    "brier_skill": m.get("brier_skill"), "hit_rate": (m.get("directional") or {}).get("hit_rate"), "params": json.loads(r.params)})
    return out


@router.get("/models/{symbol}/ablation")
def ablation(symbol: str, horizon: int = Query(5), db: Session = Depends(get_session)) -> dict:
    """Does news sentiment add anything on top of price features? Compares lgbm (price only), lgbm_sentiment (news only) and
    lgbm_combined (both) from the latest stored walk-forward runs, with a paired Diebold-Mariano test of combined vs price-only."""
    import numpy as np

    from app.eval.metrics import diebold_mariano
    from app.models.ml_features import sentiment_coverage
    sym = _known(symbol)
    _, metrics, _ = _views_and_metrics(db, sym, horizon)
    need = ["lgbm", "lgbm_sentiment", "lgbm_combined"]
    missing = [m for m in need if m not in metrics]
    if missing:
        raise HTTPException(404, f"Run lgbm, lgbm_sentiment and lgbm_combined together (with the walk-forward test) first; missing: {missing}. "
                                 "The sentiment models need stored news for this stock.")
    price, comb = metrics["lgbm"], metrics["lgbm_combined"]
    a = {x["date"]: x["v"] for x in price["brier_series"]}
    b = {x["date"]: x["v"] for x in comb["brier_series"]}
    common = sorted(set(a) & set(b))
    lag = max(0, -(-price["horizon"] // price["stride"]) - 1)
    dm = diebold_mariano(np.array([b[d] for d in common]), np.array([a[d] for d in common]), lag) if len(common) >= 10 else {"dm_stat": None, "dm_p": None}
    gain = None if not common else float(np.mean([a[d] - b[d] for d in common]))
    adds = bool(dm["dm_p"] is not None and dm["dm_p"] < 0.05 and gain is not None and gain > 0)
    cov = sentiment_coverage(sentiment_daily(db, sym))
    rows = [{"model": m, "label": lbl, "brier": metrics[m]["brier"], "brier_skill": metrics[m].get("brier_skill"), "verdict": metrics[m].get("verdict"),
             "hit_rate": metrics[m]["directional"]["hit_rate"], "n_effective": metrics[m]["n_effective"], "failures": metrics[m].get("failures", 0)}
            for m, lbl in (("lgbm", "price only"), ("lgbm_sentiment", "news only"), ("lgbm_combined", "price + news"))]
    return clean({"symbol": sym, "horizon": horizon, "rows": rows, "paired": {"n": len(common), "brier_gain": gain, "dm_p": dm["dm_p"], "adds_value": adds},
                  "news_coverage": cov,
                  "reading": ("News sentiment adds measurable, statistically significant predictive value on top of price features for this stock."
                              if adds else "No demonstrated added value from news sentiment on top of price features for this stock (the usual result, and a "
                                           "short news history makes the test weak)."),
                  "notes": ["Sentiment features come from the default non-LLM scorer; LLM scores are forward-only and never used to train.",
                            "A single paired comparison, so no multiple-testing correction is applied to this test.",
                            "News APIs return only recent history, so for most stocks this test has little data until news has been collected for months."]})
