"""LLM endpoints. Every response degrades to `available: false` instead of erroring when no LLM can serve it."""
from __future__ import annotations

import json
import time

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.routes import _known
from app.api.routes_news import label, pick_model
from app.config import get_settings
from app.data.db import get_session
from app.data.models import Article, ArticleEnrichment, ArticleScore, ArticleTicker
from app.deps import get_llm_router
from app.llm.eval import run_eval
from app.llm.router import LLMRouter
from app.llm.tasks.news_enrich import enrich_pending
from app.llm.tasks.sentiment_llm import LLM_PREFIX, compare_with_reference, score_pending_llm
from app.nlp.entities import get_resolver
from app.nlp.factory import get_scorer

router = APIRouter()
BADGE = "AI-generated, may be wrong, not investment advice"


def forward_start(db: Session) -> int | None:
    """When LLM-derived data collection began. LLM outputs for articles published BEFORE this are 'backfilled':
    the model may already know how those stories played out, so they are not valid for backtesting."""
    a = db.scalar(select(func.min(ArticleEnrichment.generated_at)))
    b = db.scalar(select(func.min(ArticleScore.scored_at)).where(ArticleScore.model.like(f"{LLM_PREFIX}%")))
    vals = [v for v in (a, b) if v is not None]
    return min(vals) if vals else None


@router.get("/llm/status")
def llm_status(db: Session = Depends(get_session), r: LLMRouter = Depends(get_llm_router)) -> dict:
    st, s = r.status(), get_settings()
    fs = forward_start(db)
    return {**st, "available": any(st["providers"].values()), "badge": BADGE, "budget": r.usage.summary()["today"],
            "forward_only": s.llm_enable_forward_only_features, "forward_start": fs}


@router.get("/llm/usage")
def llm_usage(days: int = Query(14, ge=1, le=90), r: LLMRouter = Depends(get_llm_router)) -> dict:
    return r.usage.summary(days)


@router.post("/llm/enrich/{symbol}")
async def enrich(symbol: str, limit: int = Query(24, ge=1, le=100), db: Session = Depends(get_session),
                 r: LLMRouter = Depends(get_llm_router)) -> dict:
    """Event type / materiality / summary and an LLM sentiment score for stored, not-yet-processed articles."""
    sym = _known(symbol)
    if not (r.available("news_enrich") or r.available("sentiment_llm")):
        return {"available": False, "reason": "No LLM provider configured. Add an API key to .env (see config/llm.yaml).", "badge": BADGE}
    res = get_resolver()
    return {"available": True, "badge": BADGE, "symbol": sym,
            "enrichment": await enrich_pending(db, r, res, sym, limit),
            "sentiment": await score_pending_llm(db, r, res, sym, limit)}


@router.get("/news/{symbol}/enriched")
def news_enriched(symbol: str, days: int = Query(14, ge=1, le=365), limit: int = Query(100, ge=1, le=300),
                  min_materiality: str = Query("low", pattern="^(low|medium|high)$"),
                  db: Session = Depends(get_session), r: LLMRouter = Depends(get_llm_router)) -> dict:
    sym = _known(symbol)
    ref_model = pick_model(db)
    rank = {"low": 0, "medium": 1, "high": 2}
    since = int(time.time()) - days * 86400
    q = (select(Article).join(ArticleTicker, ArticleTicker.article_id == Article.id)
         .where(ArticleTicker.symbol == sym, Article.published >= since).order_by(Article.published.desc()).limit(limit * 3))
    arts = list(db.scalars(q))
    ids = [a.id for a in arts]
    enr = {e.article_id: e for e in db.scalars(select(ArticleEnrichment).where(ArticleEnrichment.article_id.in_(ids)))}
    ref = {s.article_id: s.score for s in db.scalars(select(ArticleScore).where(ArticleScore.article_id.in_(ids), ArticleScore.model == ref_model))}
    llm = {s.article_id: (s.score, s.model) for s in db.scalars(select(ArticleScore).where(ArticleScore.article_id.in_(ids), ArticleScore.model.like(f"{LLM_PREFIX}%")))}
    fs = forward_start(db)
    items, pairs = [], []
    for a in arts:
        e = enr.get(a.id)
        if e and rank[e.materiality] < rank[min_materiality]:
            continue
        if min_materiality != "low" and not e:
            continue
        ls = llm.get(a.id)
        if a.id in ref and ls:
            pairs.append((a.id, ref[a.id], ls[0], a.title, ""))
        items.append({
            "id": a.id, "title": a.title, "url": a.url, "source": a.source, "published": a.published,
            "ref_score": ref.get(a.id), "ref_label": label(ref[a.id]) if a.id in ref else None,
            "llm_score": ls[0] if ls else None, "llm_label": label(ls[0]) if ls else None, "llm_model": ls[1] if ls else None,
            "event_type": e.event_type if e else None, "direction": e.direction if e else None,
            "materiality": e.materiality if e else None, "horizon": e.horizon if e else None,
            "is_new_information": bool(e.is_new_information) if e else None, "summary": e.summary if e else None,
            "flags": json.loads(e.flags) if e else [], "llm_generated_at": e.generated_at if e else None,
            # LLM output is only trustworthy for backtests if collected before/at the time (forward-only rule).
            "valid_for_backtest": bool(e and fs is not None and a.published >= fs),
        })
        if len(items) >= limit:
            break
    return {"symbol": sym, "reference_model": ref_model, "badge": BADGE, "llm_available": any(r.status()["providers"].values()),
            "forward_start": fs, "count": len(items), "articles": items, "agreement": compare_with_reference(pairs)}


@router.get("/llm/eval")
async def llm_eval(r: LLMRouter = Depends(get_llm_router)) -> dict:
    """Run the hand-labelled headline set against the configured LLM (uses tokens; subject to the daily budget)."""
    if not r.available("sentiment_llm"):
        raise HTTPException(503, "LLM unavailable: no provider configured")
    return await run_eval(r, get_scorer(), get_resolver())
