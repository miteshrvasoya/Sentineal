"""Context packs: the JSON facts (values, timestamps, ids, URLs) that the pipeline hands to the LLM.
The LLM may only use what is in the pack; numbers in its output are validated against it."""
from __future__ import annotations

from datetime import UTC, datetime

from app.data.models import Article
from app.llm.guardrails import flag_injection, wrap_untrusted

MAX_TEXT = 700


def article_pack(a: Article, candidate_tickers: list[str]) -> dict:
    text = f"{a.title}. {a.summary}".strip()
    return {
        "article_id": a.id, "title": a.title, "summary": a.summary[:MAX_TEXT], "source": a.source, "url": a.url,
        "published_utc": datetime.fromtimestamp(a.published, UTC).strftime("%Y-%m-%d %H:%M"),
        "candidate_tickers": candidate_tickers, "injection_flags": flag_injection(text),
    }


def article_block(pack: dict) -> str:
    """One fenced block per article; ids are ours, everything else is untrusted data."""
    body = f"source: {pack['source']}\npublished: {pack['published_utc']} UTC\ntitle: {pack['title']}\ntext: {pack['summary']}"
    return f"article id: {pack['article_id']}\n" + wrap_untrusted(body, "article")


def article_text(pack: dict) -> str:
    return f"{pack['title']}. {pack['summary']}"
