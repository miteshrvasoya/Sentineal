"""Find the best FREE OpenRouter model for this app, from the live catalogue, and optionally test candidates with real calls.

What this app needs from a model: obey a JSON schema (almost every AI feature returns structured JSON), stay faithful to the
numbers it is given, handle prompts of a few thousand tokens, and be reasonably quick. The ranking below scores the
catalogue's declared capabilities; the live test then checks what actually happens on your account, because declared
capabilities and real behaviour differ and free models rotate.
"""
from __future__ import annotations

import math
import re
import time
from typing import Any

import httpx

MODELS_URL = "https://openrouter.ai/api/v1/models"
ROUTER_MODEL = "openrouter/free"
PREFERRED_FAMILIES = ("nemotron", "gpt-oss", "qwen3", "gemma", "llama-3.3", "llama-4", "deepseek", "mistral")   # bonus order, newest-capable first
AVOID = ("coder", "image", "vision", "-vl", "embed", "guard", "tiny", "mini-")


def is_free(m: dict[str, Any]) -> bool:
    p = m.get("pricing") or {}
    zero = all(str(p.get(k, "1")) in ("0", "0.0", "0.00") for k in ("prompt", "completion"))
    return str(m.get("id", "")).endswith(":free") or zero


def _size_b(model_id: str) -> float | None:
    hits = [float(x) for x in re.findall(r"(\d+(?:\.\d+)?)b", model_id.lower())]
    return max(hits) if hits else None


def score(m: dict[str, Any]) -> tuple[float, list[str]]:
    """Higher is better. Returns the score and the reasons, so the choice is explainable."""
    why: list[str] = []
    sp = set(m.get("supported_parameters") or [])
    s = 0.0
    if "structured_outputs" in sp:
        s += 40
        why.append("supports structured outputs (JSON schema)")
    elif "response_format" in sp:
        s += 20
        why.append("supports JSON mode")
    else:
        why.append("no declared JSON support (we ask for JSON in the prompt and validate it)")
    if "tools" in sp:
        s += 12
        why.append("supports tool calling")
    if "reasoning" in sp or "include_reasoning" in sp:
        s += 6
        why.append("reasoning model")
    ctx = int(m.get("context_length") or 0)
    s += min(ctx, 262_144) / 262_144 * 14
    if ctx:
        why.append(f"{ctx // 1000}k context")
    size = _size_b(m["id"])
    if size:
        s += min(math.log10(size) / math.log10(600), 1) * 18        # bigger usually follows instructions and numbers better
        why.append(f"~{size:g}B parameters")
    mid = m["id"].lower()
    for i, fam in enumerate(PREFERRED_FAMILIES):
        if fam in mid:
            s += max(1, 8 - i)
            break
    if any(a in mid for a in AVOID):
        s -= 15
        why.append("specialised or small variant (penalised)")
    mod = (m.get("architecture") or {}).get("output_modalities") or ["text"]
    if "text" not in mod:
        s -= 100
    return s, why


def rank_free_models(models: list[dict[str, Any]], limit: int = 10) -> list[dict[str, Any]]:
    out = []
    for m in models:
        if not is_free(m) or m.get("id") == ROUTER_MODEL or int(m.get("context_length") or 0) < 16_000:
            continue
        sc, why = score(m)
        if sc < 0:
            continue
        out.append({"id": m["id"], "name": m.get("name", m["id"]), "score": round(sc, 1), "context": m.get("context_length"), "reasons": why,
                    "structured": "structured_outputs" in (m.get("supported_parameters") or [])})
    out.sort(key=lambda r: (-r["score"], r["id"]))
    return out[:limit]


async def fetch_models(key: str = "", timeout: float = 20.0) -> list[dict[str, Any]]:
    headers = {"Authorization": f"Bearer {key}"} if key else {}
    async with httpx.AsyncClient(timeout=timeout) as c:
        r = await c.get(MODELS_URL, headers=headers)
        r.raise_for_status()
        return list(r.json().get("data", []))


TEST_SYSTEM = "You classify short stock headlines for an educational tool. Never give investment advice."
TEST_HEADLINES = ["Infosys wins a large multi-year cloud contract", "Regulator opens probe into a mid-size bank over loan reporting", "Company announces AGM date"]


async def live_test(provider, model: str, runs: int = 2) -> dict[str, Any]:  # type: ignore[no-untyped-def]
    """Ask the model for a schema-conforming answer a few times; report how often it was valid JSON and how fast."""
    from pydantic import BaseModel, Field

    class Item(BaseModel):
        n: int
        label: str = Field(pattern="^(positive|negative|neutral)$")

    class Out(BaseModel):
        items: list[Item]

    ok, times, errors = 0, [], []
    user = "Label each headline.\n" + "\n".join(f"{i + 1}. {h}" for i, h in enumerate(TEST_HEADLINES))
    for _ in range(runs):
        t0 = time.monotonic()
        try:
            r = await provider.complete_json(system=TEST_SYSTEM, user=user, model=model, schema=Out, temperature=0.0, max_tokens=600)
            good = len(r.value.items) == len(TEST_HEADLINES) and r.value.items[0].label == "positive" and r.value.items[1].label == "negative"
            ok += int(good)
            times.append(time.monotonic() - t0)
        except Exception as e:  # noqa: BLE001
            errors.append(f"{type(e).__name__}: {str(e)[:80]}")
    return {"model": model, "valid_rate": ok / runs, "avg_seconds": round(sum(times) / len(times), 1) if times else None, "errors": errors[:2]}
