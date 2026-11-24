"""Hidden Markov Model regime detection (3 hidden states) on daily return and absolute return.

Idea: the market switches between hidden "regimes" (for example calm uptrend, choppy sideways, turbulent selloff), each
with its own average return and volatility. The HMM learns those regimes and the odds of switching between them, then
tells you how likely each regime is NOW.

IMPORTANT (no hindsight): library "smoothed" probabilities use data AFTER each day. Here probabilities are FILTERED with
a forward pass only, so the regime shown for any day uses information up to that day. The training-sample statistics
are descriptive; labels are relative (the lowest-return regime is called "bear" even if its average is positive).
"""
from __future__ import annotations

import warnings
from typing import Any

import numpy as np
import pandas as pd
from scipy.special import logsumexp
from scipy.stats import multivariate_normal

from app.models.base import (
    Model,
    ModelView,
    flat_band,
    log_returns,
    probs_from_samples,
    quantiles_from_samples,
    window_info,
)

K = 3
MAX_FIT = 1500
LABELS = ("bear", "sideways", "bull")


def features(r: np.ndarray) -> np.ndarray:
    return np.c_[r * 100, np.abs(r) * 100]


class HmmRegime(Model):
    name = "hmm_regime"
    description = "3-state Gaussian hidden Markov model: current regime probabilities and a regime-mixture forecast."

    def __init__(self, fast: bool = False, seed: int = 0) -> None:
        super().__init__(fast, seed)
        self.pi = self.A = self.means = self.covs = None
        self.order: list[int] = []
        self._info: dict[str, Any] = {}

    def fit(self, train: pd.DataFrame) -> HmmRegime:
        from hmmlearn.hmm import GaussianHMM
        self._check(train)
        warnings.filterwarnings("ignore")
        X = features(log_returns(train).iloc[-MAX_FIT:].to_numpy())
        best, best_ll = None, -np.inf
        for s in range(1 if self.fast else 3):
            m = GaussianHMM(K, covariance_type="diag", n_iter=30 if self.fast else 100, tol=1e-3, min_covar=1e-4, random_state=self.seed + s)
            try:
                m.fit(X)
                ll = m.score(X)
            except Exception:  # noqa: BLE001  a bad initialisation can fail; try the next one
                continue
            if ll > best_ll:
                best, best_ll = m, ll
        if best is None:
            raise ValueError("HMM did not converge")
        self.order = list(np.argsort(best.means_[:, 0]))           # lowest mean return first: bear, sideways, bull
        self.pi, self.A = best.startprob_[self.order], best.transmat_[np.ix_(self.order, self.order)]
        self.means = best.means_[self.order]
        self.covs = np.array([np.diag(best.covars_[i]) for i in self.order]) if best.covars_.ndim == 3 else best.covars_[self.order]
        self._info, self._fitted = window_info(train), True
        self._train_X = X
        return self

    def filtered(self, X: np.ndarray) -> np.ndarray:
        """Forward algorithm: P(state_t | observations up to t) for every t. Uses no future data."""
        T = len(X)
        logb = np.column_stack([multivariate_normal(self.means[k], np.diag(self.covs[k]), allow_singular=True).logpdf(X) for k in range(K)])
        logA = np.log(self.A + 1e-12)
        alpha = np.zeros((T, K))
        a = np.log(self.pi + 1e-12) + logb[0]
        alpha[0] = np.exp(a - logsumexp(a))
        for t in range(1, T):
            a = logb[t] + logsumexp(np.log(alpha[t - 1] + 1e-300)[:, None] + logA, axis=0)
            alpha[t] = np.exp(a - logsumexp(a))
        return alpha

    def regime_table(self) -> list[dict[str, Any]]:
        al = self.filtered(self._train_X)
        share = np.bincount(al.argmax(1), minlength=K) / len(al)
        out = []
        for k in range(K):
            mu_d, var_d = self.means[k, 0] / 100, self.covs[k, 0] / 1e4
            out.append({"regime": LABELS[k], "mean_return_annual": float(mu_d * 252), "volatility_annual": float(np.sqrt(var_d) * np.sqrt(252)),
                        "share_of_days": float(share[k]), "expected_duration_days": float(1 / max(1 - self.A[k, k], 1e-6)),
                        "stay_probability": float(self.A[k, k])})
        return out

    def predict(self, history: pd.DataFrame, horizon: int, **kw: Any) -> ModelView:
        warnings.filterwarnings("ignore")
        r = log_returns(history).iloc[-750:].to_numpy()
        al = self.filtered(features(r))
        now = al[-1]
        rng = self.rng(len(history))
        # Simulate regime paths from the current filtered distribution and draw each day's return from its regime.
        state = rng.choice(K, size=self.n_sims, p=now / now.sum())
        total = np.zeros(self.n_sims)
        cum = np.cumsum(self.A, axis=1)
        mu, sd = self.means[:, 0] / 100, np.sqrt(self.covs[:, 0]) / 100
        for _ in range(horizon):
            state = (rng.random(self.n_sims)[:, None] > cum[state]).sum(axis=1).clip(0, K - 1)    # next regime
            total += rng.normal(mu[state], sd[state])
        band = flat_band(history["close"], horizon)
        drivers = [{"name": f"P({LABELS[k]})", "value": f"{now[k] * 100:.0f}%"} for k in range(K)][::-1]
        view = self._view(history, horizon, probs_from_samples(total, band), quantiles_from_samples(total), band, self._info, drivers=drivers,
                          notes=["Regimes are learned from the stock's own history. Filtered probabilities use no future data."])
        dates = [str(d.date()) for d in history.index[-len(al):]][-500:]
        view.extras.update({
            "regime_probs": {LABELS[k]: float(now[k]) for k in range(K)}, "current_regime": LABELS[int(now.argmax())],
            "regime_table": self.regime_table() if kw.get("detail", True) else [],
            "timeline": {"dates": dates, "regime": al.argmax(1)[-500:].tolist(), "prob": al.max(1)[-500:].round(3).tolist(), "labels": list(LABELS)},
        })
        return view

    def params(self) -> dict[str, Any]:
        return {"transition_matrix": self.A.round(4).tolist(), "means": self.means.round(4).tolist()}
