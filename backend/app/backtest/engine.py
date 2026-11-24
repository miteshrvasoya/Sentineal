"""Event-driven daily backtest, long-only, one position.

Timing: the signal is decided at the close of bar t and filled at the OPEN of bar t+1 (never at the price it was computed
from). Fills are moved against you by the slippage assumption, and every fill pays the cost model. An optional stop-loss
is checked against each bar's low and fills at the stop (or at the open if price gapped through it).
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from app.backtest.costs import INDIA_DELIVERY, CostModel


@dataclass
class BTConfig:
    capital: float = 1_000_000.0
    alloc: float = 1.0                  # fraction of cash committed on each entry
    stop_loss: float | None = None      # e.g. 0.08 = exit if price falls 8% below entry
    costs: CostModel = field(default_factory=lambda: INDIA_DELIVERY)
    start: int = 0                      # first bar at which trading is allowed (after indicator warm-up)


@dataclass
class Result:
    equity: pd.Series
    trades: list[dict]
    paid: dict[str, float]              # itemised costs paid over the run
    slippage_paid: float
    exposure: float


def _size(cash: float, alloc: float, px: float, costs: CostModel) -> int:
    budget = cash * alloc
    qty = int(math.floor(budget / (px * (1 + 0.004)))) if px > 0 else 0   # first guess leaves room for charges
    while qty > 0 and px * qty + costs.charges("buy", px * qty)["total"] > cash:
        qty -= 1
    return qty


def run(df: pd.DataFrame, signal: np.ndarray, cfg: BTConfig) -> Result:
    n = len(df)
    if len(signal) != n:
        raise ValueError("signal length must match the data")
    o, h, lo, c = (df[k].to_numpy(float) for k in ("open", "high", "low", "close"))
    idx = df.index
    slip = cfg.costs.slippage_bps / 1e4
    cash, qty, entry_px, entry_i, entry_cost = cfg.capital, 0, 0.0, 0, 0.0
    blocked = False
    equity = np.full(n, np.nan)
    trades: list[dict] = []
    paid = {k: 0.0 for k in ("brokerage", "stt", "exchange", "sebi", "stamp", "gst", "dp")}
    slip_paid = 0.0
    held = 0

    def buy(i: int, ref_px: float) -> None:
        nonlocal cash, qty, entry_px, entry_i, entry_cost, slip_paid
        px = ref_px * (1 + slip)
        q = _size(cash, cfg.alloc, px, cfg.costs)
        if q <= 0:
            return
        ch = cfg.costs.charges("buy", px * q)
        cash -= px * q + ch["total"]
        slip_paid += (px - ref_px) * q
        for k in paid:
            paid[k] += ch[k]
        qty, entry_px, entry_i, entry_cost = q, px, i, ch["total"]

    def sell(i: int, ref_px: float, reason: str) -> None:
        nonlocal cash, qty, slip_paid
        px = ref_px * (1 - slip)
        ch = cfg.costs.charges("sell", px * qty)
        cash += px * qty - ch["total"]
        slip_paid += (ref_px - px) * qty
        for k in paid:
            paid[k] += ch[k]
        costs = entry_cost + ch["total"]
        gross = (px - entry_px) * qty
        basis = entry_px * qty
        trades.append({"entry_date": str(idx[entry_i].date()), "exit_date": str(idx[i].date()), "entry_price": round(entry_px, 4), "exit_price": round(px, 4),
                       "qty": qty, "gross_pnl": round(gross, 2), "costs": round(costs, 2), "net_pnl": round(gross - costs, 2),
                       "return_pct": round((gross - costs) / basis, 6), "bars": i - entry_i, "exit_reason": reason})
        qty = 0

    for i in range(n):
        if i >= 1 and i - 1 >= cfg.start:
            want = bool(signal[i - 1])
            if not want:
                blocked = False
            if qty == 0 and want and not blocked:
                buy(i, o[i])
            elif qty > 0 and not want:
                sell(i, o[i], "signal")
        if qty > 0 and cfg.stop_loss is not None:
            stop = entry_px * (1 - cfg.stop_loss)
            if lo[i] <= stop:
                sell(i, min(stop, o[i]) if i > entry_i else stop, "stop")
                blocked = True
        if qty > 0:
            held += 1
        equity[i] = cash + qty * c[i]
    if qty > 0:                                         # close at the last close so every trade is accounted for
        sell(n - 1, c[-1], "end of test")
        equity[-1] = cash
    eq = pd.Series(equity, index=idx)
    return Result(eq, trades, paid, slip_paid, held / max(1, n - cfg.start))
