"""Baselines every model must beat to be called useful.

  base_rate  : "naive". Predicts the historical share of up/flat/down outcomes (a zero-drift random walk in spirit).
  buy_hold   : always votes UP (the long-only investor's implicit forecast). Its probabilities are the base rates.
  ma_rule    : price above its 50-day average -> uses the empirical up-rate observed in training when that held,
               else the empirical rate when it did not. A simple trend-following rule.

Their probabilities come from TRAINING data only, so they are fair opponents in walk-forward tests.
"""
from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from app.models.base import (
    Model,
    ModelView,
    direction,
    flat_band,
    quantiles_from_samples,
    window_info,
)

MA_LEN = 50


def _outcomes(close: pd.Series, h: int) -> pd.DataFrame:
    """For each past origin: forward log return, causal flat band at that origin, and whether price > its MA."""
    lc = np.log(close)
    fwd = lc.shift(-h) - lc
    sig = lc.diff().rolling(60).std()
    band = 0.25 * sig * np.sqrt(h)
    above = (close > close.rolling(MA_LEN).mean()).astype(float).where(close.rolling(MA_LEN).mean().notna())
    d = pd.DataFrame({"fwd": fwd, "band": band, "above": above}).dropna()
    d["dir"] = np.where(d.fwd > d.band, "up", np.where(d.fwd < -d.band, "down", "flat"))
    return d


class _Base(Model):
    kind = "baseline"

    def __init__(self, fast: bool = False, seed: int = 0) -> None:
        super().__init__(fast, seed)
        self._train: pd.DataFrame | None = None
        self._cache: dict[int, Any] = {}

    def fit(self, train: pd.DataFrame) -> _Base:
        self._check(train)
        self._train, self._cache, self._fitted = train, {}, True
        return self

    def _rates(self, h: int) -> dict[str, Any]:
        if h not in self._cache:
            assert self._train is not None
            d = _outcomes(self._train["close"], h)
            # Only rows whose forward window ended inside the training data are included (dropna handles the tail).
            base = {k: float((d["dir"] == k).mean()) for k in ("up", "flat", "down")}
            cond = {}
            for a in (0.0, 1.0):
                sub = d[d["above"] == a]
                cond[a] = {k: float((sub["dir"] == k).mean()) for k in ("up", "flat", "down")} if len(sub) >= 30 else base
            self._cache[h] = {"base": base, "cond": cond, "n": int(len(d)), "fwd": d["fwd"].to_numpy()}
        return self._cache[h]

    def _make(self, history: pd.DataFrame, horizon: int, rates: dict[str, float], drivers: list[dict[str, Any]],
              vote: str | None = None) -> ModelView:
        assert self._train is not None
        r = self._rates(horizon)
        band = flat_band(history["close"], horizon)
        v = self._view(history, horizon, (rates["up"], rates["flat"], rates["down"]), quantiles_from_samples(r["fwd"]), band,
                       window_info(self._train), drivers=drivers)
        if vote:
            v.extras["forced_vote"] = vote
        return v


class BaseRate(_Base):
    name = "base_rate"
    description = "Naive baseline: forecasts the historical share of up / flat / down outcomes. Every model must beat this."

    def predict(self, history: pd.DataFrame, horizon: int, **kw: Any) -> ModelView:
        r = self._rates(horizon)
        return self._make(history, horizon, r["base"], [{"name": "training up-rate", "value": round(r["base"]["up"], 3)}])


class BuyHold(_Base):
    name = "buy_hold"
    description = "Baseline: always predicts UP (what a buy-and-hold investor implicitly assumes)."

    def predict(self, history: pd.DataFrame, horizon: int, **kw: Any) -> ModelView:
        r = self._rates(horizon)
        v = self._make(history, horizon, r["base"], [{"name": "rule", "value": "always up"}], vote="up")
        return v


class MaRule(_Base):
    name = "ma_rule"
    description = f"Baseline: trend-following. Uses the training up-rate after days when price was above (or below) its {MA_LEN}-day average."

    def predict(self, history: pd.DataFrame, horizon: int, **kw: Any) -> ModelView:
        r = self._rates(horizon)
        c = history["close"]
        above = float(c.iloc[-1] > c.iloc[-MA_LEN:].mean())
        return self._make(history, horizon, r["cond"][above],
                          [{"name": f"price vs {MA_LEN}d average", "value": "above" if above else "below"}])


__all__ = ["BaseRate", "BuyHold", "MaRule", "direction"]
