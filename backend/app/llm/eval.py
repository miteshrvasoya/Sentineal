"""Evaluate an LLM provider + prompt version on a small hand-labelled headline set (data/llm_eval/headlines.jsonl).

Reports: sentiment accuracy vs the hand labels (and the same for FinBERT/VADER as a baseline), agreement between
the LLM and the local scorer, event-type accuracy, JSON validity rate, repair rate, and the hallucinated-number
rate in summaries (raw model output, before any regeneration). Run it again after changing a prompt or model to
catch regressions."""
from __future__ import annotations

import json
from pathlib import Path

from app.config import ROOT
from app.llm import guardrails as gr
from app.llm.base import BudgetExceeded, LLMError
from app.llm.context import article_block
from app.llm.prompts import load_prompt
from app.llm.router import LLMRouter
from app.llm.tasks.news_enrich import TASK as ENRICH
from app.llm.tasks.news_enrich import EnrichmentBatch
from app.llm.tasks.sentiment_llm import TASK as SENT
from app.llm.tasks.sentiment_llm import SentimentBatch, label_of
from app.nlp.entities import AliasResolver
from app.nlp.scoring import Scorer

EVAL_FILE = ROOT / "data" / "llm_eval" / "headlines.jsonl"


def load_items(path: Path = EVAL_FILE) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def _pack(i: int, headline: str) -> dict:
    return {"article_id": f"e{i}", "title": headline, "summary": "", "source": "eval", "published_utc": "2026-01-01 00:00"}


async def run_eval(router: LLMRouter, scorer: Scorer, resolver: AliasResolver, items: list[dict] | None = None) -> dict:
    items = items or load_items()
    packs = [_pack(i, it["headline"]) for i, it in enumerate(items)]
    ref = scorer.score([it["headline"] for it in items])
    out: dict = {"n": len(items), "scorer": scorer.name, "baseline_accuracy": round(
        sum(label_of(r.score) == it["label"] for r, it in zip(ref, items, strict=True)) / len(items), 3)}
    sent_p, enr_p = load_prompt(SENT), load_prompt(ENRICH)
    out["prompt_versions"] = {SENT: sent_p.version, ENRICH: enr_p.version}
    batches = ok = repaired = 0
    llm_scores: dict[str, float] = {}
    events: dict[str, str] = {}
    summaries: list[tuple[str, str]] = []
    model = None
    size = router.cfg.tasks[SENT].batch_size
    try:
        for i in range(0, len(packs), size):
            chunk = packs[i:i + size]
            batches += 1
            try:
                r = await router.json_task(SENT, sent_p, {"untrusted_rules": gr.UNTRUSTED_RULES,
                                                          "articles": "\n\n".join(article_block(p) for p in chunk)}, SentimentBatch)
            except BudgetExceeded:
                raise
            except LLMError:
                continue
            ok, repaired, model = ok + 1, repaired + int(r.repaired), f"{r.provider}/{r.model}"
            llm_scores.update({x.article_id: x.score for x in r.value.items})
        esize = router.cfg.tasks[ENRICH].batch_size
        for i in range(0, len(packs), esize):
            chunk = packs[i:i + esize]
            batches += 1
            try:
                r = await router.json_task(ENRICH, enr_p, {"universe": ", ".join(sorted(resolver.known())), "untrusted_rules": gr.UNTRUSTED_RULES,
                                                           "articles": "\n\n".join(article_block(p) for p in chunk)}, EnrichmentBatch)
            except BudgetExceeded:
                raise
            except LLMError:
                continue
            ok, repaired = ok + 1, repaired + int(r.repaired)
            for x in r.value.items:
                events[x.article_id] = x.event_type
                summaries.append((x.summary, next((p["title"] for p in chunk if p["article_id"] == x.article_id), "")))
    except BudgetExceeded as e:
        out["stopped"] = f"budget: {e}"
    out["model"] = model
    out["json_validity_rate"] = round(ok / batches, 3) if batches else None
    out["repair_rate"] = round(repaired / ok, 3) if ok else None
    scored = [(i, it) for i, it in enumerate(items) if f"e{i}" in llm_scores]
    out["sentiment_scored"] = len(scored)
    if scored:
        out["llm_accuracy"] = round(sum(label_of(llm_scores[f"e{i}"]) == it["label"] for i, it in scored) / len(scored), 3)
        out["agreement_with_scorer"] = round(sum(label_of(llm_scores[f"e{i}"]) == label_of(ref[i].score) for i, _ in scored) / len(scored), 3)
    ev = [(i, it) for i, it in enumerate(items) if f"e{i}" in events and it.get("event_type")]
    out["event_type_accuracy"] = round(sum(events[f"e{i}"] == it["event_type"] for i, it in ev) / len(ev), 3) if ev else None
    bad = sum(1 for s, title in summaries if s and gr.unsupported_numbers(s, title, allow_small_ints=True))
    out["hallucinated_number_rate"] = round(bad / len(summaries), 3) if summaries else None
    out["advice_in_summary_rate"] = round(sum(1 for s, _ in summaries if gr.contains_advice(s)) / len(summaries), 3) if summaries else None
    return out
