"""Forecast evaluation metrics and the verdict logic ("demonstrated edge" vs "no demonstrated edge").

The bar a model must clear is a BASELINE, not zero: the naive base-rate forecast. The headline test is a Diebold-Mariano
test on the per-forecast Brier loss difference against that baseline, with a Newey-West (HAC) variance so overlapping
outcomes are handled correctly, followed by a Bonferroni correction for the number of models compared. Only then may a model
carry the label "demonstrated edge". Everything else is "no demonstrated edge" (or "insufficient sample").
"""
from __future__ import annotations

import math
from typing import Any

import numpy as np
import pandas as pd
from scipy import stats

from app.eval.calibration import calibration_curve

CLASSES = ("up", "flat", "down")
MIN_EFFECTIVE_N = 30
MAX_FAILURE_RATE = 0.05
Q_LEVELS = (5, 25, 50, 75, 95)


def _probs(p: pd.DataFrame) -> np.ndarray:
    return p[["p_up", "p_flat", "p_down"]].to_numpy(float)


def _onehot(labels: pd.Series) -> np.ndarray:
    return np.column_stack([(labels == c).to_numpy(float) for c in CLASSES])


def brier_per_forecast(p: pd.DataFrame) -> np.ndarray:
    """Multiclass Brier score per forecast: sum over classes of (probability - outcome)^2. Lower is better (0 = perfect)."""
    return ((_probs(p) - _onehot(p["label"])) ** 2).sum(axis=1)


def newey_west_var(d: np.ndarray, lag: int) -> float:
    """Long-run variance of the mean of a series with autocorrelation up to `lag` (Bartlett weights)."""
    d = d - d.mean()
    n = len(d)
    v = float(d @ d / n)
    for k in range(1, lag + 1):
        v += 2 * (1 - k / (lag + 1)) * float(d[k:] @ d[:-k] / n)
    return max(v, 1e-18)


def diebold_mariano(loss_model: np.ndarray, loss_base: np.ndarray, lag: int) -> dict[str, float | None]:
    """One-sided test that the model's average loss is LOWER than the baseline's. Returns the statistic and p-value."""
    d = loss_model - loss_base
    n = len(d)
    if n < 10 or np.allclose(d, 0):
        return {"dm_stat": None, "dm_p": None}
    stat = float(d.mean() / math.sqrt(newey_west_var(d, lag) / n))
    return {"dm_stat": stat, "dm_p": float(stats.norm.cdf(stat))}      # small p => model loss significantly below baseline


def directional(p: pd.DataFrame) -> dict[str, Any]:
    """Hit rate on the up/down calls, ignoring 'flat' outcomes. Tested against 50% and against the naive 'always the
    commoner direction' rate, because in a rising market 'always up' already scores well above 50%."""
    nf = p[p["label"] != "flat"]
    if nf.empty:
        return {"n": 0, "hit_rate": None, "naive_rate": None, "p_vs_half": None, "p_vs_naive": None}
    call = np.where(nf["vote"] == "up", "up", np.where(nf["vote"] == "down", "down", np.where(nf["p_up"] >= nf["p_down"], "up", "down")))
    hits = int((call == nf["label"].to_numpy()).sum())
    n = len(nf)
    naive = max((nf["label"] == "up").mean(), (nf["label"] == "down").mean())
    return {"n": n, "hits": hits, "hit_rate": hits / n, "naive_rate": float(naive),
            "p_vs_half": float(stats.binomtest(hits, n, 0.5).pvalue),
            "p_vs_naive": float(stats.binomtest(hits, n, float(min(max(naive, 1e-6), 1 - 1e-6)), alternative="greater").pvalue)}


def confusion(p: pd.DataFrame) -> dict[str, Any]:
    m = np.zeros((3, 3), int)
    for a, v in zip(p["label"], p["vote"], strict=True):
        m[CLASSES.index(a), CLASSES.index(v)] += 1
    prec = {c: (float(m[i, i] / m[:, i].sum()) if m[:, i].sum() else None) for i, c in enumerate(CLASSES)}
    rec = {c: (float(m[i, i] / m[i].sum()) if m[i].sum() else None) for i, c in enumerate(CLASSES)}
    return {"classes": list(CLASSES), "matrix": m.tolist(), "precision": prec, "recall": rec, "accuracy3": float(np.trace(m) / m.sum())}


def pinball(p: pd.DataFrame) -> dict[str, Any]:
    y = np.expm1(p["actual"].to_numpy())
    per = {}
    for q in Q_LEVELS:
        f = p[f"q{q}"].to_numpy()
        tau = q / 100
        per[str(q)] = float(np.mean(np.maximum(tau * (y - f), (tau - 1) * (y - f))))
    cov90 = float(np.mean((y >= p["q5"].to_numpy()) & (y <= p["q95"].to_numpy())))
    cov50 = float(np.mean((y >= p["q25"].to_numpy()) & (y <= p["q75"].to_numpy())))
    return {"per_quantile": per, "mean": float(np.mean(list(per.values()))), "coverage_90": cov90, "coverage_50": cov50,
            "coverage_note": "Nominal coverage is 90% and 50%. Much lower means the model is overconfident (intervals too narrow)."}


def point_errors(p: pd.DataFrame) -> dict[str, Any]:
    y = p["actual"].to_numpy()
    f = np.log1p(p["q50"].to_numpy())
    mae, rmse = float(np.mean(np.abs(y - f))), float(math.sqrt(np.mean((y - f) ** 2)))
    mae_naive = float(np.mean(np.abs(y)))           # forecast "no change"
    return {"mae": mae, "rmse": rmse, "mae_naive": mae_naive, "mase": mae / mae_naive if mae_naive > 0 else None,
            "note": "MASE below 1 means the median forecast beat 'no change' on average."}


def rank_ic(p: pd.DataFrame, window: int = 63) -> dict[str, Any]:
    """Spearman correlation between the forecast and the realised return (information coefficient), overall and rolling."""
    score = (p["p_up"] - p["p_down"]).to_numpy()
    y = p["actual"].to_numpy()
    if len(p) < 10 or np.std(score) == 0:
        return {"ic": None, "p": None, "rolling": [], "positive_share": None}
    ic, pv = stats.spearmanr(score, y)
    roll = []
    if len(p) >= window:
        for i in range(window, len(p) + 1, max(1, window // 6)):
            s = score[i - window:i]
            roll.append({"date": str(p.index[i - 1].date()), "ic": None if np.std(s) == 0 else float(stats.spearmanr(s, y[i - window:i])[0])})
    vals = [r["ic"] for r in roll if r["ic"] is not None]
    return {"ic": float(ic), "p": float(pv), "rolling": roll, "positive_share": float(np.mean(np.array(vals) > 0)) if vals else None}


def _series(index: pd.DatetimeIndex, values: np.ndarray, cap: int = 200) -> list[dict[str, Any]]:
    step = max(1, len(values) // cap)
    return [{"date": str(index[i].date()), "v": float(values[i])} for i in range(0, len(values), step)]


def evaluate(preds: pd.DataFrame, base: pd.DataFrame | None = None, is_baseline: bool = False) -> dict[str, Any]:
    """Full scorecard for one model's walk-forward predictions (`base` = base_rate baseline predictions, same origins)."""
    h, stride = int(preds.attrs.get("horizon", 5)), int(preds.attrs.get("stride", 5))
    n = len(preds)
    n_eff = n * min(1.0, stride / h)
    brier = brier_per_forecast(preds)
    out: dict[str, Any] = {
        "n_forecasts": n, "n_effective": n_eff, "horizon": h, "stride": stride, "mode": preds.attrs.get("mode"),
        "first": str(preds.index[0].date()), "last": str(preds.index[-1].date()), "failures": int(preds.attrs.get("failures", 0)),
        "failure_rate": float(preds.attrs.get("failures", 0)) / max(1, n + int(preds.attrs.get("failures", 0))),
        "class_shares": {c: float((preds["label"] == c).mean()) for c in CLASSES},
        "brier": float(brier.mean()), "directional": directional(preds), "confusion": confusion(preds),
        "brier_up_vs_not": float(np.mean((preds["p_up"] - (preds["label"] == "up")) ** 2)),
        "calibration_up": calibration_curve(preds["p_up"].to_numpy(), (preds["label"] == "up").to_numpy()),
        "pinball": pinball(preds), "point": point_errors(preds), "rank_ic": rank_ic(preds),
    }
    if base is not None and not is_baseline:
        bb = brier_per_forecast(base.loc[preds.index])
        lag = max(0, math.ceil(h / stride) - 1)
        out["brier_base_rate"] = float(bb.mean())
        out["brier_skill"] = float(1 - brier.mean() / bb.mean()) if bb.mean() > 0 else None
        out.update(diebold_mariano(brier, bb, lag))
        out["cum_skill"] = _series(preds.index, np.cumsum(bb - brier))        # rising line = beating the baseline over time
    ret = np.expm1(preds["actual"].to_numpy())
    pos = (preds["vote"] == "up").to_numpy().astype(float)
    eq, hold = 100 * np.cumprod(1 + ret * pos), 100 * np.cumprod(1 + ret)
    out["equity"] = {"series": _series(preds.index, eq), "buy_hold": _series(preds.index, hold), "exposure": float(pos.mean()),
                     "total_return": float(eq[-1] / 100 - 1), "buy_hold_return": float(hold[-1] / 100 - 1),
                     "note": "Diagnostic only: long when the model's top vote is UP, otherwise in cash; one trade per forecast; NO costs or slippage (Phase 9 adds those)."}
    out["brier_series"] = [{"date": str(d.date()), "v": float(v)} for d, v in zip(preds.index, brier, strict=True)]
    roll_hit = (preds["label"] == preds["vote"]).astype(float).rolling(max(10, min(63, n // 3))).mean().dropna()
    out["rolling_accuracy"] = _series(roll_hit.index, roll_hit.to_numpy())
    return out


def finalize_verdicts(results: dict[str, dict[str, Any]], baselines: set[str], alpha: float = 0.05) -> None:
    """Add `verdict` to each result in place, with a Bonferroni correction over the number of non-baseline models."""
    models = [k for k in results if k not in baselines]
    m = max(1, len(models))
    for k, r in results.items():
        if k in baselines:
            r["verdict"], r["verdict_reason"] = "baseline", "Reference forecast every model must beat."
            continue
        r["p_adjusted"] = None if r.get("dm_p") is None else min(1.0, r["dm_p"] * m)
        if r["n_effective"] < MIN_EFFECTIVE_N:
            r["verdict"], r["verdict_reason"] = "insufficient sample", f"Only about {r['n_effective']:.0f} independent forecasts; need {MIN_EFFECTIVE_N}+."
        elif r.get("failure_rate", 0.0) > MAX_FAILURE_RATE:
            # A model that fails on its hardest forecasts and has them excluded would look better than it is.
            r["verdict"] = "no demonstrated edge"
            r["verdict_reason"] = (f"{r['failures']} forecasts ({r['failure_rate']:.0%}) failed or were implausible and are excluded, so the "
                                   f"results cannot be trusted enough to claim an edge (limit {MAX_FAILURE_RATE:.0%}).")
        elif r.get("brier_skill") is not None and r["brier_skill"] > 0 and r["p_adjusted"] is not None and r["p_adjusted"] < alpha:
            r["verdict"] = "demonstrated edge"
            r["verdict_reason"] = (f"Lower Brier loss than the base-rate baseline (skill {r['brier_skill']:.1%}), significant after correcting "
                                   f"for {m} models tested (adjusted p = {r['p_adjusted']:.3f}). Still in-sample-of-history evidence, not a guarantee.")
        else:
            r["verdict"] = "no demonstrated edge"
            skill = r.get("brier_skill")
            r["verdict_reason"] = ("Did not beat the base-rate baseline" if skill is None or skill <= 0 else
                                   f"Slightly better than the baseline (skill {skill:.1%}) but not statistically significant after correcting "
                                   f"for {m} models (adjusted p = {r['p_adjusted'] if r['p_adjusted'] is not None else float('nan'):.2f}).")
