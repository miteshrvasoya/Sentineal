"""EXPERIMENTAL deep-learning models: GRU / LSTM sequence classifiers on windows of technical features (PyTorch, CPU).

A recurrent network reads the last 20 days of 15 standardised features and outputs probabilities of up / flat / down. It is
marked experimental because small recurrent networks on a few hundred to a few thousand noisy daily rows overfit very easily:
expect them to lose to the simple baselines more often than not. They exist so that claim can be TESTED, not assumed.

  deep_gru, deep_lstm  : trained on this stock only.
  deep_gru_pooled      : trained on this stock plus the other stored stocks (more data usually generalises better; the
                         comparison with the per-stock model is shown, not assumed). Pooled data is cut at the same date as
                         the stock's training data, so no other stock's future ever leaks in.

Early stopping uses a time-ordered validation tail separated by a purge gap. The network is NOT refitted afterwards.
Requires PyTorch (`uv sync --extra deep`).
"""
from __future__ import annotations

import copy
import warnings
from typing import Any

import numpy as np
import pandas as pd

from app.models.base import Model, ModelError, ModelView, flat_band, window_info
from app.models.ml import QS, choose_shrink, logloss, shrink_to_prior
from app.models.ml_features import MIN_ROWS, build_dataset, price_features

FEATS = ["ret_1d", "ret_5d", "rsi", "macd_hist_pct", "atr_pct", "rv_cc", "cmf", "rvol", "close_vs_ema20", "close_vs_ema50",
         "bb_pctb", "zscore_20", "volume_zscore", "dist_52w_high", "adx"]
WIN = 20
HIDDEN = 24


def torch_available() -> tuple[bool, str]:
    try:
        import torch  # noqa: F401
        return True, ""
    except Exception:  # noqa: BLE001
        return False, "PyTorch is not installed. Run `uv sync --extra deep` (large download) to enable the deep models."


def _windows(F: np.ndarray, positions: np.ndarray) -> np.ndarray:
    return np.stack([F[p - WIN + 1:p + 1] for p in positions]) if len(positions) else np.zeros((0, WIN, F.shape[1]))


class _Deep(Model):
    kind = "deep"
    experimental = True
    cell = "gru"
    pooled = False
    needs: str | None = None

    def __init__(self, fast: bool = False, seed: int = 0, horizon: int = 5, aux: dict | None = None, **kw: Any) -> None:
        super().__init__(fast, seed)
        self.horizon, self.aux = horizon, aux or {}
        self.shrink = 0.0
        self.prior = np.array([1 / 3, 1 / 3, 1 / 3])
        self._info: dict[str, Any] = {}

    @classmethod
    def availability(cls) -> tuple[bool, str]:
        ok, why = torch_available()
        if ok and cls.pooled:
            return True, ""
        return ok, why

    def _net(self, n_feat: int) -> Any:
        import torch.nn as nn

        class Net(nn.Module):
            def __init__(s) -> None:
                super().__init__()
                s.rnn = (nn.GRU if self.cell == "gru" else nn.LSTM)(n_feat, HIDDEN, batch_first=True)
                s.drop = nn.Dropout(0.2)
                s.out = nn.Linear(HIDDEN, 3)

            def forward(s, x: Any) -> Any:
                h, _ = s.rnn(x)
                return s.out(s.drop(h[:, -1]))
        return Net()

    def _dataset(self, frame: pd.DataFrame, mu: np.ndarray | None = None, sd: np.ndarray | None = None):
        ds = build_dataset(frame, self.horizon, "price")
        F = price_features(frame)[FEATS].to_numpy(float)
        if mu is None:
            mu, sd = np.nanmean(F, axis=0), np.nanstd(F, axis=0)
            sd = np.where(sd < 1e-9, 1.0, sd)
        Z = np.nan_to_num((F - mu) / sd)
        pos = frame.index.get_indexer(ds.index)
        keep = pos >= WIN - 1
        return _windows(Z, pos[keep]).astype(np.float32), ds.y[keep], ds.ret[keep], mu, sd

    def fit(self, train: pd.DataFrame) -> _Deep:
        import torch
        import torch.nn as nn
        ok, why = torch_available()
        if not ok:
            raise ModelError(why)
        self._check(train)
        warnings.filterwarnings("ignore")
        torch.set_num_threads(2)
        torch.manual_seed(self.seed)
        Xo, yo, ro, mu, sd = self._dataset(train)
        n = len(yo)
        if n < MIN_ROWS:
            raise ModelError(f"{self.name} needs at least {MIN_ROWS} labelled windows, has {n}")
        n_val = max(50, int(0.2 * n))
        cut = n - n_val - self.horizon
        if cut < 100:
            raise ModelError(f"{self.name}: not enough rows left after the validation split")
        Xt, yt, rt = Xo[:cut], yo[:cut], ro[:cut]
        Xv, yv, rv = Xo[n - n_val:], yo[n - n_val:], ro[n - n_val:]
        if self.pooled:
            end = train.index[-1]
            for _name, other in (self.aux.get("pool") or {}).items():
                o = other.loc[:end]                                  # cut at the same date: no other stock's future
                if len(o) < 300:
                    continue
                try:
                    Xp, yp, rp, _, _ = self._dataset(o, mu, sd)
                except Exception:  # noqa: BLE001  a bad peer frame must not break training
                    continue
                Xt, yt, rt = np.concatenate([Xt, Xp]), np.concatenate([yt, yp]), np.concatenate([rt, rp])
            self._pool_rows = len(yt) - cut
        net = self._net(len(FEATS))
        opt = torch.optim.AdamW(net.parameters(), lr=3e-3, weight_decay=1e-3)
        lossf = nn.CrossEntropyLoss()
        Xt_t, yt_t = torch.from_numpy(Xt), torch.from_numpy(yt.astype(np.int64))
        Xv_t, yv_t = torch.from_numpy(Xv), torch.from_numpy(yv.astype(np.int64))
        rng = np.random.default_rng(self.seed)
        best, best_state, bad, epochs = 9e9, None, 0, 0
        for epoch in range(12 if self.fast else 40):
            net.train()
            order = rng.permutation(len(yt))
            for i in range(0, len(order), 64):
                b = order[i:i + 64]
                opt.zero_grad()
                lossf(net(Xt_t[b]), yt_t[b]).backward()
                opt.step()
            net.eval()
            with torch.no_grad():
                vl = float(lossf(net(Xv_t), yv_t))
            epochs = epoch + 1
            if vl < best - 1e-4:
                best, best_state, bad = vl, copy.deepcopy(net.state_dict()), 0
            else:
                bad += 1
                if bad >= 5:
                    break
        net.load_state_dict(best_state)
        net.eval()
        self.net, self.mu, self.sd, self.epochs, self.val_best = net, mu, sd, epochs, best
        with torch.no_grad():
            pv = torch.softmax(net(Xv_t), dim=1).numpy()
        prior_fit = np.bincount(yt, minlength=3) / len(yt)
        self.shrink, losses = choose_shrink(yv, pv, prior_fit)
        self.prior = prior_fit
        # Return quantiles: expected return from class means, plus empirical residual quantiles on the validation tail.
        self.class_mean = np.array([float(rt[yt == k].mean()) if (yt == k).any() else 0.0 for k in range(3)])
        resid = rv - shrink_to_prior(pv, self.prior, self.shrink) @ self.class_mean
        self.offsets = np.quantile(resid, QS)
        self.val_loss = {"raw": logloss(yv, pv), "calibrated": float(losses[int(round(self.shrink * 10))]), "trust_in_model": 1.0 - self.shrink,
                         "base_rate_loss": logloss(yv, np.tile(prior_fit, (len(yv), 1)))}
        self._info = {**window_info(train), "labelled_windows": n, "validation_rows": int(n_val), "window_days": WIN, "features": len(FEATS)}
        self._fitted = True
        return self

    def predict(self, history: pd.DataFrame, horizon: int, **kw: Any) -> ModelView:
        import torch
        if horizon != self.horizon:
            raise ModelError(f"{self.name} was trained for a {self.horizon}-day horizon, not {horizon}")
        F = price_features(history)[FEATS].to_numpy(float)[-WIN:]
        if len(F) < WIN:
            raise ModelError("not enough history for one window")
        Z = np.nan_to_num((F - self.mu) / self.sd).astype(np.float32)[None]
        with torch.no_grad():
            p = shrink_to_prior(torch.softmax(self.net(torch.from_numpy(Z)), dim=1).numpy(), self.prior, self.shrink)[0]
        point = float(p @ self.class_mean)
        q = np.sort(point + self.offsets)
        quantiles = {str(int(k * 100)): float(np.expm1(v)) for k, v in zip(QS, q, strict=True)}
        drivers = [{"name": "network", "value": f"{self.cell.upper()}, {HIDDEN} units, {WIN}-day window"},
                   {"name": "epochs before early stop", "value": self.epochs},
                   {"name": "validation loss raw -> calibrated", "value": f"{self.val_loss['raw']:.3f} -> {self.val_loss['calibrated']:.3f}"}]
        if self.pooled:
            drivers.append({"name": "extra rows from other stocks", "value": int(getattr(self, "_pool_rows", 0))})
        view = self._view(history, horizon, (float(p[0]), float(p[1]), float(p[2])), quantiles, flat_band(history["close"], horizon), self._info,
                          drivers=drivers, notes=["EXPERIMENTAL: small recurrent networks overfit noisy daily data easily. Trust the walk-forward verdict.",
                                                  "Early-stopped on a held-out tail and not refitted afterwards."])
        view.extras["calibration"] = self.val_loss
        return view

    def params(self) -> dict[str, Any]:
        return {"cell": self.cell, "hidden": HIDDEN, "window": WIN, "epochs": getattr(self, "epochs", 0), "shrink_to_base_rate": self.shrink, "pooled": self.pooled}


class DeepGru(_Deep):
    name, cell = "deep_gru", "gru"
    description = "EXPERIMENTAL GRU sequence model on 20-day windows of technical features, trained on this stock only."


class DeepLstm(_Deep):
    name, cell = "deep_lstm", "lstm"
    description = "EXPERIMENTAL LSTM sequence model on 20-day windows of technical features, trained on this stock only."


class DeepGruPooled(_Deep):
    name, cell, pooled, needs = "deep_gru_pooled", "gru", True, "pool"
    description = "EXPERIMENTAL GRU trained on this stock plus other stored stocks (cut at the same date). Compare with deep_gru."
