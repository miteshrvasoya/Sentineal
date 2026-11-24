"""GARCH-family volatility models: GARCH(1,1), GJR-GARCH(1,1,1) and EGARCH(1,1,1) with Student-t errors.

These forecast how WIDE the distribution of future returns is (volatility clusters: calm follows calm, storms follow
storms), much more reliably than they forecast direction. The mean is a constant, so p(up) hugs the base rate; the value is
in the spread and the volatility cone.

At fit time the parameters are estimated. At predict time they are re-applied (arch `fix`) to the newest history, so the
conditional volatility is current without a refit per origin.
"""
from __future__ import annotations

import warnings
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

MAX_FIT = 1000
ANN = 252
CONE_WINDOWS = (5, 10, 21, 42, 63)


class _Garch(Model):
    spec: dict[str, Any] = {}
    label = ""

    def __init__(self, fast: bool = False, seed: int = 0, **kw: Any) -> None:
        super().__init__(fast, seed)
        self.fit_params: pd.Series | None = None
        self._info: dict[str, Any] = {}

    def _am(self, r: pd.Series):  # type: ignore[no-untyped-def]
        from arch import arch_model
        return arch_model(r, mean="Constant", dist="t", **self.spec)

    def fit(self, train: pd.DataFrame) -> _Garch:
        self._check(train)
        warnings.filterwarnings("ignore")
        r = log_returns(train).iloc[-MAX_FIT:] * 100
        self.fit_params = self._am(r).fit(disp="off", show_warning=False).params
        self._info, self._fitted = window_info(train), True
        return self

    def _forecast(self, r: pd.Series, horizon: int, sims: int):  # type: ignore[no-untyped-def]
        fixed = self._am(r).fix(self.fit_params)
        # Filtered historical simulation: resample the model's OWN standardised past shocks. Tails therefore come from the
        # stock's real history and are bounded. (Free-running Student-t shocks made EGARCH's log-variance recursion explode
        # at some origins, giving infinite forecasts.) random_state makes the draws reproducible.
        return fixed.forecast(horizon=horizon, method="bootstrap", simulations=sims, reindex=False,
                              random_state=np.random.RandomState(self.seed + len(r)))

    def predict(self, history: pd.DataFrame, horizon: int, cone: bool = True, **kw: Any) -> ModelView:
        warnings.filterwarnings("ignore")
        assert self.fit_params is not None
        r = log_returns(history).iloc[-MAX_FIT:] * 100
        f = self._forecast(r, horizon, self.n_sims)
        samples = f.simulations.values[0].sum(axis=1) / 100                   # (sims,) cumulative h-day log return
        var = f.variance.values[0]                                            # per-step variance forecast, in %^2
        band = flat_band(history["close"], horizon)
        p = self.fit_params
        persistence = float(p.get("alpha[1]", 0) + p.get("beta[1]", 0) + 0.5 * p.get("gamma[1]", 0)) if "EGARCH" not in self.label else float(p.get("beta[1]", 0))
        view = self._view(history, horizon, probs_from_samples(samples, band), quantiles_from_samples(samples), band, self._info,
                          drivers=[{"name": "forecast volatility (annualised)", "value": f"{np.sqrt(var.mean() * ANN) / 100 * 100:.1f}%"},
                                   {"name": "shock persistence", "value": round(persistence, 3)},
                                   {"name": "tail fatness (t dof)", "value": round(float(p.get("nu", np.nan)), 1)}]
                          + ([{"name": "leverage effect (gamma)", "value": round(float(p["gamma[1]"]), 3)}] if "gamma[1]" in p else []),
                          notes=["Better at how wide the outcomes are than at which way. p(up) stays near the base rate."])
        view.extras["vol_forecast_annualised"] = float(np.sqrt(var.mean() * ANN) / 100)
        if cone:
            view.extras["vol_cone"] = self.vol_cone(history)
        return view

    def vol_cone(self, history: pd.DataFrame) -> dict[str, Any]:
        """Model forecast of annualised volatility for several horizons, against the range realised volatility has
        actually covered over the last ~3 years for the same window length."""
        r = log_returns(history).iloc[-MAX_FIT:] * 100
        hmax = max(CONE_WINDOWS)
        f = self._forecast(r, hmax, 300 if self.fast else 600)
        var = f.variance.values[0]
        lr = log_returns(history)
        out: dict[str, Any] = {"horizons": list(CONE_WINDOWS), "forecast": [], "hist_min": [], "hist_p25": [], "hist_p50": [],
                               "hist_p75": [], "hist_max": [], "current": []}
        for k in CONE_WINDOWS:
            out["forecast"].append(float(np.sqrt(var[:k].mean() * ANN) / 100))
            rv = (lr.rolling(k).std() * np.sqrt(ANN)).dropna().iloc[-756:]
            q = np.quantile(rv, [0, 0.25, 0.5, 0.75, 1]) if len(rv) else [np.nan] * 5
            for key, v in zip(("hist_min", "hist_p25", "hist_p50", "hist_p75", "hist_max"), q, strict=True):
                out[key].append(float(v))
            out["current"].append(float(rv.iloc[-1]) if len(rv) else float("nan"))
        return out

    def params(self) -> dict[str, Any]:
        return {k: float(v) for k, v in (self.fit_params.items() if self.fit_params is not None else [])}


class Garch(_Garch):
    name, label = "garch", "GARCH"
    spec = {"vol": "GARCH", "p": 1, "q": 1}
    description = "GARCH(1,1) with Student-t errors: forecasts volatility and the width of the return distribution."


class GjrGarch(_Garch):
    name, label = "gjr_garch", "GJR-GARCH"
    spec = {"vol": "GARCH", "p": 1, "o": 1, "q": 1}
    description = "GJR-GARCH: like GARCH but bad news raises volatility more than good news (leverage effect)."


class Egarch(_Garch):
    name, label = "egarch", "EGARCH"
    spec = {"vol": "EGARCH", "p": 1, "o": 1, "q": 1}
    description = "EGARCH: models log-volatility, allows asymmetric reactions without sign constraints."
