"""Orchestration: run a strategy, compare with buy-and-hold, bootstrap, luck test, optional parameter search with a
held-out final stretch, red flags and the summary that feeds the AI backtest reviewer."""
from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from app.backtest import stats
from app.backtest.costs import NO_COSTS, CostModel
from app.backtest.engine import BTConfig, Result, run
from app.backtest.strategies import Strategy

MIN_BARS = 250


def _series(s: pd.Series, n: int = 800, rebase: bool = False) -> list[dict]:
    s = s.dropna().iloc[-n:]
    if rebase and len(s):
        s = s / s.iloc[0] * 100
    return [{"date": str(d.date()), "v": round(float(v), 4)} for d, v in s.items()]


def _slice_result(res: Result, i0: int) -> tuple[pd.Series, list[dict]]:
    eq = res.equity.iloc[i0:]
    t0 = str(eq.index[0].date())
    return eq, [t for t in res.trades if t["exit_date"] >= t0]


def _score(df: pd.DataFrame, strat: Strategy, params: dict, cfg: BTConfig, rf: float) -> float:
    sig, warm = strat.signal(df, **params)
    res = run(df, sig, BTConfig(cfg.capital, cfg.alloc, cfg.stop_loss, cfg.costs, max(cfg.start, warm)))
    eq = res.equity.iloc[max(cfg.start, warm):].dropna()
    if len(eq) < 30:
        return float("-inf")
    return stats.sharpe_of(eq.pct_change().dropna().to_numpy() - rf / stats.TRADING_DAYS)


def red_flag_inputs(m: dict, *, costs_included: bool, oos_fraction: float | None, n_tuned: int, p: float | None) -> dict[str, Any]:
    """The summary the Phase 8A reviewer and its deterministic red flags consume."""
    return {"n_trades": m.get("n_trades"), "total_return": m.get("total_return"), "sharpe": m.get("sharpe"), "max_drawdown": m.get("max_drawdown"),
            "years": m.get("years"), "costs_included": costs_included, "oos_fraction": oos_fraction, "n_params_tuned": n_tuned,
            "top5_trade_share": m.get("top5_trade_share"), "bootstrap_p": p}


def backtest(df: pd.DataFrame, strat: Strategy, params: dict[str, float], *, costs: CostModel, capital: float = 1_000_000.0, alloc: float = 1.0,
             stop_loss: float | None = None, oos_fraction: float = 0.0, optimize: bool = False, rf: float = 0.07, reps: int = 2000,
             seed: int = 0) -> dict[str, Any]:
    n = len(df)
    if n < MIN_BARS:
        raise ValueError(f"need at least {MIN_BARS} daily bars, have {n}")
    if not 0 <= oos_fraction <= 0.6:
        raise ValueError("oos_fraction must be between 0 and 0.6")
    if optimize and oos_fraction < 0.1:
        raise ValueError("a parameter search needs a held-out stretch: set oos_fraction to at least 0.1")
    base_cfg = BTConfig(capital, alloc, stop_loss, costs, 0)
    split = int(n * (1 - oos_fraction)) if oos_fraction else n
    notes: list[str] = []
    search = None
    chosen = dict(params)
    if optimize:
        combos = strat.combos()
        is_df = df.iloc[:split]
        scored = sorted(((_score(is_df, strat, c, base_cfg, rf), c) for c in combos), key=lambda x: -x[0])
        scored = [(s, c) for s, c in scored if np.isfinite(s)]
        if not scored:
            raise ValueError("no parameter set produced enough in-sample data; use more history")
        chosen = scored[0][1]
        search = {"trials": len(combos), "criterion": "in-sample Sharpe ratio", "chosen": chosen,
                  "top": [{"params": c, "in_sample_sharpe": round(s, 3)} for s, c in scored[:5]],
                  "worst": [{"params": c, "in_sample_sharpe": round(s, 3)} for s, c in scored[-3:]]}
        notes.append(f"Parameters were chosen from {len(combos)} combinations using ONLY the first {split} bars; the last {n - split} bars were never used to choose.")
    sig, warm = strat.signal(df, **chosen)
    cfg = BTConfig(capital, alloc, stop_loss, costs, warm)
    res = run(df, sig, cfg)
    bh = run(df, np.ones(n, dtype=int), cfg)
    free = run(df, sig, BTConfig(capital, alloc, stop_loss, NO_COSTS, warm))          # same strategy with zero costs/slippage
    eq_full, tr_full = _slice_result(res, warm)
    m = stats.metrics(eq_full, tr_full, rf)
    m_bh = stats.metrics(bh.equity.iloc[warm:], bh.trades, rf)
    m_free = stats.metrics(free.equity.iloc[warm:], free.trades, rf)
    out: dict[str, Any] = {"strategy": strat.name, "params": chosen, "bars": n, "warmup_bars": warm, "first_trade_allowed": str(df.index[warm].date()),
                           "last_bar": str(df.index[-1].date()), "capital": capital, "stop_loss": stop_loss, "oos_fraction": oos_fraction or None}
    out["metrics"] = m
    out["buy_hold"] = m_bh
    out["no_cost"] = {"total_return": m_free.get("total_return"), "sharpe": m_free.get("sharpe")}
    paid = res.paid
    out["costs"] = {"model": costs.describe(), "paid": {k: round(v, 2) for k, v in paid.items()}, "total_charges": round(sum(paid.values()), 2),
                    "slippage": round(res.slippage_paid, 2), "total_drag": round(sum(paid.values()) + res.slippage_paid, 2),
                    "drag_pct_of_capital": (sum(paid.values()) + res.slippage_paid) / capital, "exposure": res.exposure,
                    "return_lost_to_costs": (m_free.get("total_return") or 0) - (m.get("total_return") or 0)}
    out["series"] = {"equity": _series(res.equity.iloc[warm:], rebase=True), "buy_hold": _series(bh.equity.iloc[warm:], rebase=True),
                     "drawdown": _series(res.equity.iloc[warm:] / res.equity.iloc[warm:].cummax() - 1)}
    out["trades"] = tr_full[-200:]
    r = eq_full.pct_change().dropna().to_numpy()
    bs = stats.bootstrap(r, rf, reps, seed, trials=search["trials"] if search else 1)
    out["bootstrap"] = bs
    close_r = df["close"].pct_change().fillna(0).to_numpy()
    out["luck_test"] = stats.luck_test(sig[warm:], close_r[warm:], reps, seed)
    out["held_out"] = None
    if oos_fraction:
        i_is, i_oos = warm, split
        if i_oos - i_is < 60 or n - i_oos < 60:
            notes.append("In-sample or held-out stretch is under 60 bars after warm-up, so the split comparison is unreliable.")
        eq_is, tr_is = res.equity.iloc[i_is:i_oos], [t for t in res.trades if t["exit_date"] < str(df.index[i_oos].date())]
        eq_oos, tr_oos = _slice_result(res, i_oos)
        m_is, m_oos = stats.metrics(eq_is, tr_is, rf), stats.metrics(eq_oos, tr_oos, rf)
        bh_oos = stats.metrics(bh.equity.iloc[i_oos:], [], rf)
        boot_oos = stats.bootstrap(eq_oos.pct_change().dropna().to_numpy(), rf, reps, seed + 1, trials=search["trials"] if search else 1)
        out["held_out"] = {"split_date": str(df.index[i_oos].date()), "in_sample": m_is, "out_of_sample": m_oos, "buy_hold_oos": bh_oos, "bootstrap_oos": boot_oos,
                           "sharpe_drop": (m_is.get("sharpe") or 0) - (m_oos.get("sharpe") or 0)}
        out["series"]["split_date"] = str(df.index[i_oos].date())
    out["search"] = search
    judge = out["held_out"]["bootstrap_oos"] if out["held_out"] else bs
    p_for_flags = judge.get("p_adjusted") if judge.get("available") else None
    m_for_flags = out["held_out"]["out_of_sample"] if out["held_out"] else m
    out["reviewer_input"] = red_flag_inputs({**m_for_flags, "years": m.get("years"), "top5_trade_share": m.get("top5_trade_share"), "n_trades": m.get("n_trades")},
                                           costs_included=costs.slippage_bps > 0 or costs.stt_sell > 0, oos_fraction=oos_fraction or None,
                                           n_tuned=search["trials"] if search else 0, p=p_for_flags)
    out["verdict"] = verdict(out)
    out["notes"] = notes + ["Daily bars, long-only, one position. Signals fill at the next open. No margin, no shorting, no intraday.",
                            "Past performance of a rule is not evidence it will work again; this tool exists to show how often it does not."]
    return out


def verdict(o: dict) -> dict:
    """Plain-language summary of whether the result survives the tests."""
    m, bh = o["metrics"], o["buy_hold"]
    ho = o["held_out"]
    judge = ho["bootstrap_oos"] if ho else o["bootstrap"]
    beat = (m.get("total_return") or 0) > (bh.get("total_return") or 0)
    reasons = []
    if (m.get("n_trades") or 0) < 30:
        reasons.append(f"only {m.get('n_trades')} trade{'' if m.get('n_trades') == 1 else 's'}")
    if not ho:
        reasons.append("no held-out period")
    if judge.get("available") and judge["p_adjusted"] > 0.05:
        reasons.append(f"Sharpe not distinguishable from luck (p = {judge['p_adjusted']:.2f}{' after adjusting for the parameter search' if judge['trials'] > 1 else ''})")
    if ho and ho["sharpe_drop"] > 0.5:
        reasons.append(f"Sharpe fell by {ho['sharpe_drop']:.1f} on the held-out data")
    if not beat:
        reasons.append("did not beat simply holding the stock, after costs")
    label = "no demonstrated edge" if reasons else "survives these tests"
    return {"label": label, "reasons": reasons, "beats_buy_hold": beat,
            "caveat": "Surviving these tests is necessary, not sufficient: it does not guarantee the pattern continues."}
