"""Chat agent: a bounded tool-use loop over read-only tools, with the same guardrails as the other AI features.

The model never sees raw database access. Each step is one structured call: either "call this tool" or "answer". Tool
results are fenced as untrusted data. The final answer must cite tool-call ids, may only quote numbers that appeared in
tool results, and is withheld if it contains advice.
"""
from __future__ import annotations

import json
from typing import Any, Literal

from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.agent import tools as tl
from app.llm import guardrails as gr
from app.llm.base import BudgetExceeded, LLMUnavailable
from app.llm.prompts import load_prompt
from app.llm.router import LLMRouter

TASK = "chat_agent"
MAX_STEPS = 5
MAX_HISTORY = 6
MAX_MESSAGE = 600
RESULT_CHARS = 3500


class AgentStep(BaseModel):
    action: Literal["tool", "answer"]
    tool: str | None = None
    args: dict[str, Any] = Field(default_factory=dict)
    reason: str = Field("", max_length=200)
    answer: str | None = Field(None, max_length=1600)
    citations: list[str] = Field(default_factory=list, max_length=10)
    follow_ups: list[str] = Field(default_factory=list, max_length=3)


def _numbers(results: list[dict[str, Any]]) -> list[float]:
    return gr._context_numbers([r["data"] for r in results])


def make_check(results: list[dict[str, Any]], user_text: str):  # type: ignore[no-untyped-def]
    ids = {r["id"] for r in results}
    ctx = {"tools": _numbers(results), "user": user_text}

    def check(step: AgentStep) -> list[str]:
        problems: list[str] = []
        if step.action == "tool":
            if step.tool not in tl.TOOLS:
                problems.append(f"unknown tool {step.tool!r}; use one of {sorted(tl.TOOLS)}")
            if adv := gr.contains_advice(step.reason):
                problems.append(f"reason contains advice {adv[:2]}")
            return problems
        text = step.answer or ""
        if not text.strip():
            problems.append("an answer step needs non-empty text")
        if adv := gr.contains_advice(text + " " + " ".join(step.follow_ups)):
            problems.append(f"contains trading advice {adv[:3]}")
        if bad := gr.unsupported_numbers(text, ctx, allow_small_ints=True):
            problems.append(f"numbers not found in tool results {bad[:6]}")
        if unknown := sorted(c for c in step.citations if c not in ids):
            problems.append(f"cites tool calls that do not exist {unknown[:4]}")
        if results and not step.citations:
            problems.append("cite the tool call ids you used")
        return problems
    return check


def _fence(r: dict[str, Any]) -> str:
    body = json.dumps(r["data"], default=str)[:RESULT_CHARS] if not r.get("error") else f"ERROR: {r['error']}"
    return f"call id: {r['id']}\ntool: {r['tool']}\nargs: {json.dumps(r['args'])[:300]}\n" + gr.wrap_untrusted(body, "tool_result")


def _history_text(history: list[dict[str, str]]) -> str:
    lines = []
    for m in history[-MAX_HISTORY:]:
        who = "User" if m.get("role") == "user" else "Assistant"
        lines.append(f"{who}: {gr.sanitize(str(m.get('content', '')), MAX_MESSAGE)}")
    return "\n".join(lines) or "(none)"


async def run_agent(router: LLMRouter, db: Session, message: str, history: list[dict[str, str]] | None = None, max_steps: int = MAX_STEPS) -> dict[str, Any]:
    message = gr.sanitize(message, MAX_MESSAGE).strip()
    if not message:
        raise ValueError("message is empty")
    prompt = load_prompt(TASK)
    results: list[dict[str, Any]] = []
    meta: dict[str, Any] = {}
    out: dict[str, Any] = {"answer": None, "citations": [], "follow_ups": [], "steps": [], "withheld": False, "problems": [], "error": None}
    for step_no in range(max_steps + 1):
        final = step_no == max_steps
        instruction = ("You have used all tool calls: reply now with an answer step using only what you already have." if final
                       else "Reply with the next JSON step.")
        try:
            r = await router.json_task(TASK, prompt, {"tools": tl.describe_tools(), "untrusted_rules": gr.UNTRUSTED_RULES, "history": _history_text(history or []),
                                                      "transcript": "\n\n".join(_fence(x) for x in results) or "(none yet)", "message": message,
                                                      "instruction": instruction}, AgentStep, make_check(results, message))
        except BudgetExceeded as e:
            out["error"] = f"Daily AI budget reached: {e}"
            break
        except LLMUnavailable as e:
            out["error"] = f"No provider could answer: {e}"
            break
        meta = {"provider": r.provider, "model": r.model, "cached": r.cached}
        step = r.value
        if r.problems:
            out.update(withheld=True, problems=r.problems)
            break
        if step.action == "answer" or final:
            if step.action != "answer" or not step.answer:
                out.update(withheld=True, problems=["the model did not produce an answer"])
                break
            out.update(answer=step.answer, citations=step.citations, follow_ups=step.follow_ups)
            break
        cid = f"t{len(results) + 1}"
        try:
            data, err = tl.call(db, step.tool or "", step.args), None
        except tl.ToolError as e:
            data, err = {}, str(e)
        res = {"id": cid, "tool": step.tool, "args": step.args, "data": data, "error": err}
        results.append(res)
        out["steps"].append({"id": cid, "tool": step.tool, "args": step.args, "reason": step.reason, "error": err,
                             "result": None if err else json.dumps(data, default=str)[:1200]})
    out["meta"] = meta
    out["prompt"] = f"{prompt.id}.v{prompt.version}"
    return out
