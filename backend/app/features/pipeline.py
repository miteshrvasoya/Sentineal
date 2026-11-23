"""Versioned feature pipeline. All sets are causal; see tests/test_leakage.py."""
from __future__ import annotations

import hashlib
import json
from collections.abc import Callable

import pandas as pd

from app.features import momentum, trend, volatility, volume

FEATURE_VERSION = "1"
SETS: dict[str, Callable[..., pd.DataFrame]] = {
    "trend": trend.compute, "momentum": momentum.compute,
    "volatility": volatility.compute, "volume": volume.compute,
}


def to_frame(prices: pd.DataFrame) -> pd.DataFrame:
    """DB frame (index = UTC epoch seconds) -> UTC DatetimeIndex frame."""
    df = prices[["open", "high", "low", "close", "volume"]].astype(float).copy()
    df.index = pd.to_datetime(df.index, unit="s", utc=True)
    return df


def compute_features(df: pd.DataFrame, sets: list[str] | None = None, params: dict | None = None) -> pd.DataFrame:
    names = sets or list(SETS)
    unknown = [s for s in names if s not in SETS]
    if unknown:
        raise ValueError(f"unknown indicator set(s) {unknown}; available {list(SETS)}")
    params = params or {}
    frames = [SETS[s](df, **params.get(s, {})) for s in names]
    return pd.concat(frames, axis=1).replace([float("inf"), float("-inf")], float("nan"))


def feature_hash(columns: list[str], sets: list[str]) -> str:
    """Stable hash of the feature set, stored with trained models (Phase 7+)."""
    return hashlib.sha1(json.dumps([FEATURE_VERSION, sorted(sets), sorted(columns)]).encode()).hexdigest()[:12]
