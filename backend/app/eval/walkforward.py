"""Walk-forward validation: the only honest way to test a time-series model.

At each REFIT point t the model is fitted on data up to and including t only (expanding window, or a fixed rolling
window). It then forecasts from every forecast ORIGIN until the next refit; each forecast is compared with what actually
happened h days later. Nothing from the future is visible when a forecast is made, there is no random shuffling, and the
default stride equals the horizon so evaluated outcomes do not overlap (overlapping outcomes would overstate how much
independent evidence we have).

A model that has to be refitted every day would be too slow, so the model is refitted every `refit_every` bars and merely
re-conditioned on the newest history between refits (see each model's predict()).
"""
from __future__ import annotations

import logging
import math
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from app.models.base import Model

log = logging.getLogger("quantlens.eval")
HISTORY_CAP = 1500   # bars of history handed to predict()


@dataclass
class WFConfig:
    horizon: int = 5
    mode: str = "expanding"          # "expanding" | "rolling"
    min_train: int = 504             # ~2 years of daily bars before the first forecast
    window: int = 756                # rolling window length (~3 years)
    refit_every: int = 63            # ~one quarter
    stride: int | None = None        # bars between forecast origins; default = horizon (non-overlapping outcomes)
    max_origins: int | None = None   # keep only the most recent N origins (speed)

    @property
    def step(self) -> int:
        return self.stride or self.horizon


def origins(n: int, cfg: WFConfig) -> list[int]:
    """Row positions t (forecast made at the close of bar t) whose outcome at t+h exists."""
    ts = list(range(cfg.min_train - 1, n - 1 - cfg.horizon + 1, cfg.step))
    return ts[-cfg.max_origins:] if cfg.max_origins else ts


def walk_forward(factory: Callable[[], Model], df: pd.DataFrame, cfg: WFConfig,
                 progress: Callable[[float], None] | None = None) -> pd.DataFrame:
    """Return one row per forecast origin with the model's probabilities, quantiles and the realised outcome."""
    if cfg.mode not in ("expanding", "rolling"):
        raise ValueError("mode must be 'expanding' or 'rolling'")
    n, h = len(df), cfg.horizon
    ts = origins(n, cfg)
    if not ts:
        raise ValueError(f"not enough data: need more than {cfg.min_train + h} daily bars, have {n}")
    close = df["close"].to_numpy()
    rows: list[dict[str, Any]] = []
    model: Model | None = None
    last_fit = -10**9
    failures = 0
    for i, t in enumerate(ts):
        try:
            if model is None or t - last_fit >= cfg.refit_every:
                lo = 0 if cfg.mode == "expanding" else max(0, t + 1 - cfg.window)
                model = factory()
                model.fit(df.iloc[lo:t + 1])               # data up to and including the origin, nothing later
                last_fit = t
            view = model.predict(df.iloc[max(0, t + 1 - HISTORY_CAP):t + 1], h, cone=False, fan=False, detail=False)
        except Exception as e:  # noqa: BLE001  one bad fit must not sink the whole evaluation
            failures += 1
            log.warning("walk-forward %s failed at origin %d: %s", getattr(model, "name", "?"), t, e)
            model = None
            continue
        actual = math.log(close[t + h] / close[t])
        rows.append({"origin": df.index[t], "actual": actual, "band": view.flat_band, "p_up": view.p_up, "p_flat": view.p_flat,
                     "p_down": view.p_down, "vote": view.extras.get("forced_vote", view.vote),
                     **{f"q{k}": v for k, v in view.quantiles.items()}})
        if progress and i % 5 == 0:
            progress((i + 1) / len(ts))
    if failures > 0.2 * len(ts):
        raise RuntimeError(f"{failures} of {len(ts)} forecasts failed; the model is not usable on this series")
    out = pd.DataFrame(rows).set_index("origin")
    out["label"] = np.where(out["actual"] > out["band"], "up", np.where(out["actual"] < -out["band"], "down", "flat"))
    out.attrs.update(horizon=h, stride=cfg.step, failures=failures, n_origins=len(ts), mode=cfg.mode)
    return out
