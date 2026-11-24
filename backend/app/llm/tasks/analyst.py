"""Phase 8A tasks: AI analyst, model explainer, why-did-it-move, backtest reviewer.

All four share one contract: the LLM receives a context pack (facts computed in Python), must cite fact ids for every
claim, may only quote numbers that exist in the pack, and must not give advice. Output that still breaks those rules
after one regeneration is withheld rather than shown.
"""
from __future__ import annotations

import math
import re
from typing import Any, Literal

import pandas as pd
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.data.models import Article, ArticleTicker
from app.llm import guardrails as gr
from app.llm.context import article_block, article_pack, article_text
from app.llm.packs import pack_block, pack_numbers
from app.llm.prompts import load_prompt
from app.llm.router import LLMRouter, TaskResult

ANALYST, EXPLAIN_MODEL, EXPLAIN_MOVE, BACKTEST_REVIEW = "analyst", "explain_model", "explain_move", "backtest_review"
PROSE_SKIP = {"stance", "verdict", "confidence"}
CITE_KEYS = {"evidence", "article_ids"}


class Claim(BaseModel):
    text: str = Field(max_length=320)
    evidence: list[str] = Field(min_length=1, max_length=8)


class AnalystReport(BaseModel):
    stance: Literal["leaning positive", "leaning negative", "mixed", "unclear"]
    headline: str = Field(max_length=200)
    plain_summary: str = Field(max_length=700)
    in_favour: list[Claim] = Field(max_length=6)
    against: list[Claim] = Field(max_length=6)
    conflicts: list[Claim] = Field(max_length=4)
    data_gaps: list[str] = Field(max_length=6)


class ModelExplanation(BaseModel):
    verdict_in_words: str = Field(max_length=300)
    plain_summary: str = Field(max_length=700)
    drivers: list[Claim] = Field(max_length=6)
    cautions: list[Claim] = Field(max_length=5)


class MoveCandidate(BaseModel):
    text: str = Field(max_length=320)
    article_ids: list[str] = Field(max_length=6)
    evidence: list[str] = Field(default_factory=list, max_length=8)
    strength: Literal["plausible", "weak"]


class MoveExplanation(BaseModel):
    plain_summary: str = Field(max_length=700)
    market_context: Claim
    candidates: list[MoveCandidate] = Field(max_length=5)
    unexplained: str = Field(max_length=300)


class BacktestReview(BaseModel):
    verdict: Literal["unreliable", "weak evidence", "plausible but unproven"]
    plain_summary: str = Field(max_length=700)
    concerns: list[Claim] = Field(max_length=8)
    strengths: list[Claim] = Field(max_length=4)
    what_to_check_next: list[str] = Field(max_length=5)


def _walk(obj: Any, prose: list[str], cites: list[str]) -> None:
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k in CITE_KEYS and isinstance(v, list):
                cites += [str(x) for x in v]
            elif k in PROSE_SKIP:
                continue
            else:
                _walk(v, prose, cites)
    elif isinstance(obj, list):
        for v in obj:
            _walk(v, prose, cites)
    elif isinstance(obj, str):
        prose.append(obj)


def make_check(pack: dict[str, Any], article_ids: set[str] | None = None, extra_context: Any = None):  # type: ignore[no-untyped-def]
    """Post-check shared by the four tasks: no advice, no invented numbers, no citation of unknown ids."""
    facts = set(pack["facts"])
    # the windows named in fact ids ("ret_21d" -> 21) may be quoted too
    id_numbers = [float(n) for k in facts for n in re.findall(r"\d+", k)]
    context = {"facts": pack_numbers(pack), "ids": id_numbers, "extra": extra_context}

    def check(report: BaseModel) -> list[str]:
        prose: list[str] = []
        cites: list[str] = []
        _walk(report.model_dump(), prose, cites)
        problems: list[str] = []
        text = " ".join(prose)
        if adv := gr.contains_advice(text):
            problems.append(f"contains trading advice {adv[:3]}")
        if bad := gr.unsupported_numbers(text, context, allow_small_ints=True):
            problems.append(f"numbers not in the facts {bad[:6]}")
        unknown = sorted(c for c in cites if c not in facts and c not in (article_ids or set()))
        if unknown:
            problems.append(f"cites ids that do not exist {unknown[:6]}")
        return problems
    return check


async def _run(router: LLMRouter, task: str, pack: dict[str, Any], schema: type[BaseModel], variables: dict[str, str],
               article_ids: set[str] | None = None, extra_context: Any = None) -> dict[str, Any]:
    prompt = load_prompt(task)
    res: TaskResult = await router.json_task(task, prompt, {"untrusted_rules": gr.UNTRUSTED_RULES, "facts": pack_block(pack), **variables},
                                             schema, make_check(pack, article_ids, extra_context))
    withheld = bool(res.problems)
    return {"report": None if withheld else res.value.model_dump(), "withheld": withheld, "problems": res.problems,
            "provider": res.provider, "model": res.model, "cached": res.cached, "repaired": res.repaired,
            "prompt": f"{prompt.id}.v{prompt.version}"}


async def analyst_report(router: LLMRouter, pack: dict[str, Any]) -> dict[str, Any]:
    return await _run(router, ANALYST, pack, AnalystReport, {"symbol": pack["symbol"]})


async def explain_model(router: LLMRouter, pack: dict[str, Any], model: str) -> dict[str, Any]:
    return await _run(router, EXPLAIN_MODEL, pack, ModelExplanation, {"symbol": pack["symbol"], "model": model})


def model_pack(symbol: str, view: dict[str, Any], metrics: dict[str, Any] | None, horizon: int) -> dict[str, Any]:
    """Facts about one model's current output, its walk-forward record and its drivers (from `views` / evaluation)."""
    from app.llm.packs import flatten
    facts: dict[str, Any] = {}
    flatten("forecast", {k: view.get(k) for k in ("p_up", "p_flat", "p_down", "median", "kind", "asof", "horizon")}, facts)
    for q, v in (view.get("quantiles") or {}).items():
        if isinstance(v, int | float) and math.isfinite(v):
            facts[f"forecast.q{q}"] = round(float(v), 4)
    ex = view.get("extras") or {}
    if ex.get("calibration"):
        flatten("trust", ex["calibration"], facts)
    for i, d in enumerate((ex.get("shap_now") or [])[:6]):
        facts[f"driver{i + 1}.feature"] = d["feature"]
        facts[f"driver{i + 1}.pushes_up"] = round(float(d["toward_up"]) - float(d["toward_down"]), 4)
    if not ex.get("shap_now"):
        for i, d in enumerate((view.get("drivers") or [])[:6]):
            if isinstance(d.get("value"), int | float):
                facts[f"driver{i + 1}.{d['name']}"] = round(float(d["value"]), 4)
    if metrics:
        flatten("record", {k: metrics.get(k) for k in ("brier", "brier_skill", "hit_rate", "naive_rate", "p_adjusted", "ece", "n_effective", "verdict", "verdict_reason")}, facts)
    facts["horizon_days"] = horizon
    return {"symbol": symbol, "horizon": horizon, "facts": facts, "missing": [] if metrics else ["record (no walk-forward test stored)"]}


# ---------- why did it move ----------

def move_pack(db: Session, symbol: str, start: str, end: str) -> dict[str, Any]:
    from app.data.analysis import close_series
    from app.data.prices import apply_adjustment, load_prices
    from app.features.pipeline import to_frame

    p = load_prices(db, symbol, "1d")
    if p.empty:
        raise ValueError(f"no stored prices for {symbol}")
    df = to_frame(apply_adjustment(p))
    tz = df.index.tz
    w = df.loc[(df.index >= pd.Timestamp(start, tz=tz)) & (df.index <= pd.Timestamp(end, tz=tz))]
    if len(w) < 2:
        raise ValueError("need at least two trading days inside the period")
    prev = df.loc[df.index < w.index[0], "close"]
    base = float(prev.iloc[-1]) if len(prev) else float(w["close"].iloc[0])
    rets = w["close"].pct_change()
    rets.iloc[0] = w["close"].iloc[0] / base - 1
    facts: dict[str, Any] = {"move.stock_return": round(float(w["close"].iloc[-1] / base - 1), 4), "move.days": len(w),
                             "move.first_day": str(w.index[0].date()), "move.last_day": str(w.index[-1].date()),
                             "move.biggest_day": str(rets.abs().idxmax().date()), "move.biggest_day_return": round(float(rets[rets.abs().idxmax()]), 4)}
    if "volume" in w and len(df) > 80:
        avg = float(df["volume"].iloc[-80:].mean())
        if avg > 0:
            facts["move.volume_vs_80d_avg"] = round(float(w["volume"].mean() / avg), 2)
    missing = []
    try:
        idx = close_series(db, "NIFTY 50")
        if idx is None:
            raise ValueError
        ix = idx.loc[(idx.index >= w.index[0]) & (idx.index <= w.index[-1])]
        ib = idx.loc[idx.index < w.index[0]]
        ibase = float(ib.iloc[-1]) if len(ib) else float(ix.iloc[0])
        facts["move.index_return"] = round(float(ix.iloc[-1] / ibase - 1), 4)
        facts["move.excess_return"] = round(facts["move.stock_return"] - facts["move.index_return"], 4)
    except Exception:  # noqa: BLE001
        missing.append("index comparison (NIFTY 50 not stored)")
    return {"symbol": symbol, "horizon": len(w), "facts": facts, "missing": missing}


def articles_for_move(db: Session, symbol: str, start: str, end: str, limit: int = 12) -> list[dict[str, Any]]:
    t0 = int(pd.Timestamp(start, tz="UTC").timestamp()) - 2 * 86400
    t1 = int(pd.Timestamp(end, tz="UTC").timestamp()) + 86400
    q = (select(Article).join(ArticleTicker, ArticleTicker.article_id == Article.id)
         .where(ArticleTicker.symbol == symbol, Article.published >= t0, Article.published <= t1)
         .order_by(Article.published.desc()).limit(limit))
    return [article_pack(a, [symbol]) for a in db.scalars(q)]


async def explain_move(router: LLMRouter, pack: dict[str, Any], packs: list[dict[str, Any]], start: str, end: str) -> dict[str, Any]:
    ids = {p["article_id"] for p in packs}
    arts = "\n\n".join(article_block(p) for p in packs) or "(no stored articles for this period)"
    out = await _run(router, EXPLAIN_MOVE, pack, MoveExplanation, {"symbol": pack["symbol"], "start": start, "end": end, "articles": arts},
                     ids, [article_text(p) for p in packs])
    out["articles"] = [{"id": p["article_id"], "title": p["title"], "source": p["source"], "url": p["url"], "published": p["published_utc"],
                        "injection_flags": p["injection_flags"]} for p in packs]
    return out


# ---------- backtest reviewer ----------

def backtest_red_flags(m: dict[str, Any]) -> list[dict[str, str]]:
    """Deterministic checks on a backtest summary (these do not need an LLM and run even when none is configured)."""
    flags: list[dict[str, str]] = []

    def add(fid: str, msg: str) -> None:
        flags.append({"id": fid, "message": msg})

    n = m.get("n_trades")
    if isinstance(n, int | float) and n < 30:
        add("too_few_trades", f"Only {int(n)} trades: too few to separate skill from luck.")
    if m.get("costs_included") is False:
        add("costs_ignored", "Trading costs (brokerage, STT, slippage) were not included; real results would be lower.")
    oos = m.get("oos_fraction")
    if oos is None or (isinstance(oos, int | float) and oos < 0.2):
        add("no_out_of_sample", "Little or no data was held out; the strategy was judged on the data it was built on.")
    yrs = m.get("years")
    if isinstance(yrs, int | float) and yrs < 3:
        add("short_history", f"Only {yrs:g} years of history: may cover a single market regime.")
    top = m.get("top5_trade_share")
    if isinstance(top, int | float) and top > 0.5:
        add("concentrated_profit", f"{top:.0%} of profit came from the five best trades; the result may hinge on luck.")
    tuned = m.get("n_params_tuned")
    if isinstance(tuned, int | float) and tuned >= 5:
        add("many_tuned_params", f"{int(tuned)} parameters were tuned: high risk of overfitting.")
    sh = m.get("sharpe")
    if isinstance(sh, int | float) and sh > 3:
        add("too_good", f"A Sharpe ratio of {sh:.1f} is rarely real after costs; suspect a bug or look-ahead.")
    bp = m.get("bootstrap_p")
    if isinstance(bp, int | float) and bp > 0.1:
        add("not_significant", f"Bootstrap p-value {bp:.2f}: the result is within what luck produces.")
    return flags


def backtest_pack(strategy: str, metrics: dict[str, Any]) -> dict[str, Any]:
    from app.llm.packs import flatten
    facts: dict[str, Any] = {}
    flatten("metrics", metrics, facts)
    flags = backtest_red_flags(metrics)
    for f in flags:
        facts[f"flag.{f['id']}"] = True
    facts["flags.count"] = len(flags)
    return {"symbol": strategy, "horizon": 0, "facts": facts, "missing": [], "flags": flags}


async def review_backtest(router: LLMRouter, strategy: str, pack: dict[str, Any]) -> dict[str, Any]:
    out = await _run(router, BACKTEST_REVIEW, pack, BacktestReview, {"strategy": gr.sanitize(strategy, 80)},
                     None, [f["message"] for f in pack.get("flags", [])])
    out["red_flags"] = pack.get("flags", [])
    return out
