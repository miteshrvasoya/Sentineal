"""Glue that assembles fundamentals views and the scorecard from stored data (no network)."""
from __future__ import annotations

import json
import time
from typing import Any

import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.data.models import FundamentalsSnapshot
from app.data.prices import apply_adjustment, load_prices
from app.features import fundamentals as fd
from app.features import sentiment as sf
from app.features import structure as st
from app.features.pipeline import compute_features, to_frame
from app.models import scorecard as sc


def close_series(db: Session, symbol: str, adjusted: bool = True) -> pd.Series | None:
    """Daily close indexed by naive IST calendar date."""
    p = load_prices(db, symbol, "1d")
    if p.empty:
        return None
    c = (apply_adjustment(p) if adjusted else p)["close"]
    idx = pd.to_datetime(c.index, unit="s", utc=True).tz_convert("Asia/Kolkata").tz_localize(None).normalize()
    return pd.Series(c.to_numpy(), index=idx).groupby(level=0).last()


def fundamentals_view(db: Session, symbol: str, r: float | None = None, g1: float | None = None, g2: float | None = None,
                      years: int | None = None) -> dict[str, Any] | None:
    snap = db.get(FundamentalsSnapshot, symbol)
    if not snap:
        return None
    inp = fd.Inputs.from_dict(json.loads(snap.payload))
    notes: list[str] = []
    raw = load_prices(db, symbol, "1d")
    if not raw.empty:                                   # value on the latest stored close, not a stale snapshot price
        inp.price = float(raw["close"].iloc[-1])
        if inp.shares:
            inp.market_cap = inp.price * inp.shares
    if inp.prev is None:
        notes.append("Only one year of statements: growth and most Piotroski tests are unavailable.")
    rat = fd.ratios(inp)
    peers = []
    for s in db.scalars(select(FundamentalsSnapshot).where(FundamentalsSnapshot.sector == snap.sector, FundamentalsSnapshot.symbol != symbol)):
        peers.append(fd.ratios(fd.Inputs.from_dict(json.loads(s.payload))))
    pct = fd.sector_percentiles(rat, peers) if snap.sector else {}
    if not snap.sector or len(peers) < 3:
        notes.append(f"Sector percentiles need at least 3 other {snap.sector or 'same-sector'} companies loaded (have {len(peers)}).")
    d = fd.default_dcf_assumptions(inp)
    used = {"r": d["r"] if r is None else r, "g1": d["g1"] if g1 is None else g1, "g2": d["g2"] if g2 is None else g2,
            "years": d["years"] if years is None else years}
    dc = fd.dcf(inp.cur.fcf, inp.shares, inp.price, **used)
    return {
        "symbol": symbol, "sector": snap.sector, "currency": inp.currency, "price": inp.price, "fetched_at": snap.fetched_at,
        "stale_days": round((time.time() - snap.fetched_at) / 86400, 1), "notes": notes,
        "ratios": rat, "percentiles": pct, "piotroski": fd.piotroski(inp), "altman": fd.altman_z(inp),
        "graham": fd.graham_number(inp.eps, inp.bvps, inp.price), "dcf": dc, "dcf_defaults": d,
        "dcf_sensitivity": fd.dcf_sensitivity(inp.cur.fcf, inp.shares, inp.price, used["r"], used["g1"], used["g2"], used["years"]),
        "peers_used": len(peers),
    }


def sentiment_latest(db: Session, symbol: str, days: int = 30) -> dict | None:
    from app.api.routes_news import articles_frame, pick_model  # local import: avoid a module cycle
    model = pick_model(db)
    if model is None:
        return None
    rows = articles_frame(db, symbol, days, model)
    if len(rows) < 3:
        return None
    f = sf.daily_features(pd.DataFrame([{"published": a.published, "score": s.score} for a, s in rows]))
    last = f.iloc[-1]
    return {"recency_weighted": None if pd.isna(last["recency_weighted"]) else float(last["recency_weighted"]),
            "sent_mom": None if pd.isna(last["sent_mom"]) else float(last["sent_mom"]), "n_articles": len(rows), "model": model}


def scorecard_for(db: Session, symbol: str) -> dict[str, Any] | None:
    p = load_prices(db, symbol, "1d")
    if len(p) < 60:
        return None
    df = to_frame(apply_adjustment(p)).iloc[-600:]
    feats = compute_features(df)
    try:
        trend = st.analyze(df.iloc[-300:], k=5)["trend"]
    except Exception:  # noqa: BLE001  structure is a nice-to-have input
        trend = None
    close = df["close"]
    out = sc.build(feats.iloc[-1], float(close.iloc[-1]), structure_trend=trend, obv_series=feats["obv"],
                   up_day=bool(close.iloc[-1] > close.iloc[-2]) if len(close) > 1 else None,
                   sentiment=sentiment_latest(db, symbol), fundamentals=fundamentals_view(db, symbol))
    return {"symbol": symbol, "as_of": str(df.index[-1].date()), "bars": len(df), **out}
