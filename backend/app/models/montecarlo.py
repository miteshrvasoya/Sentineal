"""Monte Carlo price paths: geometric Brownian motion (GBM) and block bootstrap of historical returns.

Both simulate thousands of possible daily paths from recent behaviour, then read off (a) the distribution of the
terminal return, (b) a FAN of percentile bands per day, and (c) the probability of touching price levels you choose.
They assume the near future resembles the recent past; they have no view on direction beyond the recent drift.
"""
from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from app.models.base import (
    Model,
    ModelView,
    flat_band,
    log_returns,
    probs_from_samples,
    quantiles_from_samples,
    window_info,
)

MAX_FAN_DAYS = 63


def fan_and_touch(last: float, paths: np.ndarray, levels: list[float] | None) -> dict[str, Any]:
    """paths: (sims, H) cumulative LOG returns. Returns percentile price bands per day and touch probabilities."""
    prices = last * np.exp(paths)
    qs = np.quantile(prices, [0.05, 0.25, 0.5, 0.75, 0.95], axis=0)
    out: dict[str, Any] = {"days": list(range(1, paths.shape[1] + 1)), "last": last,
                           "fan": {k: qs[i].tolist() for i, k in enumerate(("p5", "p25", "p50", "p75", "p95"))}}
    touch = {}
    for lv in levels or []:
        # The path starts at today's price, so that start counts as visited (a level equal to today's price is touched at once).
        hit = (np.maximum(prices.max(axis=1), last) >= lv) if lv >= last else (np.minimum(prices.min(axis=1), last) <= lv)
        touch[f"{lv:g}"] = {"level": float(lv), "direction": "above" if lv >= last else "below", "probability": float(hit.mean())}
    out["touch"] = touch
    return out


class _MC(Model):
    window = 252

    def __init__(self, fast: bool = False, seed: int = 0) -> None:
        super().__init__(fast, seed)
        self._info: dict[str, Any] = {}

    def fit(self, train: pd.DataFrame) -> _MC:
        self._check(train)
        self._info, self._fitted = window_info(train), True
        return self

    def _paths(self, r: np.ndarray, horizon: int, rng: np.random.Generator) -> np.ndarray:
        raise NotImplementedError

    def predict(self, history: pd.DataFrame, horizon: int, levels: list[float] | None = None, fan: bool = True, **kw: Any) -> ModelView:
        r = log_returns(history).iloc[-self.window * (2 if self.name == "mc_bootstrap" else 1):].to_numpy()
        paths = self._paths(r, min(horizon, MAX_FAN_DAYS) if fan else horizon, self.rng(len(history)))
        if paths.shape[1] < horizon:  # horizon longer than the fan cap: simulate the terminal value only
            paths = self._paths(r, horizon, self.rng(len(history)))
        samples = paths[:, horizon - 1]
        band = flat_band(history["close"], horizon)
        view = self._view(history, horizon, probs_from_samples(samples, band), quantiles_from_samples(samples), band, self._info,
                          drivers=self._drivers(r), notes=["Assumes the next few weeks look like the recent past."])
        if fan:
            view.extras["fan"] = fan_and_touch(float(history["close"].iloc[-1]), paths[:, :min(horizon, MAX_FAN_DAYS)], levels)
        return view

    def _drivers(self, r: np.ndarray) -> list[dict[str, Any]]:
        return []


class McGbm(_MC):
    name = "mc_gbm"
    description = "Monte Carlo with geometric Brownian motion: constant drift and volatility measured over the last year."

    def _paths(self, r: np.ndarray, horizon: int, rng: np.random.Generator) -> np.ndarray:
        mu, sd = float(r.mean()), float(r.std(ddof=1))
        z = rng.standard_normal((self.n_sims, horizon))
        return np.cumsum(mu + sd * z, axis=1)

    def _drivers(self, r: np.ndarray) -> list[dict[str, Any]]:
        return [{"name": "drift (annualised)", "value": f"{r.mean() * 252 * 100:.1f}%"},
                {"name": "volatility (annualised)", "value": f"{r.std(ddof=1) * np.sqrt(252) * 100:.1f}%"}]


class McBootstrap(_MC):
    name = "mc_bootstrap"
    description = "Monte Carlo that resamples real historical daily returns in 5-day blocks (keeps fat tails and some volatility clustering)."

    def _paths(self, r: np.ndarray, horizon: int, rng: np.random.Generator) -> np.ndarray:
        block = 5
        n_blocks = -(-horizon // block)
        starts = rng.integers(0, len(r) - block, size=(self.n_sims, n_blocks))
        idx = (starts[:, :, None] + np.arange(block)[None, None, :]).reshape(self.n_sims, -1)[:, :horizon]
        return np.cumsum(r[idx], axis=1)

    def _drivers(self, r: np.ndarray) -> list[dict[str, Any]]:
        return [{"name": "returns resampled from", "value": f"last {len(r)} days"},
                {"name": "worst day in sample", "value": f"{np.expm1(r.min()) * 100:.1f}%"}]
