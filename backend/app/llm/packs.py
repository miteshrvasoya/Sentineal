"""Context packs: the facts the AI layer may talk about.

A pack is a flat registry `fact_id -> value` (e.g. `price.ret_21d = -0.034`). Every number the LLM may quote comes from
here, and every claim it makes must cite fact ids from here. Python computes; the LLM only narrates and interprets.
"""
from __future__ import annotations

import math
from typing import Any

import numpy as np
import pandas as pd
from sqlalchemy.orm import Session

SKIP_KEYS = {"rules", "why", "series", "notes", "disclaimer", "timeline", "points", "views", "dates", "symbol"}
MAX_DEPTH = 3


def _round(v: float) -> float:
    return round(float(v), 4)


def flatten(prefix: str, obj: Any, out: dict[str, Any], depth: int = 0) -> None:
    """Scalars only (numbers, booleans, short strings); lists, long text and bulky series are left out."""
    if depth > MAX_DEPTH:
        return
    if isinstance(obj, dict):
        for k, v in obj.items():
            if str(k) in SKIP_KEYS:
                continue
            flatten(f"{prefix}.{k}", v, out, depth + 1)
    elif isinstance(obj, bool):
        out[prefix] = obj
    elif isinstance(obj, int | float | np.integer | np.floating):
        if math.isfinite(float(obj)):
            out[prefix] = _round(obj) if isinstance(obj, float | np.floating) else int(obj)
    elif isinstance(obj, str) and 0 < len(obj) <= 60:
        out[prefix] = obj


def price_facts(close: pd.Series) -> dict[str, Any]:
    c = close.dropna()
    out: dict[str, Any] = {"last_close": _round(c.iloc[-1]), "as_of": str(c.index[-1].date()), "bars": len(c)}
    for n in (1, 5, 21, 63, 126, 252):
        if len(c) > n:
            out[f"ret_{n}d"] = _round(c.iloc[-1] / c.iloc[-1 - n] - 1)
    w = c.iloc[-252:]
    out["high_52w"], out["low_52w"] = _round(w.max()), _round(w.min())
    out["pct_below_52w_high"] = _round(c.iloc[-1] / w.max() - 1)
    lr = np.log(c).diff().dropna()
    if len(lr) >= 21:
        out["vol_21d_annual"] = _round(lr.iloc[-21:].std() * math.sqrt(252))
    if len(lr) >= 63:
        out["vol_63d_annual"] = _round(lr.iloc[-63:].std() * math.sqrt(252))
    return out


def build_symbol_pack(db: Session, symbol: str, horizon: int = 5) -> dict[str, Any]:
    """Facts about one stock from the stored data. Sections that cannot be built are listed in `missing`, never invented."""
    from app.data.analysis import close_series, fundamentals_view, scorecard_for, sentiment_latest
    from app.features import risk as rk

    facts: dict[str, Any] = {}
    missing: list[str] = []

    def section(name: str, fn) -> None:  # type: ignore[no-untyped-def]
        try:
            data = fn()
        except Exception:  # noqa: BLE001  one broken section must not take the report down
            data = None
        if not data:
            missing.append(name)
            return
        flat: dict[str, Any] = {}
        flatten(name, data, flat)
        if flat:
            facts.update(flat)
        else:
            missing.append(name)

    c = close_series(db, symbol)
    section("price", lambda: price_facts(c) if c is not None and len(c) > 30 else None)
    section("risk", lambda: {k: v for k, v in rk.summary(c, None, 0.07, 63).items() if k not in ("first", "last", "rf")}
            if c is not None and len(c) >= 60 else None)
    def scorecard() -> dict | None:
        s = scorecard_for(db, symbol)
        if not s:
            return None
        return {"composite": s["composite"], "label": s["label"],
                "subscores": {k: {"score": v.get("score"), "label": v.get("label"), "available": v.get("available")}
                              for k, v in s["subscores"].items()}}

    def fundamentals() -> dict | None:
        f = fundamentals_view(db, symbol)
        if not f:
            return None
        return {"ratios": f.get("ratios"), "scores": f.get("scores"), "stale_days": f.get("stale_days"), "sector": f.get("sector")}

    section("scorecard", scorecard)
    section("fundamentals", fundamentals)
    section("sentiment", lambda: sentiment_latest(db, symbol))
    section("models", lambda: _model_facts(db, symbol, horizon))
    return {"symbol": symbol, "horizon": horizon, "facts": facts, "missing": missing}


def _model_facts(db: Session, symbol: str, horizon: int) -> dict[str, Any] | None:
    from app.api.routes_models import _views_and_metrics
    from app.models import consensus as cons
    from app.models import registry as reg

    views, metrics, _runs = _views_and_metrics(db, symbol, horizon)
    if not views:
        return None
    c = cons.build(views, metrics, reg.BASELINES)
    out: dict[str, Any] = {"horizon_days": horizon, "headline": c.get("headline") if isinstance(c.get("headline"), str) else None}
    for k in ("votes", "agreement", "conviction", "n_edge"):
        if k in c:
            out[k] = c[k]
    for r in (c.get("models") or [])[:8]:
        out[f"model_{r['name']}"] = {"p_up": r.get("p_up"), "p_down": r.get("p_down"), "verdict": r.get("verdict")}
    return out


def pack_numbers(pack: dict[str, Any]) -> list[float]:
    return [float(v) for v in pack["facts"].values() if isinstance(v, int | float) and not isinstance(v, bool)]


def pack_block(pack: dict[str, Any]) -> str:
    """The pack as text for the prompt: one `id = value` line per fact."""
    lines = [f"{k} = {v}" for k, v in sorted(pack["facts"].items())]
    if pack.get("missing"):
        lines.append("sections with NO data: " + ", ".join(pack["missing"]))
    return "\n".join(lines)
