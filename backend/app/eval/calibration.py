"""Calibration: when a model says 70% up, is it up about 70% of the time?"""
from __future__ import annotations

import numpy as np


def calibration_curve(p: np.ndarray, y: np.ndarray, bins: int = 10) -> dict:
    """Reliability table for a binary event. `p` predicted probabilities, `y` 0/1 outcomes.
    A perfectly calibrated model lies on the diagonal (mean_pred == observed). ECE is the weighted average gap."""
    p, y = np.asarray(p, float), np.asarray(y, float)
    edges = np.linspace(0, 1, bins + 1)
    idx = np.clip(np.digitize(p, edges[1:-1]), 0, bins - 1)
    rows, ece = [], 0.0
    for b in range(bins):
        m = idx == b
        if not m.any():
            continue
        mp, ob = float(p[m].mean()), float(y[m].mean())
        rows.append({"bin": f"{edges[b]:.1f}-{edges[b + 1]:.1f}", "mean_pred": mp, "observed": ob, "n": int(m.sum())})
        ece += m.mean() * abs(mp - ob)
    return {"rows": rows, "ece": float(ece) if len(p) else None}
