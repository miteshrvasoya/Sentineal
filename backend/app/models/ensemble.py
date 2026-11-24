"""Ensemble: a weighted average of several models' forecasts, with weights from RECENT OUT-OF-SAMPLE performance.

Idea: models that have been right lately get more say. Danger: using outcomes that were not yet known when the forecast was made
would be look-ahead. So at each forecast origin the weights use ONLY earlier forecasts whose h-day outcome had already been
observed by that origin (for non-overlapping forecasts that is every previous one). With no usable history the weights are equal.

Weights: w_k proportional to exp(-(L_k - L_min) / tau), where L_k is model k's average Brier loss over its last `lookback`
resolved forecasts. tau = 0.02 means a model 0.02 worse than the best gets about 37% of the best model's weight: a gentle tilt,
not a winner-takes-all bet (winner-takes-all chases noise).

Probabilities are averaged directly. Return quantiles are averaged quantile-by-quantile (Vincentisation).
"""
from __future__ import annotations

import math
from typing import Any

import numpy as np
import pandas as pd

from app.eval.metrics import brier_per_forecast
from app.models.base import ModelView

LOOKBACK = 20
TAU = 0.02
Q_COLS = ["q5", "q25", "q50", "q75", "q95"]
P_COLS = ["p_up", "p_flat", "p_down"]


def weights_from_losses(mean_loss: dict[str, float], tau: float = TAU) -> dict[str, float]:
    if not mean_loss:
        return {}
    lo = min(mean_loss.values())
    raw = {k: math.exp(-(v - lo) / tau) for k, v in mean_loss.items()}
    s = sum(raw.values())
    return {k: v / s for k, v in raw.items()}


def combine_walkforward(preds: dict[str, pd.DataFrame], horizon: int, stride: int, lookback: int = LOOKBACK, tau: float = TAU) -> pd.DataFrame:
    """Causal ensemble predictions on the origins common to all components."""
    names = list(preds)
    idx = preds[names[0]].index
    for n in names[1:]:
        idx = idx.intersection(preds[n].index)
    if len(idx) == 0:
        raise ValueError("components share no forecast origins")
    P = {n: preds[n].loc[idx] for n in names}
    loss = pd.DataFrame({n: brier_per_forecast(P[n]) for n in names}, index=idx)
    lag = max(1, math.ceil(horizon / stride))           # forecast i's outcome is known by origin i + lag
    rows, weights_hist = [], []
    for i in range(len(idx)):
        known = loss.iloc[max(0, i - lag - lookback + 1):max(0, i - lag + 1)] if i - lag + 1 > 0 else loss.iloc[0:0]
        w = weights_from_losses(known.mean().to_dict(), tau) if len(known) else {n: 1.0 / len(names) for n in names}
        weights_hist.append(w)
        base = P[names[0]].iloc[i]
        p = {c: sum(w[n] * P[n].iloc[i][c] for n in names) for c in P_COLS}
        q = {c: sum(w[n] * P[n].iloc[i][c] for n in names) for c in Q_COLS}
        vote = max(("up", p["p_up"]), ("flat", p["p_flat"]), ("down", p["p_down"]), key=lambda t: t[1])[0]
        rows.append({"actual": base["actual"], "band": base["band"], **p, "vote": vote, **q, "label": base["label"]})
    out = pd.DataFrame(rows, index=idx)
    out.attrs.update(horizon=horizon, stride=stride, failures=0, mode=preds[names[0]].attrs.get("mode"), n_origins=len(idx))
    out.attrs["weights_last"] = weights_hist[-1]
    return out


def current_weights(preds: dict[str, pd.DataFrame], horizon: int, stride: int, lookback: int = LOOKBACK, tau: float = TAU) -> dict[str, float]:
    """Weights to use for a forecast made NOW: all walk-forward outcomes are already known."""
    idx = preds[next(iter(preds))].index
    for p in preds.values():
        idx = idx.intersection(p.index)
    if len(idx) == 0:
        return {n: 1.0 / len(preds) for n in preds}
    loss = {n: float(np.mean(brier_per_forecast(p.loc[idx])[-lookback:])) for n, p in preds.items()}
    return weights_from_losses(loss, tau)


def combine_views(views: dict[str, ModelView], weights: dict[str, float], horizon: int) -> ModelView:
    names = [n for n in views if n in weights]
    w = {n: weights[n] / sum(weights[k] for k in names) for n in names}
    first = views[names[0]]
    p = [sum(w[n] * getattr(views[n], c) for n in names) for c in P_COLS]
    qs = {k: float(sum(w[n] * views[n].quantiles[k] for n in names)) for k in first.quantiles}
    drivers = [{"name": f"weight: {n}", "value": f"{w[n]:.0%}"} for n in sorted(names, key=lambda n: -w[n])]
    extras: dict[str, Any] = {"weights": w}
    return ModelView(name="ensemble", horizon=horizon, p_up=p[0], p_flat=p[1], p_down=p[2], quantiles=qs, flat_band=first.flat_band, asof=first.asof,
                     training_window=first.training_window, version="ensemble-v1", kind="ensemble", drivers=drivers,
                     notes=["Weighted by each model's recent out-of-sample Brier loss, using only outcomes that were already known at each forecast."],
                     extras=extras)


__all__ = ["combine_walkforward", "combine_views", "current_weights", "weights_from_losses", "np"]
