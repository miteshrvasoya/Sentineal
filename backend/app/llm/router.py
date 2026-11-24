"""Task -> provider/model routing with fallback, caching, budget hard-stop and guardrail regeneration."""
from __future__ import annotations

import json
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Generic, TypeVar

import yaml
from pydantic import BaseModel
from tenacity import (
    AsyncRetrying,
    retry_if_exception_type,
    stop_after_attempt,
    wait_random_exponential,
)

from app.config import ROOT, Settings, get_settings
from app.llm.base import (
    BudgetExceeded,
    LLMError,
    LLMProvider,
    LLMRateLimited,
    LLMResult,
    LLMUnavailable,
    LLMValidationError,
)
from app.llm.cache import LLMResultCache, cache_key, content_hash
from app.llm.prompts import Prompt
from app.llm.usage import UsageTracker, estimate_tokens

log = logging.getLogger("quantlens.llm")
T = TypeVar("T", bound=BaseModel)
CONFIG_PATH = ROOT / "config" / "llm.yaml"


class ChainEntry(BaseModel):
    provider: str
    model: str


class TaskCfg(BaseModel):
    temperature: float = 0.0
    max_tokens: int = 1024
    batch_size: int = 8
    chain: list[ChainEntry]


class LLMConfig(BaseModel):
    providers: dict[str, dict[str, str]] = {}
    default_price: dict[str, float] = {"in": 3.0, "out": 15.0}
    pricing: dict[str, dict[str, float]] = {}
    tasks: dict[str, TaskCfg] = {}


def load_config(path: Path = CONFIG_PATH) -> LLMConfig:
    return LLMConfig.model_validate(yaml.safe_load(path.read_text()))


def build_providers(cfg: LLMConfig, s: Settings | None = None) -> dict[str, LLMProvider]:
    from app.llm.providers.anthropic import AnthropicProvider
    from app.llm.providers.gemini import GeminiProvider
    from app.llm.providers.openai import OpenAIProvider
    from app.llm.providers.openai_compat import OpenAICompatProvider

    s = s or get_settings()
    ollama = s.ollama_base_url.rstrip("/")
    if ollama and not ollama.endswith("/v1"):
        ollama += "/v1"
    return {
        "anthropic": AnthropicProvider(), "gemini": GeminiProvider(), "openai": OpenAIProvider(),
        "groq": OpenAICompatProvider("groq", s.groq_api_key, cfg.providers.get("groq", {}).get("base_url"), True),
        "ollama": OpenAICompatProvider("ollama", "", ollama or None, False),
    }


@dataclass
class TaskResult(Generic[T]):
    value: T
    provider: str
    model: str
    cached: bool = False
    repaired: bool = False
    problems: list[str] = field(default_factory=list)   # guardrail problems that survived regeneration


class LLMRouter:
    def __init__(self, cfg: LLMConfig, providers: dict[str, LLMProvider], usage: UsageTracker, cache: LLMResultCache,
                 default_provider: str = "", retry_base: float = 0.5) -> None:
        self.cfg, self.providers, self.usage, self.cache = cfg, providers, usage, cache
        self.default_provider, self.retry_base = default_provider, retry_base

    def chain(self, task: str) -> list[tuple[LLMProvider, str]]:
        if task not in self.cfg.tasks:
            raise KeyError(f"unknown LLM task {task!r}")
        entries = list(self.cfg.tasks[task].chain)
        if self.default_provider:
            entries.sort(key=lambda e: e.provider != self.default_provider)   # stable: default first
        return [(self.providers[e.provider], e.model) for e in entries if e.provider in self.providers
                and self.providers[e.provider].is_configured()]

    def available(self, task: str) -> bool:
        return bool(self.chain(task))

    def status(self) -> dict:
        return {
            "providers": {n: p.is_configured() for n, p in self.providers.items()},
            "tasks": {t: {"temperature": c.temperature, "max_tokens": c.max_tokens,
                          "chain": [{"provider": e.provider, "model": e.model,
                                     "configured": e.provider in self.providers and self.providers[e.provider].is_configured()}
                                    for e in c.chain]} for t, c in self.cfg.tasks.items()},
        }

    async def _call(self, provider: LLMProvider, task: str, model: str, schema: type[T], system: str, user: str,
                    tcfg: TaskCfg, temperature: float | None = None):  # type: ignore[no-untyped-def]
        self.usage.check(model, estimate_tokens(system + user), tcfg.max_tokens)       # raises BudgetExceeded
        async for attempt in AsyncRetrying(stop=stop_after_attempt(2), reraise=True, retry=retry_if_exception_type(LLMRateLimited),
                                           wait=wait_random_exponential(multiplier=self.retry_base, max=4)):
            with attempt:
                return await provider.complete_json(system=system, user=user, model=model, schema=schema,
                                                    temperature=tcfg.temperature if temperature is None else temperature,
                                                    max_tokens=tcfg.max_tokens)

    def _record_ok(self, task: str, provider: str, model: str, results: list[LLMResult]) -> None:
        for r in results:
            self.usage.record(task=task, provider=provider, model=model, tokens_in=r.tokens_in, tokens_out=r.tokens_out,
                              latency_ms=r.latency_ms)

    async def json_task(self, task: str, prompt: Prompt, variables: dict[str, str], schema: type[T],
                        post_check: Callable[[T], list[str]] | None = None) -> TaskResult[T]:
        tcfg = self.cfg.tasks[task]
        system, user = prompt.render(**variables)
        chash = content_hash(system, user)
        reasons: list[str] = []
        chain = self.chain(task)
        if not chain:
            raise LLMUnavailable("no LLM provider is configured for this task (add an API key to .env)")
        for provider, model in chain:
            key = cache_key(task, prompt.id, prompt.version, model, chash)
            hit = self.cache.get(key)
            if hit is not None:
                try:
                    val = schema.model_validate(json.loads(hit))
                    self.usage.record(task=task, provider=provider.name, model=model, cached=True)
                    return TaskResult(val, provider.name, model, cached=True)
                except Exception:  # noqa: BLE001  stale/incompatible cache entry -> recompute
                    pass
            try:
                jr = await self._call(provider, task, model, schema, system, user, tcfg)
            except BudgetExceeded:
                raise                                   # hard stop: never fall through to another provider
            except LLMValidationError as e:
                self._record_ok(task, provider.name, model, getattr(e, "results", []))
                self.usage.record(task=task, provider=provider.name, model=model, ok=False, error=str(e))
                reasons.append(f"{provider.name}: {e}")
                continue
            except LLMError as e:
                self.usage.record(task=task, provider=provider.name, model=model, ok=False, error=str(e))
                reasons.append(f"{provider.name}: {e}")
                continue
            self._record_ok(task, provider.name, model, jr.results)
            value, repaired = jr.value, jr.repaired
            problems = post_check(value) if post_check else []
            if problems:                                # guardrail failed: regenerate once with feedback
                feedback = ("\n\nYour previous answer broke these rules: " + "; ".join(problems[:6]) +
                            ". Produce the answer again and fix them.")
                try:
                    jr2 = await self._call(provider, task, model, schema, system, user + feedback, tcfg, temperature=0.0)
                    self._record_ok(task, provider.name, model, jr2.results)
                    value, repaired = jr2.value, True
                    problems = post_check(value)
                except BudgetExceeded:
                    raise
                except LLMError as e:
                    reasons.append(f"{provider.name} regenerate: {e}")
            if not problems:
                self.cache.put(key, value.model_dump_json(), model)
            return TaskResult(value, provider.name, model, repaired=repaired, problems=problems)
        raise LLMUnavailable("; ".join(reasons) or "all providers failed")


def build_router(db_factory: Callable, s: Settings | None = None, cfg: LLMConfig | None = None) -> LLMRouter:  # type: ignore[type-arg]
    s = s or get_settings()
    cfg = cfg or load_config()
    usage = UsageTracker(db_factory, s.llm_daily_token_budget, s.llm_daily_usd_budget, cfg.pricing, cfg.default_price)
    return LLMRouter(cfg, build_providers(cfg, s), usage, LLMResultCache(db_factory), s.llm_default_provider)


__all__ = ["LLMRouter", "TaskResult", "build_router", "load_config", "Any"]
