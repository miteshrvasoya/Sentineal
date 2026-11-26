"""LLM endpoints. Every response degrades to `available: false` instead of erroring when no LLM can serve it."""
from __future__ import annotations

import json
import time
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.routes import _known
from app.api.routes_news import label, pick_model
from app.config import get_settings
from app.data.db import get_session
from app.data.models import Article, ArticleEnrichment, ArticleScore, ArticleTicker
from app.deps import get_llm_router
from app.llm.eval import run_eval
from app.llm.packs import build_symbol_pack
from app.llm.router import LLMRouter
from app.llm.tasks import analyst as ai
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


# ---------------- Phase 8A: AI analyst, model explainer, why-did-it-move, backtest reviewer ----------------

def _unavailable(task: str, r: LLMRouter, pack: dict) -> dict | None:
    if r.available(task):
        return None
    return {"available": False, "reason": "No LLM provider configured for this task. Add an API key to .env (see config/llm.yaml). "
            "The facts below are what the AI would have been given.", "badge": BADGE, "facts": pack["facts"], "missing": pack["missing"]}


async def _guard(coro) -> dict:  # type: ignore[no-untyped-def]
    from app.llm.base import BudgetExceeded, LLMUnavailable
    try:
        return await coro
    except BudgetExceeded as e:
        return {"available": True, "report": None, "error": f"Daily AI budget reached: {e}"}
    except LLMUnavailable as e:
        return {"available": True, "report": None, "error": f"No provider could answer: {e}"}


@router.post("/ai/analyst/{symbol}")
async def ai_analyst(symbol: str, horizon: int = Query(5), db: Session = Depends(get_session), r: LLMRouter = Depends(get_llm_router)) -> dict:
    sym = _known(symbol)
    pack = build_symbol_pack(db, sym, horizon)
    if not pack["facts"]:
        raise HTTPException(404, f"No stored data for {sym}. Open its chart or run make seed first.")
    if (u := _unavailable(ai.ANALYST, r, pack)) is not None:
        return u
    out = await _guard(ai.analyst_report(r, pack))
    return {"available": True, "badge": BADGE, "symbol": sym, "facts": pack["facts"], "missing": pack["missing"], **out}


class ExplainModelBody(BaseModel):
    model: str
    horizon: int = 5


@router.post("/ai/explain-model/{symbol}")
async def ai_explain_model(symbol: str, body: ExplainModelBody, db: Session = Depends(get_session),
                           r: LLMRouter = Depends(get_llm_router)) -> dict:
    from app.api.routes_models import _views_and_metrics
    sym = _known(symbol)
    views, metrics, _ = _views_and_metrics(db, sym, body.horizon)
    if body.model not in views:
        raise HTTPException(404, f"no stored run of {body.model} for {sym} at horizon {body.horizon}. Run it on the Models page first.")
    pack = ai.model_pack(sym, views[body.model], metrics.get(body.model), body.horizon)
    if (u := _unavailable(ai.EXPLAIN_MODEL, r, pack)) is not None:
        return u
    out = await _guard(ai.explain_model(r, pack, body.model))
    return {"available": True, "badge": BADGE, "symbol": sym, "model": body.model, "facts": pack["facts"], "missing": pack["missing"], **out}


class ExplainMoveBody(BaseModel):
    start: str | None = Field(None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    end: str | None = Field(None, pattern=r"^\d{4}-\d{2}-\d{2}$")


@router.post("/ai/explain-move/{symbol}")
async def ai_explain_move(symbol: str, body: ExplainMoveBody, db: Session = Depends(get_session), r: LLMRouter = Depends(get_llm_router)) -> dict:
    from app.data.analysis import close_series
    sym = _known(symbol)
    c = close_series(db, sym)
    if c is None or len(c) < 10:
        raise HTTPException(404, f"No stored prices for {sym}.")
    end = body.end or str(c.index[-1].date())
    start = body.start or str(c.index[-min(5, len(c))].date())
    try:
        pack = ai.move_pack(db, sym, start, end)
    except ValueError as e:
        raise HTTPException(422, str(e)) from e
    arts = ai.articles_for_move(db, sym, start, end)
    if (u := _unavailable(ai.EXPLAIN_MOVE, r, pack)) is not None:
        return {**u, "articles": [{"id": a["article_id"], "title": a["title"], "source": a["source"], "url": a["url"]} for a in arts],
                "start": start, "end": end}
    out = await _guard(ai.explain_move(r, pack, arts, start, end))
    return {"available": True, "badge": BADGE, "symbol": sym, "start": start, "end": end, "facts": pack["facts"], "missing": pack["missing"], **out}


class BacktestReviewBody(BaseModel):
    strategy: str = Field(max_length=80)
    metrics: dict[str, Any]


@router.post("/ai/backtest-review")
async def ai_backtest_review(body: BacktestReviewBody, r: LLMRouter = Depends(get_llm_router)) -> dict:
    """Deterministic red flags always; the LLM review is added when a provider is configured."""
    pack = ai.backtest_pack(body.strategy, body.metrics)
    if not r.available(ai.BACKTEST_REVIEW):
        return {"available": False, "badge": BADGE, "red_flags": pack["flags"], "facts": pack["facts"],
                "reason": "No LLM provider configured; showing the automatic red-flag checks only."}
    out = await _guard(ai.review_backtest(r, body.strategy, pack))
    return {"available": True, "badge": BADGE, "facts": pack["facts"], "red_flags": pack["flags"], **out}


# ---------------- Phase 10A: chat agent, natural-language screener, briefing, red flags, safety eval ----------------

class ChatBody(BaseModel):
    message: str = Field(max_length=600)
    history: list[dict[str, str]] = Field(default_factory=list, max_length=12)


@router.post("/ai/chat")
async def ai_chat(body: ChatBody, db: Session = Depends(get_session), r: LLMRouter = Depends(get_llm_router)) -> dict:
    from app.agent.agent import run_agent
    if not r.available("chat_agent"):
        return {"available": False, "badge": BADGE, "reason": "No LLM provider configured for the chat agent. Add an API key to .env (see config/llm.yaml). "
                "Everything else in QuantLens works without one."}
    try:
        out = await run_agent(r, db, body.message, body.history)
    except ValueError as e:
        raise HTTPException(422, str(e)) from e
    return {"available": True, "badge": BADGE, **out}


class NLScreenBody(BaseModel):
    request: str = Field(max_length=400)


@router.post("/ai/nl-screen")
async def ai_nl_screen(body: NLScreenBody, db: Session = Depends(get_session), r: LLMRouter = Depends(get_llm_router)) -> dict:
    from app.api.routes_fund import clean
    from app.llm.base import BudgetExceeded, LLMUnavailable
    from app.llm.tasks.assistant import NL_SCREEN, nl_screen
    if not r.available(NL_SCREEN):
        return {"available": False, "badge": BADGE, "reason": "No LLM provider configured. You can still build the screen by hand with the condition builder."}
    try:
        out = await nl_screen(r, db, body.request)
    except ValueError as e:
        raise HTTPException(422, str(e)) from e
    except BudgetExceeded as e:
        return {"available": True, "badge": BADGE, "screen": None, "error": f"Daily AI budget reached: {e}"}
    except LLMUnavailable as e:
        return {"available": True, "badge": BADGE, "screen": None, "error": f"No provider could answer: {e}"}
    return clean({"available": True, "badge": BADGE, **out})


@router.post("/ai/briefing")
async def ai_briefing(db: Session = Depends(get_session), r: LLMRouter = Depends(get_llm_router)) -> dict:
    from app.llm.tasks.assistant import BRIEFING, briefing_pack, make_briefing
    pack = briefing_pack(db)
    if not pack["facts"]:
        raise HTTPException(404, "No stored data to brief on. Run make seed first.")
    if (u := _unavailable(BRIEFING, r, pack)) is not None:
        return {**u, "asof": pack["asof"]}
    out = await _guard(make_briefing(r, pack))
    return {"available": True, "badge": BADGE, "asof": pack["asof"], "facts": pack["facts"], "missing": pack["missing"], **out}


@router.get("/ai/briefing/latest")
def ai_briefing_latest(request: Request) -> dict:
    """The briefing the scheduler produced last (if the daily_briefing job has run)."""
    last = request.app.state.scheduler.last_run("daily_briefing")
    if not last or last["status"] != "ok" or not last["result"] or not last["result"].get("report"):
        return {"available": False, "reason": "No scheduled briefing yet. Press 'Write today's briefing', or enable the scheduler."}
    return {"available": True, "badge": BADGE, "generated_at": last["finished"], **last["result"]}


@router.get("/redflags/{symbol}")
def redflags(symbol: str, db: Session = Depends(get_session)) -> dict:
    from app.agent.redflags import red_flags
    sym = _known(symbol)
    out = red_flags(db, sym)
    if not out["checked"]:
        raise HTTPException(404, f"No stored data for {sym}.")
    return out


@router.get("/redflags")
def redflags_watchlist(db: Session = Depends(get_session)) -> list[dict]:
    from app.agent.redflags import red_flags
    from app.portfolio import tracked_symbols
    rows = []
    for sym in tracked_symbols(db):
        r = red_flags(db, sym)
        rows.append({"symbol": sym, "count": r["count"], "high": sum(f["severity"] == "high" for f in r["flags"]), "medium": sum(f["severity"] == "medium" for f in r["flags"]),
                     "top": r["flags"][0]["message"] if r["flags"] else None})
    return sorted(rows, key=lambda x: (-x["high"], -x["medium"], x["symbol"]))


@router.get("/llm/eval/safety")
async def llm_eval_safety(db: Session = Depends(get_session), r: LLMRouter = Depends(get_llm_router)) -> dict:
    """Run the prompt-injection corpus and the agent question set against the configured LLM (uses tokens)."""
    from app.llm.eval_agent import eval_agent, eval_injections
    if not r.available("chat_agent"):
        raise HTTPException(503, "LLM unavailable: no provider configured")
    return {"injection": await eval_injections(r, db), "agent": await eval_agent(r, db)}


@router.get("/llm/openrouter/models")
async def openrouter_models() -> dict:
    """The free OpenRouter models available now, ranked for this app (needs internet; the key is optional for listing)."""
    from app.llm import openrouter as orr
    cfg = get_settings()
    try:
        ranked = orr.rank_free_models(await orr.fetch_models(cfg.openrouter_api_key), 8)
    except Exception as e:  # noqa: BLE001
        from app.llm.router import load_config
        return {"ok": False, "error": f"Could not reach OpenRouter ({type(e).__name__}). Showing the built-in order instead.", "ranked": [],
                "defaults": load_config().openrouter_free_models, "current": cfg.openrouter_model or None, "key_set": bool(cfg.openrouter_api_key)}
    return {"ok": True, "ranked": ranked, "current": cfg.openrouter_model or None, "key_set": bool(cfg.openrouter_api_key),
            "recommended": ranked[0]["id"] if ranked else None,
            "note": "Ranked by declared capabilities. Run `make openrouter-check` to test the top models with real calls on your account."}
