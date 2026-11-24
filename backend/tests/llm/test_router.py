import json

import pytest
from pydantic import BaseModel

from app.data import db as dbmod
from app.data.models import LLMUsage
from app.llm.base import BudgetExceeded, LLMError, LLMRateLimited, LLMUnavailable
from app.llm.prompts import load_prompt
from tests.llm.fakes import Scripted, make_router, session_ctx


class Out(BaseModel):
    ok: bool = True
    n: int = 1


PROMPT = load_prompt("sentiment_llm")
VARS = {"untrusted_rules": "RULES", "articles": "article id: a1\n<x>"}


@pytest.fixture(autouse=True)
def mem_db():
    dbmod.init_engine("sqlite:///:memory:")


def usage_rows():
    with session_ctx() as db:
        return db.query(LLMUsage).all()


async def run(router, post_check=None):
    return await router.json_task("sentiment_llm", PROMPT, VARS, Out, post_check)


async def test_prompts_are_versioned_files_and_render():
    assert PROMPT.id == "sentiment_llm" and PROMPT.version == 1
    s, u = PROMPT.render(**VARS)
    assert "RULES" in s and "article id: a1" in u
    with pytest.raises(KeyError):
        PROMPT.render(articles="x")           # missing placeholder is an error, never silently blank
    with pytest.raises(FileNotFoundError):
        load_prompt("does_not_exist")


async def test_success_records_usage_and_caches():
    a = Scripted("a", queue=['{"ok": true, "n": 5}'])
    r = make_router({"a": a})
    first = await run(r)
    assert first.value.n == 5 and not first.cached
    second = await run(r)                                       # identical content -> served from cache, no provider call
    assert second.cached and len(a.calls) == 1
    rows = usage_rows()
    assert [x.cached for x in rows] == [0, 1] and rows[0].tokens_in > 0 and rows[0].cost_usd > 0 and rows[1].cost_usd == 0


async def test_cache_key_changes_with_model_and_content():
    a = Scripted("a", responder=lambda kw: '{"n": 1}')
    r = make_router({"a": a})
    await run(r)
    await r.json_task("sentiment_llm", PROMPT, {**VARS, "articles": "article id: a2"}, Out)
    assert len(a.calls) == 2                                    # different content -> not a cache hit


async def test_falls_back_when_first_provider_rate_limited_or_errors():
    a = Scripted("a", responder=lambda kw: (_ for _ in ()).throw(LLMRateLimited("429")))
    b = Scripted("b", queue=['{"n": 2}'])
    r = make_router({"a": a, "b": b}, chain=(("a", "m1"), ("b", "m2")))
    res = await run(r)
    assert res.provider == "b" and res.value.n == 2
    assert len(a.calls) == 2                                    # one tenacity retry on rate limit, then fall through
    assert any(u.ok == 0 and u.provider == "a" for u in usage_rows())


async def test_unconfigured_providers_are_skipped_and_none_means_unavailable():
    off = Scripted("a", configured=False)
    with pytest.raises(LLMUnavailable, match="no LLM provider is configured"):
        await run(make_router({"a": off}))
    on = Scripted("b", queue=['{"n": 3}'])
    assert (await run(make_router({"a": off, "b": on}, chain=(("a", "m"), ("b", "m"))))).provider == "b"


async def test_all_providers_failing_raises_with_reasons():
    a = Scripted("a", responder=lambda kw: (_ for _ in ()).throw(LLMError("boom")))
    with pytest.raises(LLMUnavailable, match="boom"):
        await run(make_router({"a": a}))


async def test_invalid_json_repair_recorded_and_second_failure_falls_back():
    a = Scripted("a", queue=["garbage", "more garbage"])
    b = Scripted("b", queue=['{"n": 9}'])
    r = make_router({"a": a, "b": b}, chain=(("a", "m1"), ("b", "m2")))
    res = await run(r)
    assert res.provider == "b" and len(a.calls) == 2           # a got its one repair attempt
    assert sum(1 for u in usage_rows() if u.provider == "a") == 3  # two token-bearing calls + one failure row


async def test_token_budget_is_a_hard_stop_and_does_not_fall_back():
    a, b = Scripted("a", responder=lambda kw: '{"n": 1}'), Scripted("b", responder=lambda kw: '{"n": 1}')
    r = make_router({"a": a, "b": b}, chain=(("a", "m1"), ("b", "m2")), token_budget=300)   # reserve = est_in + 500 > 300
    with pytest.raises(BudgetExceeded):
        await run(r)
    assert a.calls == [] and b.calls == []                      # nothing was sent anywhere


async def test_budget_exhausted_by_earlier_spend():
    a = Scripted("a", responder=lambda kw: '{"n": 1}')
    r = make_router({"a": a}, token_budget=5000)
    r.usage.record(task="x", provider="a", model="m1", tokens_in=4700, tokens_out=0)
    with pytest.raises(BudgetExceeded, match="token"):
        await run(r)
    assert a.calls == []


async def test_usd_budget_hard_stop():
    a = Scripted("a", responder=lambda kw: '{"n": 1}')
    r = make_router({"a": a}, chain=(("a", "unknown-model"),), usd_budget=0.001)   # unknown model uses the conservative default price
    with pytest.raises(BudgetExceeded, match="spend"):
        await run(r)
    assert a.calls == []


async def test_post_check_regenerates_once_and_caches_only_clean_results():
    a = Scripted("a", queue=['{"n": -1}', '{"n": 4}'])
    r = make_router({"a": a})
    res = await run(r, lambda v: [] if v.n > 0 else ["n must be positive"])
    assert res.value.n == 4 and res.repaired and not res.problems and "n must be positive" in a.calls[1]["user"]
    again = await run(r, lambda v: [])
    assert again.cached

    bad = Scripted("a", queue=['{"n": -1}', '{"n": -2}'])
    r2 = make_router({"a": bad})
    res2 = await r2.json_task("sentiment_llm", PROMPT, {**VARS, "articles": "article id: other"}, Out, lambda v: ["still bad"])
    assert res2.problems == ["still bad"] and len(bad.calls) == 2
    from app.data.models import LLMCache
    with session_ctx() as db:
        assert db.query(LLMCache).count() == 1                  # only the clean result from the first scenario was cached


async def test_default_provider_moves_to_front_and_status_shape():
    a, b = Scripted("a", queue=['{"n": 1}']), Scripted("b", queue=['{"n": 2}'])
    r = make_router({"a": a, "b": b}, chain=(("a", "m"), ("b", "m")), default_provider="b")
    assert (await run(r)).provider == "b"
    st = r.status()
    assert st["providers"] == {"a": True, "b": True} and st["tasks"]["news_enrich"]["chain"][0]["configured"] is True
    with pytest.raises(KeyError):
        await r.json_task("nope", PROMPT, VARS, Out)


def test_real_config_file_is_valid():
    from app.llm.router import load_config
    cfg = load_config()
    assert {"news_enrich", "sentiment_llm", "analyst", "chat_agent"} <= set(cfg.tasks)
    assert all(e.provider in {"anthropic", "gemini", "openai", "groq", "ollama"} for t in cfg.tasks.values() for e in t.chain)
    json.dumps(cfg.model_dump())
