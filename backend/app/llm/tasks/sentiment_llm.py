"""LLM sentiment second opinion, stored next to FinBERT/VADER (model name 'llm:<model>') and compared."""
from __future__ import annotations

import time
from typing import Literal

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.data.models import Article, ArticleScore, ArticleTicker
from app.features.sentiment import POS_T
from app.llm import guardrails as gr
from app.llm.base import BudgetExceeded, LLMUnavailable
from app.llm.context import article_block, article_pack
from app.llm.prompts import load_prompt
from app.llm.router import LLMRouter
from app.nlp.entities import AliasResolver

TASK = "sentiment_llm"
LLM_PREFIX = "llm:"


class SentimentItem(BaseModel):
    article_id: str
    score: float = Field(ge=-1, le=1)
    label: Literal["positive", "negative", "neutral"]


class SentimentBatch(BaseModel):
    items: list[SentimentItem]


def label_of(score: float) -> str:
    return "positive" if score > POS_T else "negative" if score < -POS_T else "neutral"


def make_post_check(ids: set[str]):  # type: ignore[no-untyped-def]
    def check(b: SentimentBatch) -> list[str]:
        got = [i.article_id for i in b.items]
        p = []
        if ids - set(got):
            p.append(f"missing article ids {sorted(ids - set(got))}")
        if set(got) - ids or len(got) != len(set(got)):
            p.append("unknown or duplicate article ids")
        return p
    return check


async def score_pending_llm(db: Session, router: LLMRouter, resolver: AliasResolver, symbol: str | None = None,
                            limit: int = 30) -> dict:
    out = {"scored": 0, "failed_batches": 0, "stopped": None, "model": None}
    done = select(ArticleScore.article_id).where(ArticleScore.model.like(f"{LLM_PREFIX}%"))
    q = select(Article).where(Article.id.not_in(done))
    if symbol:
        q = q.join(ArticleTicker, ArticleTicker.article_id == Article.id).where(ArticleTicker.symbol == symbol)
    arts = list(db.scalars(q.order_by(Article.published.desc()).limit(limit)))
    prompt, size = load_prompt(TASK), router.cfg.tasks[TASK].batch_size
    for i in range(0, len(arts), size):
        packs = {a.id: article_pack(a, []) for a in arts[i:i + size]}
        try:
            res = await router.json_task(TASK, prompt, {"untrusted_rules": gr.UNTRUSTED_RULES,
                                                        "articles": "\n\n".join(article_block(p) for p in packs.values())},
                                         SentimentBatch, make_post_check(set(packs)))
        except BudgetExceeded as e:
            out["stopped"] = f"budget: {e}"
            break
        except LLMUnavailable as e:
            out["stopped"], out["failed_batches"] = f"unavailable: {e}", out["failed_batches"] + 1
            break
        out["model"], now = f"{res.provider}/{res.model}", int(time.time())
        for it in res.value.items:
            if it.article_id in packs:
                pos, neg = max(it.score, 0.0), max(-it.score, 0.0)
                db.merge(ArticleScore(article_id=it.article_id, model=f"{LLM_PREFIX}{res.model}", pos=pos, neg=neg,
                                      neu=1 - pos - neg, score=it.score, scored_at=now))
                out["scored"] += 1
        db.commit()
    return out


def compare_with_reference(rows: list[tuple[str, float, float, str, str]]) -> dict:
    """rows: (article_id, reference_score, llm_score, title, ...) -> agreement stats and the disagreements."""
    n = len(rows)
    agree = [r for r in rows if label_of(r[1]) == label_of(r[2])]
    dis = sorted((r for r in rows if label_of(r[1]) != label_of(r[2])), key=lambda r: -abs(r[1] - r[2]))
    sign_agree = [r for r in rows if (r[1] > 0) == (r[2] > 0)]
    return {"n": n, "label_agreement": round(len(agree) / n, 3) if n else None,
            "sign_agreement": round(len(sign_agree) / n, 3) if n else None,
            "disagreements": [{"article_id": r[0], "reference": round(r[1], 3), "llm": round(r[2], 3), "title": r[3]}
                              for r in dis[:20]]}
