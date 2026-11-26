"""Per-call usage table, cost estimates and the daily hard budget stop."""
from __future__ import annotations

import time
from collections.abc import Callable
from datetime import datetime

from sqlalchemy import func, select

from app.data import calendar as cal
from app.data.models import LLMUsage
from app.llm.base import BudgetExceeded


def estimate_tokens(text: str) -> int:
    """Rough token count (~4 characters per token for English). Only used to reserve budget before a call."""
    return max(1, len(text) // 4)


class UsageTracker:
    def __init__(self, db_factory: Callable, token_budget: int, usd_budget: float,  # type: ignore[type-arg]
                 pricing: dict[str, dict[str, float]], default_price: dict[str, float]) -> None:
        self.db_factory, self.token_budget, self.usd_budget = db_factory, token_budget, usd_budget
        self.pricing, self.default_price = pricing, default_price

    @staticmethod
    def today() -> str:
        return datetime.now(cal.IST).strftime("%Y-%m-%d")

    def cost(self, model: str, tokens_in: int, tokens_out: int) -> float:
        if model.endswith(":free") or model == "openrouter/free":      # OpenRouter free models cost nothing (but have request limits)
            return 0.0
        p = self.pricing.get(model, self.default_price)
        return (tokens_in * p["in"] + tokens_out * p["out"]) / 1_000_000

    def spent_today(self) -> tuple[int, float]:
        with self.db_factory() as db:
            t, c = db.execute(select(func.coalesce(func.sum(LLMUsage.tokens_in + LLMUsage.tokens_out), 0),
                                     func.coalesce(func.sum(LLMUsage.cost_usd), 0.0))
                              .where(LLMUsage.day == self.today())).one()
        return int(t), float(c)

    def check(self, model: str, est_in: int, max_out: int) -> None:
        """HARD STOP. Reserve the worst case (input estimate + max output tokens) before calling."""
        tokens, usd = self.spent_today()
        if tokens + est_in + max_out > self.token_budget:
            raise BudgetExceeded(f"daily token budget {self.token_budget} would be exceeded "
                                 f"(used {tokens}, this call needs up to {est_in + max_out})")
        if usd + self.cost(model, est_in, max_out) > self.usd_budget:
            raise BudgetExceeded(f"daily spend budget ${self.usd_budget:.2f} would be exceeded (used ${usd:.4f})")

    def record(self, *, task: str, provider: str, model: str, tokens_in: int = 0, tokens_out: int = 0,
               latency_ms: int = 0, cached: bool = False, ok: bool = True, error: str = "") -> None:
        with self.db_factory() as db:
            db.add(LLMUsage(ts=int(time.time()), day=self.today(), task=task, provider=provider, model=model,
                            tokens_in=tokens_in, tokens_out=tokens_out,
                            cost_usd=0.0 if cached else self.cost(model, tokens_in, tokens_out),
                            latency_ms=latency_ms, cached=int(cached), ok=int(ok), error=error[:200]))
            db.commit()

    def summary(self, days: int = 14) -> dict:
        with self.db_factory() as db:
            rows = db.execute(select(LLMUsage.day, LLMUsage.task, func.sum(LLMUsage.tokens_in), func.sum(LLMUsage.tokens_out),
                                     func.sum(LLMUsage.cost_usd), func.count(), func.sum(LLMUsage.cached), func.sum(1 - LLMUsage.ok))
                              .group_by(LLMUsage.day, LLMUsage.task).order_by(LLMUsage.day.desc()).limit(days * 12)).all()
        tokens, usd = self.spent_today()
        return {"today": {"tokens": tokens, "usd": round(usd, 6), "token_budget": self.token_budget,
                          "usd_budget": self.usd_budget, "exhausted": tokens >= self.token_budget or usd >= self.usd_budget},
                "rows": [{"day": d, "task": t, "tokens_in": int(a or 0), "tokens_out": int(b or 0), "usd": round(float(c or 0), 6),
                          "calls": int(n), "cache_hits": int(h or 0), "failures": int(f or 0)} for d, t, a, b, c, n, h, f in rows]}
