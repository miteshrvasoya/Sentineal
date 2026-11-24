"""Scripted LLM providers for tests. No test in this repo calls a live LLM."""
from __future__ import annotations

import json
import re

from app.data import db as dbmod
from app.llm.base import LLMProvider, LLMResult
from app.llm.cache import LLMResultCache
from app.llm.router import LLMConfig, LLMRouter, TaskCfg
from app.llm.usage import UsageTracker


def session_ctx():
    return dbmod._SessionLocal()


def ids_in(user: str) -> list[str]:
    return re.findall(r"article id: (\w+)", user)


class Scripted(LLMProvider):
    """Replays queued responses (str or Exception), else calls `responder(kwargs) -> str`."""

    def __init__(self, name="p", responder=None, queue=None, configured=True):
        self.name, self.responder, self.queue, self.configured, self.calls = name, responder, list(queue or []), configured, []

    def is_configured(self):
        return self.configured

    async def complete(self, *, system, user, model, temperature=0.0, max_tokens=1024, json_mode=False):
        self.calls.append({"system": system, "user": user, "model": model, "temperature": temperature,
                           "max_tokens": max_tokens, "json_mode": json_mode})
        item = self.queue.pop(0) if self.queue else self.responder(self.calls[-1])
        if isinstance(item, Exception):
            raise item
        return LLMResult(item, len(system + user) // 4, len(item) // 4, model, self.name, 5)


def sent_items(user, score=0.6):
    return json.dumps({"items": [{"article_id": i, "score": score, "label": "positive" if score > .15 else "negative" if score < -.15 else "neutral"}
                                 for i in ids_in(user)]})


def enrich_items(user, **over):
    base = {"tickers": ["RELIANCE"], "event_type": "earnings", "direction": "positive", "materiality": "medium",
            "horizon": "weeks", "is_new_information": True, "summary": "Company reported quarterly results."}
    return json.dumps({"items": [{"article_id": i, **{**base, **over}} for i in ids_in(user)]})


def smart(kw):
    """A well-behaved model for both tasks."""
    return sent_items(kw["user"]) if "financial sentiment" in kw["system"] else enrich_items(kw["user"])


def make_router(providers: dict, chain=(("a", "m1"),), token_budget=10**6, usd_budget=100.0, default_provider="", batch=8):
    ch = [{"provider": p, "model": m} for p, m in chain]
    cfg = LLMConfig(tasks={t: TaskCfg(temperature=0.0, max_tokens=500, batch_size=batch, chain=ch) for t in ("news_enrich", "sentiment_llm")},
                    pricing={"m1": {"in": 1.0, "out": 2.0}}, default_price={"in": 10.0, "out": 10.0})
    usage = UsageTracker(session_ctx, token_budget, usd_budget, cfg.pricing, cfg.default_price)
    return LLMRouter(cfg, providers, usage, LLMResultCache(session_ctx), default_provider, retry_base=0.0)
