"""Provider-agnostic LLM interface.

The LLM interprets and summarises text. It never computes prices, indicators or model outputs and never gives
buy/sell advice. All numbers come from the Python pipeline and reach the LLM as grounded context.
"""
from __future__ import annotations

import abc
import json
import re
import time
from dataclasses import dataclass, field
from typing import Any, TypeVar

from pydantic import BaseModel, ValidationError

T = TypeVar("T", bound=BaseModel)


class LLMError(Exception):
    """Generic provider failure (network, auth, bad request). The router tries the next provider."""


class LLMRateLimited(LLMError):
    pass


class LLMUnavailable(LLMError):
    """No configured provider could serve the request."""


class BudgetExceeded(LLMError):
    """Daily token or USD budget reached. A hard stop: the router does NOT fall back to another provider."""


class LLMValidationError(LLMError):
    """Output was not valid JSON for the schema even after one repair retry."""


@dataclass
class LLMResult:
    text: str
    tokens_in: int
    tokens_out: int
    model: str
    provider: str
    latency_ms: int = 0


@dataclass
class JsonResult:
    value: BaseModel
    results: list[LLMResult] = field(default_factory=list)   # one per call (a repair adds a second)

    @property
    def repaired(self) -> bool:
        return len(self.results) > 1


def extract_json(text: str) -> Any:
    """Parse the first JSON object/array in `text`, tolerating markdown fences and chatter around it."""
    t = text.strip()
    t = re.sub(r"^```(?:json)?\s*|\s*```$", "", t, flags=re.I)
    try:
        return json.loads(t)
    except ValueError:
        pass
    for open_c, close_c in (("{", "}"), ("[", "]")):
        a, b = t.find(open_c), t.rfind(close_c)
        if a != -1 and b > a:
            try:
                return json.loads(t[a:b + 1])
            except ValueError:
                continue
    raise ValueError("no JSON found in model output")


class LLMProvider(abc.ABC):
    name = "base"

    @abc.abstractmethod
    def is_configured(self) -> bool: ...

    @abc.abstractmethod
    async def complete(self, *, system: str, user: str, model: str, temperature: float = 0.0,
                       max_tokens: int = 1024, json_mode: bool = False) -> LLMResult:
        """One non-streaming completion. Raise LLMRateLimited / LLMError on failure."""

    async def complete_json(self, *, system: str, user: str, model: str, schema: type[T],
                            temperature: float = 0.0, max_tokens: int = 1024) -> JsonResult:
        """Completion validated against a Pydantic schema, with ONE automatic repair retry."""
        sys_full = (f"{system}\n\nReturn ONLY a JSON object that conforms to this JSON Schema. "
                    f"No prose, no markdown fences.\n{json.dumps(schema.model_json_schema())}")
        results: list[LLMResult] = []
        r = await self.complete(system=sys_full, user=user, model=model, temperature=temperature,
                                max_tokens=max_tokens, json_mode=True)
        results.append(r)
        try:
            return JsonResult(schema.model_validate(extract_json(r.text)), results)
        except (ValueError, ValidationError) as e:
            problem = str(e)[:600]
        repair = (f"{user}\n\nYour previous reply was rejected: {problem}\n"
                  f"Previous reply:\n{r.text[:1500]}\n\nReply again with ONLY the corrected JSON object.")
        r2 = await self.complete(system=sys_full, user=repair, model=model, temperature=0.0,
                                 max_tokens=max_tokens, json_mode=True)
        results.append(r2)
        try:
            return JsonResult(schema.model_validate(extract_json(r2.text)), results)
        except (ValueError, ValidationError) as e:
            err = LLMValidationError(f"invalid JSON after repair: {str(e)[:300]}")
            err.results = results  # type: ignore[attr-defined]  # so usage is still recorded
            raise err from None

    async def chat_with_tools(self, **_: Any) -> Any:  # implemented with the chat agent (Phase 10A)
        raise NotImplementedError("tool-calling arrives with the chat agent in Phase 10A")


def timed() -> float:
    return time.monotonic()
