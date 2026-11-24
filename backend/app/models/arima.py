"""ARIMA on daily log returns and damped-trend exponential smoothing (ETS) on log price.

ARIMA: order (p, 0, q) chosen by AIC over p, q in 0..2 at fit time (returns are already differenced prices, d = 0).
At predict time the FITTED parameters are re-applied (smooth) to the newest history, so no refit is needed per origin.
The h-day return distribution is simulated from the fitted model.
Daily returns are almost unpredictable, so expect these to land close to the naive baseline.
"""
from __future__ import annotations

import warnings
from typing import Any

import numpy as np
import pandas as pd
from scipy import stats

from app.models.base import (
    Model,
    ModelView,
    flat_band,
    log_returns,
    probs_from_normal,
    probs_from_samples,
    quantiles_from_samples,
    window_info,
)

MAX_FIT = 1000     # use at most the last 1000 bars when fitting


def _quiet():  # type: ignore[no-untyped-def]
    warnings.filterwarnings("ignore")


class Arima(Model):
    name = "arima"
    description = "ARIMA(p,0,q) on daily returns, order chosen by AIC. Simulates the h-day return distribution."

    def __init__(self, fast: bool = False, seed: int = 0) -> None:
        super().__init__(fast, seed)
        self.order: tuple[int, int, int] = (0, 0, 0)
        self.fit_params: Any = None
        self._info: dict[str, Any] = {}
        self.aic: float | None = None

    def fit(self, train: pd.DataFrame) -> Arima:
        from statsmodels.tsa.arima.model import ARIMA
        self._check(train)
        _quiet()
        r = log_returns(train).iloc[-MAX_FIT:] * 100
        grid = [(p, 0, q) for p in range(0, 3) for q in range(0, 3)]
        if self.fast:
            grid = [(0, 0, 0), (1, 0, 0), (0, 0, 1), (1, 0, 1)]
        best = None
        for order in grid:
            try:
                res = ARIMA(r, order=order, trend="c").fit()
            except Exception:  # noqa: BLE001  non-convergent orders are skipped
                continue
            if best is None or res.aic < best[0]:
                best = (res.aic, order, res.params)
        if best is None:
            raise ValueError("no ARIMA order converged")
        self.aic, self.order, self.fit_params = best
        self._info, self._fitted = window_info(train), True
        return self

    def predict(self, history: pd.DataFrame, horizon: int, **kw: Any) -> ModelView:
        from statsmodels.tsa.arima.model import ARIMA
        _quiet()
        r = log_returns(history).iloc[-MAX_FIT:] * 100
        res = ARIMA(r, order=self.order, trend="c").smooth(self.fit_params)
        sim = np.asarray(res.simulate(nsimulations=horizon, repetitions=self.n_sims, anchor="end", rng=self.rng(len(history))))
        samples = sim.reshape(horizon, -1).sum(axis=0) / 100            # cumulative log return over the horizon
        band = flat_band(history["close"], horizon)
        phi = [float(self.fit_params.get(f"ar.L{i}", 0)) for i in (1, 2)]
        return self._view(history, horizon, probs_from_samples(samples, band), quantiles_from_samples(samples), band, self._info,
                          drivers=[{"name": "order (p,d,q)", "value": str(self.order)},
                                   {"name": "AR(1) coefficient", "value": round(phi[0], 3)},
                                   {"name": "daily mean (%)", "value": round(float(self.fit_params.get("const", 0)), 4)}],
                          notes=["Daily returns carry very little linear memory, so ARIMA forecasts hug zero."])

    def params(self) -> dict[str, Any]:
        return {"order": list(self.order), "aic": self.aic}


class Ets(Model):
    name = "ets"
    description = "Holt-Winters style damped-trend exponential smoothing on log price; residual noise gives the spread."

    def __init__(self, fast: bool = False, seed: int = 0) -> None:
        super().__init__(fast, seed)
        self.alpha = self.beta = self.phi = 0.0
        self._info: dict[str, Any] = {}

    def fit(self, train: pd.DataFrame) -> Ets:
        from statsmodels.tsa.holtwinters import ExponentialSmoothing
        self._check(train)
        _quiet()
        lp = np.log(train["close"].iloc[-MAX_FIT:].to_numpy())
        m = ExponentialSmoothing(lp, trend="add", damped_trend=True).fit()
        p = m.params
        self.alpha, self.beta, self.phi = float(p["smoothing_level"]), float(p["smoothing_trend"]), float(p["damping_trend"])
        self._info, self._fitted = window_info(train), True
        return self

    def predict(self, history: pd.DataFrame, horizon: int, **kw: Any) -> ModelView:
        from statsmodels.tsa.holtwinters import ExponentialSmoothing
        _quiet()
        lp = np.log(history["close"].iloc[-MAX_FIT:].to_numpy())
        m = ExponentialSmoothing(lp, trend="add", damped_trend=True).fit(
            smoothing_level=self.alpha, smoothing_trend=self.beta, damping_trend=self.phi, optimized=False)
        mu = float(m.forecast(horizon)[-1] - lp[-1])
        resid_sd = float(np.std(m.resid[-250:], ddof=1)) if len(m.resid) > 20 else 0.01
        sigma = resid_sd * np.sqrt(horizon)
        band = flat_band(history["close"], horizon)
        q = {str(int(p * 100)): float(np.expm1(mu + sigma * stats.norm.ppf(p))) for p in (0.05, 0.25, 0.5, 0.75, 0.95)}
        return self._view(history, horizon, probs_from_normal(mu, sigma, band), q, band, self._info,
                          drivers=[{"name": "expected log move", "value": round(mu, 5)},
                                   {"name": "smoothing level / trend / damping", "value": f"{self.alpha:.2f} / {self.beta:.2f} / {self.phi:.2f}"}],
                          notes=["Trend extrapolation on prices is usually weak at short horizons."])

    def params(self) -> dict[str, Any]:
        return {"alpha": self.alpha, "beta": self.beta, "phi": self.phi}
