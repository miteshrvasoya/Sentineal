"""OpenAI-compatible chat completions client: covers OpenAI, Groq, Together, OpenRouter, Ollama, LM Studio."""
from __future__ import annotations

import time

from app.llm.base import LLMError, LLMProvider, LLMRateLimited, LLMResult


class OpenAICompatProvider(LLMProvider):
    name = "openai_compat"

    def __init__(self, name: str, key: str = "", base_url: str | None = None, needs_key: bool = True, client=None) -> None:  # type: ignore[no-untyped-def]
        self.name, self.key, self.base_url, self.needs_key, self._client = name, key, base_url, needs_key, client

    def is_configured(self) -> bool:
        if self._client is not None:
            return True
        return bool(self.key) if self.needs_key else bool(self.base_url)

    def _c(self):  # type: ignore[no-untyped-def]
        if self._client is None:
            from openai import AsyncOpenAI
            self._client = AsyncOpenAI(api_key=self.key or "not-needed", base_url=self.base_url)
        return self._client

    async def complete(self, *, system, user, model, temperature=0.0, max_tokens=1024, json_mode=False) -> LLMResult:  # type: ignore[no-untyped-def]
        import openai
        kw: dict = {"model": model, "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
                    "temperature": temperature, "max_tokens": max_tokens}
        if json_mode:
            kw["response_format"] = {"type": "json_object"}
        t0 = time.monotonic()
        for _ in range(4):   # retry while peeling off parameters this model/server rejects
            try:
                resp = await self._c().chat.completions.create(**kw)
                break
            except openai.RateLimitError:
                raise LLMRateLimited(f"{self.name} rate limited") from None
            except openai.BadRequestError as e:
                m = str(e).lower()
                if "max_tokens" in m and "max_tokens" in kw:
                    kw["max_completion_tokens"] = kw.pop("max_tokens")
                elif "temperature" in m and "temperature" in kw:
                    kw.pop("temperature")
                elif "response_format" in m and "response_format" in kw:
                    kw.pop("response_format")
                else:
                    raise LLMError(f"{self.name} bad request: {type(e).__name__}") from None
            except openai.OpenAIError as e:
                raise LLMError(f"{self.name} error: {type(e).__name__}") from None
        else:
            raise LLMError(f"{self.name}: request kept being rejected")
        u = resp.usage
        return LLMResult(resp.choices[0].message.content or "", getattr(u, "prompt_tokens", 0) or 0,
                         getattr(u, "completion_tokens", 0) or 0, model, self.name, int((time.monotonic() - t0) * 1000))
