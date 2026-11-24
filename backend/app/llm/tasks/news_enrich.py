"""News understanding: one structured call per batch of articles -> event type, materiality, summary, tickers."""
from __future__ import annotations

import json
import time
from typing import Literal

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.data.models import Article, ArticleEnrichment, ArticleTicker
from app.llm import guardrails as gr
from app.llm.base import BudgetExceeded, LLMUnavailable
from app.llm.context import article_block, article_pack, article_text
from app.llm.prompts import load_prompt
from app.llm.router import LLMRouter
from app.nlp.entities import AliasResolver

TASK = "news_enrich"
EventType = Literal["earnings", "guidance", "mna", "regulatory", "management_change", "order_win", "litigation",
                    "macro", "sector", "rumor", "other"]


class EnrichmentItem(BaseModel):
    article_id: str
    tickers: list[str] = []
    event_type: EventType
    direction: Literal["positive", "negative", "neutral", "mixed"]
    materiality: Literal["low", "medium", "high"]
    horizon: Literal["intraday", "weeks", "structural"]
    is_new_information: bool
    summary: str = Field(max_length=400)


class EnrichmentBatch(BaseModel):
    items: list[EnrichmentItem]


def make_post_check(packs: dict[str, dict]):  # type: ignore[no-untyped-def]
    def check(batch: EnrichmentBatch) -> list[str]:
        problems: list[str] = []
        got = [i.article_id for i in batch.items]
        missing, extra = set(packs) - set(got), set(got) - set(packs)
        if missing:
            problems.append(f"missing article ids {sorted(missing)}")
        if extra or len(got) != len(set(got)):
            problems.append(f"unknown or duplicate article ids {sorted(extra)}")
        for i in batch.items:
            if i.article_id not in packs:
                continue
            if adv := gr.contains_advice(i.summary):
                problems.append(f"{i.article_id}: summary contains trading advice {adv}")
            if bad := gr.unsupported_numbers(i.summary, article_text(packs[i.article_id]), allow_small_ints=True):
                problems.append(f"{i.article_id}: summary has numbers not in the article {bad}")
        return problems
    return check


def _pending(db: Session, symbol: str | None, limit: int) -> list[Article]:
    done = select(ArticleEnrichment.article_id)
    q = select(Article).where(Article.id.not_in(done))
    if symbol:
        q = q.join(ArticleTicker, ArticleTicker.article_id == Article.id).where(ArticleTicker.symbol == symbol)
    return list(db.scalars(q.order_by(Article.published.desc()).limit(limit)))


async def enrich_pending(db: Session, router: LLMRouter, resolver: AliasResolver, symbol: str | None = None,
                         limit: int = 24) -> dict:
    out = {"processed": 0, "flagged": 0, "summaries_removed": 0, "failed_batches": 0, "stopped": None, "model": None}
    arts = _pending(db, symbol, limit)
    if not arts:
        return out
    universe = resolver.known()
    prompt = load_prompt(TASK)
    size = router.cfg.tasks[TASK].batch_size
    for i in range(0, len(arts), size):
        chunk = arts[i:i + size]
        packs = {}
        for a in chunk:
            tick = sorted(db.scalars(select(ArticleTicker.symbol).where(ArticleTicker.article_id == a.id)))
            packs[a.id] = article_pack(a, tick)
        try:
            res = await router.json_task(TASK, prompt, {
                "universe": ", ".join(sorted(universe)), "untrusted_rules": gr.UNTRUSTED_RULES,
                "articles": "\n\n".join(article_block(p) for p in packs.values())}, EnrichmentBatch, make_post_check(packs))
        except BudgetExceeded as e:
            out["stopped"] = f"budget: {e}"
            break
        except LLMUnavailable as e:
            out["stopped"] = f"unavailable: {e}"
            out["failed_batches"] += 1
            break
        out["model"] = f"{res.provider}/{res.model}"
        now = int(time.time())
        for item in res.value.items:
            pack = packs.get(item.article_id)
            if pack is None:
                continue
            flags = []
            if pack["injection_flags"]:
                flags.append("injection_suspected")
            summary = item.summary.strip()
            if gr.contains_advice(summary) or gr.unsupported_numbers(summary, article_text(pack), allow_small_ints=True):
                summary = ""
                flags.append("summary_removed")
                out["summaries_removed"] += 1
            if flags:
                out["flagged"] += 1
            db.merge(ArticleEnrichment(
                article_id=item.article_id, prompt_id=prompt.id, prompt_version=prompt.version, provider=res.provider,
                model=res.model, generated_at=now, tickers=json.dumps(sorted({t.upper() for t in item.tickers} & universe)),
                event_type=item.event_type, direction=item.direction, materiality=item.materiality, horizon=item.horizon,
                is_new_information=int(item.is_new_information), summary=summary, flags=json.dumps(flags)))
            out["processed"] += 1
        db.commit()
    return out
