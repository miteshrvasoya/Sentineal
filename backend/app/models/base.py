"""Common model interface for every forecasting model in QuantLens.

Models are analysis tools, not crystal balls. A model never outputs "the price"; it outputs a *predictive
distribution* for the h-day return, summarised as:
  - probabilities of up / flat / down, where "flat" means |log return| < flat_band (see below), and
  - quantiles (5/25/50/75/95) of the simple return.
The evaluation harness (app/eval) then measures how often those probabilities were right, out of sample,
against simple baselines.

Interface:  fit(train)            -> self     (train = daily OHLCV, index sorted, ONLY data available at fit time)
            predict(history, h)   -> ModelView (history = daily OHLCV up to and including the forecast origin)

`flat_band` is causal: 0.25 x trailing 60-day daily volatility x sqrt(h). A move smaller than that counts as
"flat", so the three classes are meaningful at any volatility level.
"""
from __future__ import annotations

import abc
import math
from dataclasses import asdict, dataclass, field
from typing import Any

import numpy as np
import pandas as pd
from scipy import stats

QUANTILES = (0.05, 0.25, 0.5, 0.75, 0.95)
FLAT_K = 0.25
VOL_WINDOW = 60
MIN_HISTORY = 120


def log_returns(df: pd.DataFrame) -> pd.Series:
    return np.log(df["close"]).diff().dropna()


def daily_sigma(close: pd.Series, window: int = VOL_WINDOW) -> float:
    """Trailing standard deviation of daily log returns (causal: last `window` bars only)."""
    r = np.log(close).diff().dropna().iloc[-window:]
    s = float(r.std(ddof=1)) if len(r) > 5 else 0.01
    return s if s > 1e-8 else 1e-8


def flat_band(close: pd.Series, horizon: int, k: float = FLAT_K) -> float:
    return k * daily_sigma(close) * math.sqrt(horizon)


def direction(logret: float, band: float) -> str:
    return "up" if logret > band else "down" if logret < -band else "flat"


@dataclass
class ModelView:
    name: str
    horizon: int
    p_up: float
    p_flat: float
    p_down: float
    quantiles: dict[str, float]            # {"5": simple return, ...}
    flat_band: float                       # log-return threshold defining "flat"
    asof: str
    training_window: dict[str, Any]
    version: str
    kind: str = "statistical"
    drivers: list[dict[str, Any]] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    extras: dict[str, Any] = field(default_factory=dict)

    @property
    def vote(self) -> str:
        return max((("up", self.p_up), ("flat", self.p_flat), ("down", self.p_down)), key=lambda x: x[1])[0]

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["vote"] = self.vote
        d["conviction"] = max(self.p_up, self.p_flat, self.p_down)
        return d


def _norm3(p_up: float, p_flat: float, p_down: float) -> tuple[float, float, float]:
    t = p_up + p_flat + p_down
    return p_up / t, p_flat / t, p_down / t


def probs_from_samples(samples: np.ndarray, band: float) -> tuple[float, float, float]:
    """P(up), P(flat), P(down) from simulated h-day LOG returns."""
    s = np.asarray(samples, float)
    s = s[np.isfinite(s)]
    if len(s) == 0:
        return 1 / 3, 1 / 3, 1 / 3
    return _norm3(float((s > band).mean()), float((np.abs(s) <= band).mean()), float((s < -band).mean()))


def probs_from_normal(mu: float, sigma: float, band: float) -> tuple[float, float, float]:
    sigma = max(sigma, 1e-9)
    up = 1 - stats.norm.cdf((band - mu) / sigma)
    down = stats.norm.cdf((-band - mu) / sigma)
    return _norm3(float(up), float(max(1 - up - down, 0.0)), float(down))


def quantiles_from_samples(samples: np.ndarray) -> dict[str, float]:
    s = np.asarray(samples, float)
    s = s[np.isfinite(s)]
    q = np.quantile(s, QUANTILES) if len(s) else np.zeros(len(QUANTILES))
    return {str(int(p * 100)): float(np.expm1(v)) for p, v in zip(QUANTILES, q, strict=True)}


def window_info(df: pd.DataFrame) -> dict[str, Any]:
    return {"start": str(df.index[0].date()), "end": str(df.index[-1].date()), "n": int(len(df))}


class ModelError(Exception):
    """A model produced a forecast that is not finite or not plausible. Treated as a failed forecast, never shown as a result."""


MAX_ABS_LOGRET = 2.0       # |log return| beyond this over any horizon (a x7 move) means the simulation blew up


def validate_quantiles(q: dict[str, float], probs: tuple[float, float, float]) -> None:
    vals = list(q.values())
    if not all(np.isfinite(v) for v in vals) or not all(np.isfinite(p) for p in probs):
        raise ModelError("forecast contains non-finite values")
    if any(v <= -1 or abs(math.log1p(v)) > MAX_ABS_LOGRET for v in vals):
        raise ModelError(f"implausible forecast range {min(vals):+.2f} to {max(vals):+.2f}")


class Model(abc.ABC):
    """Subclass, set `name`/`description`, implement fit and predict, register in app/models/registry.py."""

    name = "model"
    kind = "statistical"          # "statistical" | "baseline" | "ml" | "deep"
    description = ""
    experimental = False
    version = "v1"

    def __init__(self, fast: bool = False, seed: int = 0) -> None:
        self.fast, self.seed = fast, seed
        self.n_sims = 400 if fast else 2000
        self._fitted = False

    @abc.abstractmethod
    def fit(self, train: pd.DataFrame) -> Model: ...

    @abc.abstractmethod
    def predict(self, history: pd.DataFrame, horizon: int, **kwargs: Any) -> ModelView: ...

    def params(self) -> dict[str, Any]:
        return {}

    def _check(self, df: pd.DataFrame) -> None:
        if len(df) < MIN_HISTORY:
            raise ValueError(f"{self.name} needs at least {MIN_HISTORY} daily bars, got {len(df)}")
        if not df.index.is_monotonic_increasing:
            raise ValueError("history must be sorted by date")

    def _view(self, history: pd.DataFrame, horizon: int, probs: tuple[float, float, float], quantiles: dict[str, float],
              band: float, train_info: dict[str, Any], **kw: Any) -> ModelView:
        validate_quantiles(quantiles, probs)
        return ModelView(name=self.name, horizon=horizon, p_up=probs[0], p_flat=probs[1], p_down=probs[2], quantiles=quantiles,
                         flat_band=band, asof=str(history.index[-1].date()), training_window=train_info,
                         version=f"{self.name}-{self.version}", kind=self.kind, **kw)

    def rng(self, salt: int = 0) -> np.random.Generator:
        return np.random.default_rng(self.seed + salt)
