"""Run models for one symbol: forecast now, optionally validate walk-forward against baselines, store in the registry."""
from __future__ import annotations

import logging
import time
from collections.abc import Callable
from typing import Any

import pandas as pd

from app.eval.metrics import evaluate, finalize_verdicts
from app.eval.walkforward import WFConfig, walk_forward
from app.models import registry as reg

log = logging.getLogger("quantlens.runner")
MIN_BARS = 300
MIN_TRAIN_FLOOR = 250
MIN_FORECASTS = 30


def plan_config(n_bars: int, horizon: int, mode: str, fast: bool) -> tuple[WFConfig | None, str | None]:
    """Choose walk-forward settings that leave at least MIN_FORECASTS independent forecasts, or explain why we cannot."""
    min_train = min(504, n_bars - horizon - MIN_FORECASTS * horizon)
    if min_train < MIN_TRAIN_FLOOR:
        need = MIN_TRAIN_FLOOR + horizon + MIN_FORECASTS * horizon
        return None, f"Not enough history for a walk-forward test at a {horizon}-day horizon (need about {need} daily bars, have {n_bars})."
    return WFConfig(horizon=horizon, mode=mode, min_train=min_train, refit_every=126 if fast else 63,
                    max_origins=60 if fast else None), None


def run_models(db_factory: Callable, symbol: str, df: pd.DataFrame, names: list[str], horizon: int, do_eval: bool = True,  # type: ignore[type-arg]
               mode: str = "expanding", fast: bool = False, levels: list[float] | None = None,
               progress: Callable[[float], None] | None = None) -> dict[str, Any]:
    """Blocking (CPU heavy): meant to be run in a worker thread via the job manager."""
    t0 = time.time()
    if len(df) < MIN_BARS:
        raise ValueError(f"need at least {MIN_BARS} daily bars for {symbol}, have {len(df)}")
    unknown = [n for n in names if n not in reg.MODEL_CLASSES]
    if unknown:
        raise ValueError(f"unknown model(s) {unknown}")
    chosen = [n for n in dict.fromkeys(names) if n not in reg.BASELINES]
    everything = chosen + sorted(reg.BASELINES)                 # baselines always run: they are the yardstick
    cfg, why_not = plan_config(len(df), horizon, mode, fast) if do_eval else (None, None)
    warnings: list[str] = [why_not] if why_not else []
    total = len(everything) * (2 if cfg else 1)
    done = 0

    def tick(frac: float = 1.0) -> None:
        if progress:
            progress(min(0.98, (done + frac) / total))      # the last 1-2% is reserved for saving to the registry

    views, params = {}, {}
    failed: list[str] = []
    for name in list(everything):                                # 1) the forecast made now, on all data
        try:
            m = reg.build(name, fast=fast).fit(df)
            views[name] = m.predict(df, horizon, levels=levels, cone=True, fan=True, detail=True)
            params[name] = m.params()
        except Exception as e:  # noqa: BLE001  one broken model must not sink the run
            if name in reg.BASELINES:
                raise
            failed.append(name)
            everything.remove(name)
            warnings.append(f"{name} was skipped: {type(e).__name__}: {str(e)[:160]}")
            log.warning("model %s failed for %s: %s", name, symbol, e)
        done += 1
        tick(0)
    total = len(everything) * (2 if cfg else 1) + len(failed)

    metrics: dict[str, dict[str, Any]] = {}
    if cfg:                                                      # 2) honest out-of-sample test of each model
        preds = {}
        for name in list(everything):
            try:
                preds[name] = walk_forward(lambda n=name: reg.build(n, fast=fast), df, cfg, tick)
            except Exception as e:  # noqa: BLE001  e.g. too many failed forecasts: report it, do not rank the model
                if name in reg.BASELINES:
                    raise
                everything.remove(name)
                views.pop(name, None)
                warnings.append(f"{name} was dropped from the evaluation: {type(e).__name__}: {str(e)[:160]}")
            done += 1
        for name in everything:
            metrics[name] = evaluate(preds[name], preds["base_rate"], is_baseline=name in reg.BASELINES)
        finalize_verdicts(metrics, set(reg.BASELINES))

    db_versions = {}
    with db_factory() as db:
        for name in everything:
            db_versions[name] = reg.save_run(db, symbol, views[name], params[name], metrics.get(name))
    if progress:
        progress(0.99)
    return {"symbol": symbol, "horizon": horizon, "asof": str(df.index[-1].date()), "models": everything, "evaluated": bool(cfg),
            "walk_forward": None if not cfg else {"mode": cfg.mode, "min_train": cfg.min_train, "refit_every": cfg.refit_every,
                                                   "stride": cfg.step, "forecasts": metrics[everything[0]]["n_forecasts"]},
            "versions": db_versions, "warnings": warnings, "elapsed_s": round(time.time() - t0, 1)}
