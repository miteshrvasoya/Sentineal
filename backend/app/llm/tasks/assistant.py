"""Phase 10A tasks: natural-language screener and the daily briefing."""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.llm import guardrails as gr
from app.llm.prompts import load_prompt
from app.llm.router import LLMRouter
from app.llm.tasks.analyst import Claim, _run
from app.screener import engine as scr

NL_SCREEN, BRIEFING = "nl_screener", "briefing"


# ---------------- natural-language screener ----------------

class NLCondition(BaseModel):
    field: str
    op: str
    value: Any


class NLScreen(BaseModel):
    conditions: list[NLCondition] = Field(max_length=8)
    sort: str = "rs_rank_126"
    desc: bool = True
    explanation: str = Field(max_length=400)
    unsupported: list[str] = Field(default_factory=list, max_length=5)


def nl_check(screen: NLScreen) -> list[str]:
    problems = scr.validate([c.model_dump() for c in screen.conditions])
    f = scr.FIELD_MAP.get(screen.sort)
    if f is None or f.kind != "number":
        problems.append(f"sort must be a numeric field, got {screen.sort!r}")
    for c in screen.conditions:
        fld = scr.FIELD_MAP.get(c.field)
        vals = c.value if isinstance(c.value, list) else [c.value]
        if fld and fld.unit == "pct" and any(isinstance(v, int | float) and not isinstance(v, bool) and abs(v) > 3 for v in vals):
            problems.append(f"{c.field} is a fraction (0.15 means 15%), but got {c.value}")
    if adv := gr.contains_advice(screen.explanation):
        problems.append(f"explanation contains advice {adv[:2]}")
    return problems


async def nl_screen(router: LLMRouter, db: Session, request: str) -> dict[str, Any]:
    request = gr.sanitize(request, 400).strip()
    if not request:
        raise ValueError("request is empty")
    prompt = load_prompt(NL_SCREEN)
    fields = "; ".join(f"{f.key} ({f.kind}{', pct' if f.unit == 'pct' else ''})" for f in scr.FIELDS)
    res = await router.json_task(NL_SCREEN, prompt, {"fields": fields, "untrusted_rules": gr.UNTRUSTED_RULES, "request": gr.wrap_untrusted(request, "request")}, NLScreen, nl_check)
    out: dict[str, Any] = {"provider": res.provider, "model": res.model, "cached": res.cached, "repaired": res.repaired, "prompt": f"{prompt.id}.v{prompt.version}",
                           "problems": res.problems, "withheld": bool(res.problems), "screen": None, "result": None}
    if res.problems:
        return out
    v = res.value
    conds = [c.model_dump() for c in v.conditions]
    out["screen"] = {"conditions": conds, "sort": v.sort, "desc": v.desc, "explanation": v.explanation, "unsupported": v.unsupported}
    out["result"] = scr.screen(scr.universe(db), conds, v.sort, v.desc, 100)
    return out


# ---------------- daily briefing ----------------

class Briefing(BaseModel):
    headline: str = Field(max_length=200)
    market_summary: str = Field(max_length=700)
    movers: list[Claim] = Field(max_length=6)
    watch_items: list[Claim] = Field(max_length=5)
    red_flags: list[Claim] = Field(max_length=5)
    data_notes: list[str] = Field(max_length=5)


def briefing_pack(db: Session) -> dict[str, Any]:
    from app.agent.redflags import red_flags
    from app.api.routes import get_watchlist
    from app.data.analysis import close_series
    facts: dict[str, Any] = {}
    missing: list[str] = []
    rows = scr.universe(db)
    asof = max((r["as_of"] for r in rows), default="n/a")
    b = scr.breadth(rows)
    if b.get("n"):
        for k in ("n", "above_sma50", "above_sma200", "positive_5d", "positive_21d", "near_52w_high", "near_52w_low", "median_5d_return"):
            if b.get(k) is not None:
                facts[f"breadth.{k}"] = round(b[k], 4) if isinstance(b[k], float) else b[k]
    else:
        missing.append("market breadth")
    sec = [r for r in scr.sectors(rows)["rows"] if r.get("ret_21d") is not None]
    for i, r in enumerate(sec[:2]):
        facts[f"sector.best{i + 1}.name"], facts[f"sector.best{i + 1}.ret_21d"] = r["sector"], round(r["ret_21d"], 4)
    for i, r in enumerate(sec[::-1][:2]):
        facts[f"sector.worst{i + 1}.name"], facts[f"sector.worst{i + 1}.ret_21d"] = r["sector"], round(r["ret_21d"], 4)
    if not sec:
        missing.append("sector returns")
    watch = get_watchlist(db)[:15]
    n_flagged = 0
    for sym in watch:
        c = close_series(db, sym)
        if c is not None and len(c) > 6:
            facts[f"watch.{sym}.ret_1d"] = round(float(c.iloc[-1] / c.iloc[-2] - 1), 4)
            facts[f"watch.{sym}.ret_5d"] = round(float(c.iloc[-1] / c.iloc[-6] - 1), 4)
        fl = [f for f in red_flags(db, sym)["flags"] if f["severity"] in ("high", "medium")]
        if fl:
            n_flagged += 1
            facts[f"flags.{sym}.count"] = len(fl)
            facts[f"flags.{sym}.top"] = fl[0]["id"]
            facts[f"flags.{sym}.top_text"] = fl[0]["message"][:60]
    facts["watchlist.size"], facts["watchlist.flagged"] = len(watch), n_flagged
    if not watch:
        missing.append("watchlist")
    return {"symbol": "market", "horizon": 0, "facts": facts, "missing": missing, "asof": asof}


async def make_briefing(router: LLMRouter, pack: dict[str, Any]) -> dict[str, Any]:
    return await _run(router, BRIEFING, pack, Briefing, {"asof": pack["asof"]})
