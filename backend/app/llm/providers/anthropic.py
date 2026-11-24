from __future__ import annotations

import time

from app.config import get_settings
from app.llm.base import LLMError, LLMProvider, LLMRateLimited, LLMResult


class AnthropicProvider(LLMProvider):
    name = "anthropic"

    def __init__(self, client=None, key: str | None = None) -> None:  # type: ignore[no-untyped-def]
        self.key = key if key is not None else get_settings().anthropic_api_key
        self._client = client

    def is_configured(self) -> bool:
        return bool(self.key) or self._client is not None

    def _c(self):  # type: ignore[no-untyped-def]
        if self._client is None:
            from anthropic import AsyncAnthropic
            self._client = AsyncAnthropic(api_key=self.key)
        return self._client

    async def complete(self, *, system, user, model, temperature=0.0, max_tokens=1024, json_mode=False) -> LLMResult:  # type: ignore[no-untyped-def]
        import anthropic
        kw = {"model": model, "max_tokens": max_tokens, "system": system,
              "messages": [{"role": "user", "content": user}], "temperature": temperature}
        t0 = time.monotonic()
        try:
            try:
                resp = await self._c().messages.create(**kw)
            except anthropic.BadRequestError as e:
                if "temperature" not in str(e).lower():
                    raise
                kw.pop("temperature")            # some models reject sampling parameters
                resp = await self._c().messages.create(**kw)
        except anthropic.RateLimitError as e:
            raise LLMRateLimited(f"anthropic rate limited: {type(e).__name__}") from None
        except anthropic.APIError as e:
            raise LLMError(f"anthropic error: {type(e).__name__}") from None   # message may echo request data
        text = "".join(b.text for b in resp.content if getattr(b, "type", "") == "text")
        return LLMResult(text, resp.usage.input_tokens, resp.usage.output_tokens, model, self.name,
                         int((time.monotonic() - t0) * 1000))
