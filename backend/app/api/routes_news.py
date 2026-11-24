"""News, sentiment and market-sentiment endpoints."""
from __future__ import annotations

import math
import time

import pandas as pd
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.routes import _known, symbol_table
from app.data.db import get_session
from app.data.models import Article, ArticleScore, ArticleTicker
from app.data.news_ingest import NewsRouter, ingest_symbol
from app.data.prices import apply_adjustment, load_prices
from app.deps import get_news_router
from app.features import sentiment as sent
from app.nlp.entities import get_resolver, top_terms
from app.nlp.factory import get_scorer

router = APIRouter()
LABEL_T = sent.POS_T


def label(score: float) -> str:
    return "positive" if score > LABEL_T else "negative" if score < -LABEL_T else "neutral"


def clean(v: object) -> object:
    if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
        return None
    if isinstance(v, dict):
        return {k: clean(x) for k, x in v.items()}
    if isinstance(v, list):
        return [clean(x) for x in v]
    return v


def pick_model(db: Session) -> str | None:
    """One scoring model per series (scales differ). Prefer FinBERT, then whichever has most scores."""
    counts = {m: n for m, n in db.execute(select(ArticleScore.model, func.count()).group_by(ArticleScore.model)).all()
              if not m.startswith("llm:")}      # LLM scores are a second opinion, never the default series
    if not counts:
        return None
    return "finbert" if counts.get("finbert") else max(counts, key=counts.__getitem__)


def articles_frame(db: Session, symbol: str | None, days: int, model: str) -> list[tuple]:
    q = (select(Article, ArticleScore).join(ArticleScore, ArticleScore.article_id == Article.id)
         .where(ArticleScore.model == model, Article.published >= int(time.time()) - days * 86400))
    if symbol:
        q = q.join(ArticleTicker, ArticleTicker.article_id == Article.id).where(ArticleTicker.symbol == symbol)
    return db.execute(q.order_by(Article.published.desc())).all()


@router.get("/news/{symbol}")
def get_news(symbol: str, days: int = Query(14, ge=1, le=365), limit: int = Query(100, ge=1, le=500),
             min_abs_score: float = Query(0.0, ge=0, le=1), db: Session = Depends(get_session)) -> dict:
    sym = _known(symbol)
    model = pick_model(db)
    if model is None:
        return {"symbol": sym, "model": None, "count": 0, "articles": [],
                "note": "No articles stored yet. POST /news/{symbol}/refresh to fetch."}
    rows = articles_frame(db, sym, days, model)
    ids = [a.id for a, _ in rows]
    tick: dict[str, list[str]] = {}
    for aid, s in db.execute(select(ArticleTicker.article_id, ArticleTicker.symbol).where(ArticleTicker.article_id.in_(ids))):
        tick.setdefault(aid, []).append(s)
    arts = [{"id": a.id, "title": a.title, "url": a.url, "source": a.source, "provider": a.provider,
             "published": a.published, "summary": a.summary, "tickers": sorted(tick.get(a.id, [])),
             "score": round(s.score, 4), "label": label(s.score), "pos": round(s.pos, 3), "neg": round(s.neg, 3),
             "neu": round(s.neu, 3), "provider_score": a.provider_score}
            for a, s in rows if abs(s.score) >= min_abs_score][:limit]
    return {"symbol": sym, "model": model, "count": len(arts), "articles": arts}


@router.post("/news/{symbol}/refresh")
async def refresh_news(symbol: str, days: int = Query(7, ge=1, le=90), db: Session = Depends(get_session),
                       nr: NewsRouter = Depends(get_news_router)) -> dict:
    sym = _known(symbol)
    company = next((s.name for s in symbol_table() if s.symbol == sym), sym)
    return await ingest_symbol(db, nr, get_resolver(), get_scorer(), sym, company, days)


@router.get("/sentiment/market")
def market_sentiment(days: int = Query(30, ge=1, le=365), db: Session = Depends(get_session)) -> dict:
    model = pick_model(db)
    if model is None:
        return {"model": None, "latest": None, "series": [], "note": "No articles stored yet."}
    rows = articles_frame(db, None, days, model)
    df = pd.DataFrame([{"published": a.published, "score": s.score} for a, s in rows])
    idx = sent.market_index(df)
    series = [{"date": d.date().isoformat(), "value": round(float(v), 4)} for d, v in idx.items()]
    return clean({"model": model, "n_articles": len(df), "latest": series[-1]["value"] if series else None,
                  "series": series})


@router.get("/sentiment/{symbol}")
def get_sentiment(symbol: str, days: int = Query(90, ge=7, le=365), db: Session = Depends(get_session)) -> dict:
    sym = _known(symbol)
    model = pick_model(db)
    if model is None:
        raise HTTPException(404, "No articles stored yet. POST /news/{symbol}/refresh to fetch.")
    rows = articles_frame(db, sym, days, model)
    if not rows:
        raise HTTPException(404, f"No articles for {sym} in the last {days} days.")
    df = pd.DataFrame([{"published": a.published, "score": s.score, "title": a.title} for a, s in rows])
    feats = sent.daily_features(df)

    prices = load_prices(db, sym, "1d")
    close = None
    if not prices.empty:
        p = apply_adjustment(prices)["close"]
        close = pd.Series(p.to_numpy(), index=pd.to_datetime(p.index, unit="s", utc=True).tz_convert("Asia/Kolkata").tz_localize(None).normalize())
        feats["divergence"] = sent.divergence(feats["sent_mom"], close).reindex(feats.index).fillna(0).astype(int)
    lead_lag = sent.lead_lag(feats["mean_sent"], close) if close is not None else []

    daily = [{"date": d.date().isoformat(), **{k: (None if pd.isna(v) else (int(v) if k in ("n_articles", "volume_spike", "divergence") else round(float(v), 4)))
                                                 for k, v in r.items()}} for d, r in feats.iterrows()]
    mix = dict(db.execute(select(ArticleScore.model, func.count()).group_by(ArticleScore.model)).all())
    return clean({
        "symbol": sym, "days": days, "model": model, "models_in_db": mix, "n_articles": len(df),
        "latest": daily[-1] if daily else None, "daily": daily, "lead_lag": lead_lag,
        "spikes": [d for d in daily if d["volume_spike"]],
        "top_terms": top_terms(df["title"].tolist()),
        "notes": ["Articles published after the 15:30 IST close are counted on the next day.",
                  "Lead/lag needs >=30 overlapping days; p_bonferroni corrects for testing all lags.",
                  "Correlation is not causation, and sentiment is often a reaction to price rather than a cause."]
        + ([] if model == "finbert" else ["Scored with the VADER fallback, not FinBERT: less accurate on financial text."]),
    })
