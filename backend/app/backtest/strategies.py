"""Rule-based strategies. Each maps an OHLCV frame to a 0/1 'want to be long' signal.

`signal[t]` may use bars up to and including t only (checked by a prefix-invariance test). The engine acts on it at the
NEXT bar's open, so a signal can never trade on the price it was computed from.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from itertools import product

import numpy as np
import pandas as pd


def _ema(s: pd.Series, n: int) -> pd.Series:
    return s.ewm(span=n, adjust=False, min_periods=n).mean()


def _rsi(close: pd.Series, n: int) -> pd.Series:
    d = close.diff()
    up, dn = d.clip(lower=0).ewm(alpha=1 / n, adjust=False, min_periods=n).mean(), (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False, min_periods=n).mean()
    return 100 - 100 / (1 + up / dn.replace(0, np.nan))


def _stateful(enter: np.ndarray, exit_: np.ndarray, valid: np.ndarray) -> np.ndarray:
    """Position that turns on at `enter`, off at `exit_`, holding in between."""
    pos = np.zeros(len(enter), dtype=int)
    on = 0
    for i in range(len(enter)):
        if not valid[i]:
            on = 0
        elif on == 0 and enter[i]:
            on = 1
        elif on == 1 and exit_[i]:
            on = 0
        pos[i] = on
    return pos


def ma_cross(df: pd.DataFrame, fast: int = 20, slow: int = 50) -> tuple[np.ndarray, int]:
    f, s = _ema(df["close"], fast), _ema(df["close"], slow)
    valid = s.notna().to_numpy()
    return ((f > s).to_numpy() & valid).astype(int), slow


def rsi_reversion(df: pd.DataFrame, period: int = 14, buy_below: float = 30, sell_above: float = 55) -> tuple[np.ndarray, int]:
    r = _rsi(df["close"], period)
    valid = r.notna().to_numpy()
    return _stateful((r < buy_below).to_numpy(), (r > sell_above).to_numpy(), valid), period + 1


def breakout(df: pd.DataFrame, lookback: int = 55, exit_lookback: int = 20) -> tuple[np.ndarray, int]:
    hi = df["high"].rolling(lookback).max().shift(1)
    lo = df["low"].rolling(exit_lookback).min().shift(1)
    c = df["close"]
    valid = (hi.notna() & lo.notna()).to_numpy()
    return _stateful((c > hi).to_numpy(), (c < lo).to_numpy(), valid), max(lookback, exit_lookback) + 1


def momentum(df: pd.DataFrame, lookback: int = 126) -> tuple[np.ndarray, int]:
    r = df["close"].pct_change(lookback)
    return ((r > 0).to_numpy() & r.notna().to_numpy()).astype(int), lookback + 1


@dataclass(frozen=True)
class Strategy:
    name: str
    title: str
    description: str
    fn: Callable[..., tuple[np.ndarray, int]]
    defaults: dict[str, float]
    grid: dict[str, list[float]] = field(default_factory=dict)

    def signal(self, df: pd.DataFrame, **params: float) -> tuple[np.ndarray, int]:
        p = {**self.defaults, **{k: type(self.defaults[k])(v) for k, v in params.items() if k in self.defaults}}
        unknown = set(params) - set(self.defaults)
        if unknown:
            raise ValueError(f"unknown parameter(s) {sorted(unknown)} for {self.name}; allowed {sorted(self.defaults)}")
        if self.name == "ma_cross" and p["fast"] >= p["slow"]:
            raise ValueError("ma_cross needs fast < slow")
        return self.fn(df, **p)

    def combos(self) -> list[dict[str, float]]:
        keys = list(self.grid)
        out = [dict(zip(keys, v, strict=True)) for v in product(*(self.grid[k] for k in keys))]
        if self.name == "ma_cross":
            out = [c for c in out if c["fast"] < c["slow"]]
        return out


STRATEGIES: dict[str, Strategy] = {s.name: s for s in [
    Strategy("ma_cross", "Moving-average crossover", "Long while the fast EMA is above the slow EMA (a trend-following rule).", ma_cross,
             {"fast": 20, "slow": 50}, {"fast": [10, 20, 30], "slow": [50, 100, 150, 200]}),
    Strategy("rsi_reversion", "RSI mean reversion", "Buy after RSI drops below a threshold, sell when it recovers (bets on bounce-backs).", rsi_reversion,
             {"period": 14, "buy_below": 30.0, "sell_above": 55.0}, {"period": [7, 14, 21], "buy_below": [25.0, 30.0, 35.0], "sell_above": [50.0, 55.0, 65.0]}),
    Strategy("breakout", "Channel breakout (Donchian)", "Buy a new N-day high, sell a new shorter-window low (a trend-following rule).", breakout,
             {"lookback": 55, "exit_lookback": 20}, {"lookback": [20, 40, 55, 100], "exit_lookback": [10, 20, 30]}),
    Strategy("momentum", "Time-series momentum", "Long while the return over the last N days is positive.", momentum,
             {"lookback": 126}, {"lookback": [21, 63, 126, 189, 252]}),
]}


def get(name: str) -> Strategy:
    if name not in STRATEGIES:
        raise ValueError(f"unknown strategy {name!r}; choose from {list(STRATEGIES)}")
    return STRATEGIES[name]
