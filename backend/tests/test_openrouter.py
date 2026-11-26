"""OpenRouter integration: provider quirks, config chains, free-model ranking and cost."""
import pytest

from app.config import Settings
from app.llm import openrouter as orr
from app.llm.base import LLMError, LLMRateLimited
from app.llm.providers.openai_compat import OpenAICompatProvider
from app.llm.router import build_providers, build_router, load_config
from tests.llm.fakes import session_ctx

CATALOGUE = [
    {"id": "nvidia/nemotron-3-super-120b-a12b:free", "context_length": 262144, "pricing": {"prompt": "0", "completion": "0"},
     "supported_parameters": ["structured_outputs", "response_format", "tools", "reasoning"], "architecture": {"output_modalities": ["text"]}},
    {"id": "openai/gpt-oss-120b:free", "context_length": 131072, "pricing": {"prompt": "0", "completion": "0"},
     "supported_parameters": ["structured_outputs", "tools"], "architecture": {"output_modalities": ["text"]}},
    {"id": "qwen/qwen3-coder:free", "context_length": 262144, "pricing": {"prompt": "0", "completion": "0"}, "supported_parameters": ["tools"]},
    {"id": "liquid/lfm-3-1.7b:free", "context_length": 32768, "pricing": {"prompt": "0", "completion": "0"}, "supported_parameters": ["structured_outputs"]},
    {"id": "tiny/old-model:free", "context_length": 4096, "pricing": {"prompt": "0", "completion": "0"}, "supported_parameters": ["structured_outputs"]},
    {"id": "anthropic/claude-sonnet-5-5", "context_length": 200000, "pricing": {"prompt": "0.000003", "completion": "0.000015"}, "supported_parameters": ["structured_outputs", "tools"]},
    {"id": "some/free-by-price", "context_length": 64000, "pricing": {"prompt": "0", "completion": "0"}, "supported_parameters": ["response_format"]},
    {"id": "openrouter/free", "context_length": 200000, "pricing": {"prompt": "0", "completion": "0"}, "supported_parameters": ["tools"]},
    {"id": "x/image-gen:free", "context_length": 64000, "pricing": {"prompt": "0", "completion": "0"}, "architecture": {"output_modalities": ["image"]}},
]


def test_free_detection_and_ranking_prefers_structured_output_big_models():
    assert orr.is_free(CATALOGUE[0]) and orr.is_free(CATALOGUE[6]) and not orr.is_free(CATALOGUE[5])
    ranked = orr.rank_free_models(CATALOGUE)
    ids = [r["id"] for r in ranked]
    assert ids[0] == "nvidia/nemotron-3-super-120b-a12b:free" and ids[1] == "openai/gpt-oss-120b:free"
    assert "anthropic/claude-sonnet-5-5" not in ids and "openrouter/free" not in ids and "tiny/old-model:free" not in ids and "x/image-gen:free" not in ids
    assert ids.index("qwen/qwen3-coder:free") > ids.index("openai/gpt-oss-120b:free")            # coder variant is penalised for general JSON work
    assert ranked[0]["structured"] and any("structured" in w for w in ranked[0]["reasons"])


def test_default_config_appends_openrouter_free_models_to_every_task():
    cfg = load_config()
    assert cfg.openrouter_free_models[0].endswith(":free") and cfg.openrouter_free_models[-1] == "openrouter/free"
    for task, t in cfg.tasks.items():
        orm = [e.model for e in t.chain if e.provider == "openrouter"]
        assert orm == cfg.openrouter_free_models, task
        assert t.chain[0].provider != "openrouter"                                                # paid providers keep priority by default


def test_openrouter_model_setting_goes_first_and_default_provider_can_promote_it():
    s = Settings(openrouter_api_key="k", openrouter_model="google/gemma-4-31b-it:free", llm_default_provider="openrouter")
    r = build_router(session_ctx, s, load_config())
    chain = r.chain("analyst")
    assert chain[0][1] == "google/gemma-4-31b-it:free" and chain[0][0].name == "openrouter"
    assert [m for _, m in chain].count("google/gemma-4-31b-it:free") == 1                          # not duplicated


def test_only_an_openrouter_key_is_enough_to_enable_every_ai_task():
    s = Settings(openrouter_api_key="k", anthropic_api_key="", openai_api_key="", gemini_api_key="", groq_api_key="", ollama_base_url="")
    r = build_router(session_ctx, s, load_config())
    assert all(r.available(t) for t in ("news_enrich", "analyst", "chat_agent", "briefing", "nl_screener", "explain_move"))


def test_provider_is_configured_only_with_a_key_and_sends_attribution_headers():
    p = build_providers(load_config(), Settings(openrouter_api_key="sk-or-x"))["openrouter"]
    assert p.is_configured() and p.base_url == "https://openrouter.ai/api/v1" and p.headers["X-Title"] == "QuantLens"
    assert not build_providers(load_config(), Settings(openrouter_api_key=""))["openrouter"].is_configured()


def test_free_models_cost_nothing_so_the_budget_is_not_consumed():
    from app.llm.usage import UsageTracker
    u = UsageTracker(session_ctx, 10**6, 1.0, {}, {"in": 10.0, "out": 10.0})
    assert u.cost("openai/gpt-oss-120b:free", 10_000, 10_000) == 0 and u.cost("openrouter/free", 5, 5) == 0 and u.cost("paid/model", 1_000_000, 0) == 10.0


class FakeResp:
    def __init__(self, choices=None, extra=None):
        self.choices, self.model_extra, self.usage = choices, extra or {}, None


class FakeClient:
    def __init__(self, resp):
        self.resp = resp
        self.chat = type("C", (), {"completions": type("X", (), {"create": self.create})()})()

    async def create(self, **kw):
        return self.resp


async def test_error_inside_a_200_body_becomes_a_clean_error_or_rate_limit():
    with pytest.raises(LLMRateLimited):
        await OpenAICompatProvider("openrouter", "k", client=FakeClient(FakeResp(None, {"error": {"code": 429, "message": "slow down"}}))).complete(system="s", user="u", model="m:free")
    with pytest.raises(LLMError, match="no answer"):
        await OpenAICompatProvider("openrouter", "k", client=FakeClient(FakeResp([], {"error": {"code": 502}}))).complete(system="s", user="u", model="m:free")


async def test_live_test_scores_a_model_that_answers_correctly():
    import json

    class P:
        async def complete_json(self, **kw):
            from app.llm.base import JsonResult
            return JsonResult(kw["schema"].model_validate(json.loads('{"items":[{"n":1,"label":"positive"},{"n":2,"label":"negative"},{"n":3,"label":"neutral"}]}')), [])

    class Bad:
        async def complete_json(self, **kw):
            raise RuntimeError("model unavailable")
    ok = await orr.live_test(P(), "a:free", runs=2)
    bad = await orr.live_test(Bad(), "b:free", runs=2)
    assert ok["valid_rate"] == 1.0 and bad["valid_rate"] == 0.0 and bad["errors"]


def test_api_endpoint_falls_back_gracefully_when_openrouter_is_unreachable(client, monkeypatch):
    async def boom(key="", timeout=20.0):
        raise OSError("offline")
    monkeypatch.setattr(orr, "fetch_models", boom)
    r = client.get("/llm/openrouter/models").json()
    assert r["ok"] is False and r["defaults"][0].endswith(":free") and "Could not reach" in r["error"]
    monkeypatch.setattr(orr, "fetch_models", lambda key="", timeout=20.0: _cat())
    r2 = client.get("/llm/openrouter/models").json()
    assert r2["ok"] and r2["recommended"] == "nvidia/nemotron-3-super-120b-a12b:free"


async def _cat():
    return CATALOGUE
