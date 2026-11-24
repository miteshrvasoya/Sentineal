from __future__ import annotations

import time

from app.config import get_settings
from app.llm.base import LLMError, LLMProvider, LLMRateLimited, LLMResult


class GeminiProvider(LLMProvider):
    name = "gemini"

    def __init__(self, client=None, key: str | None = None) -> None:  # type: ignore[no-untyped-def]
        self.key = key if key is not None else get_settings().gemini_api_key
        self._client = client

    def is_configured(self) -> bool:
        return bool(self.key) or self._client is not None

    def _c(self):  # type: ignore[no-untyped-def]
        if self._client is None:
            from google import genai
            self._client = genai.Client(api_key=self.key)
        return self._client

    async def complete(self, *, system, user, model, temperature=0.0, max_tokens=1024, json_mode=False) -> LLMResult:  # type: ignore[no-untyped-def]
        from google.genai import errors, types
        cfg = types.GenerateContentConfig(system_instruction=system, temperature=temperature, max_output_tokens=max_tokens,
                                          response_mime_type="application/json" if json_mode else None)
        t0 = time.monotonic()
        try:
            resp = await self._c().aio.models.generate_content(model=model, contents=user, config=cfg)
        except errors.APIError as e:
            if getattr(e, "code", None) == 429:
                raise LLMRateLimited("gemini rate limited") from None
            raise LLMError(f"gemini error (HTTP {getattr(e, 'code', '?')})") from None
        u = resp.usage_metadata
        return LLMResult(resp.text or "", getattr(u, "prompt_token_count", 0) or 0, getattr(u, "candidates_token_count", 0) or 0,
                         model, self.name, int((time.monotonic() - t0) * 1000))
