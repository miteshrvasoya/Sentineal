"""Background scheduler: keeps prices, news and (optionally) model runs fresh without anyone clicking.

Design: a plain asyncio loop (no extra service). Each job has a schedule: `after_close` (once per trading day, an hour
after the NSE close, with catch-up if the app was down then) or `every:<minutes>`. Every run is recorded in the
`scheduler_runs` table, failures are isolated and retried later, and a job never overlaps itself.
"""
from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import date, datetime
from datetime import time as dtime

from sqlalchemy import select

from app.data import calendar as cal
from app.data.models import SchedulerRun

log = logging.getLogger("quantlens.scheduler")
IST = cal.IST
RUN_AFTER = dtime(16, 30)
RETRY_AFTER_S = 1800
MAX_FAILS_PER_DAY = 3
STALE_RUNNING_S = 2 * 3600


@dataclass
class JobSpec:
    name: str
    title: str
    description: str
    schedule: str                              # "after_close" | "every:<minutes>"
    fn: Callable[[], Awaitable[dict]]
    enabled: bool = True


def _run_dict(r: SchedulerRun) -> dict:
    dur = None if r.finished is None else r.finished - r.started
    return {"id": r.id, "job": r.job, "trigger": r.trigger, "started": r.started, "finished": r.finished, "duration_s": dur, "status": r.status,
            "error": r.error or None, "result": json.loads(r.result) if r.result else None}


class Scheduler:
    def __init__(self, db_factory: Callable, jobs: list[JobSpec], now: Callable[[], datetime] | None = None) -> None:  # type: ignore[type-arg]
        self.db_factory, self.jobs = db_factory, {j.name: j for j in jobs}
        self.now = now or (lambda: datetime.now(IST))
        self._running: set[str] = set()

    # ---- state
    def _runs(self, name: str, since: int = 0) -> list[SchedulerRun]:
        with self.db_factory() as db:
            rows = list(db.scalars(select(SchedulerRun).where(SchedulerRun.job == name, SchedulerRun.started >= since).order_by(SchedulerRun.started.desc())))
            for r in rows:
                db.expunge(r)
            return rows

    def last_run(self, name: str) -> dict | None:
        rows = self._runs(name)
        return _run_dict(rows[0]) if rows else None

    def recent(self, limit: int = 20) -> list[dict]:
        with self.db_factory() as db:
            return [_run_dict(r) for r in db.scalars(select(SchedulerRun).order_by(SchedulerRun.started.desc()).limit(limit))]

    # ---- schedule logic
    def is_due(self, spec: JobSpec, now: datetime | None = None) -> bool:
        now = (now or self.now()).astimezone(IST)
        if not spec.enabled or spec.name in self._running:
            return False
        ts = int(now.timestamp())
        if spec.schedule == "after_close":
            d: date = now.date()
            if not cal.is_trading_day(d) or now.time() < RUN_AFTER:
                return False
            since = int(datetime.combine(d, RUN_AFTER, IST).timestamp())
            runs = [r for r in self._runs(spec.name, since) if not (r.status == "running" and ts - r.started > STALE_RUNNING_S)]
            if any(r.status in ("ok", "running") for r in runs):
                return False
            fails = [r for r in runs if r.status == "failed"]
            if len(fails) >= MAX_FAILS_PER_DAY:
                return False
            return not fails or ts - (fails[0].finished or fails[0].started) >= RETRY_AFTER_S
        if spec.schedule.startswith("every:"):
            minutes = float(spec.schedule.split(":", 1)[1])
            runs = [r for r in self._runs(spec.name, ts - int(minutes * 60) - 1) if not (r.status == "running" and ts - r.started > STALE_RUNNING_S)]
            return not runs
        raise ValueError(f"bad schedule {spec.schedule!r}")

    def next_hint(self, spec: JobSpec) -> str:
        if not spec.enabled:
            return "disabled"
        if spec.schedule == "after_close":
            return "once per trading day after 16:30 IST"
        return f"every {spec.schedule.split(':', 1)[1]} minutes"

    # ---- execution
    async def run_job(self, name: str, trigger: str = "schedule") -> dict:
        spec = self.jobs[name]
        if name in self._running:
            return {"job": name, "status": "skipped", "error": "already running"}
        self._running.add(name)
        with self.db_factory() as db:
            row = SchedulerRun(job=name, trigger=trigger, started=int(self.now().timestamp()), status="running")
            db.add(row)
            db.commit()
            rid = row.id
        status, result, error = "ok", {}, ""
        try:
            result = await spec.fn()
        except Exception as e:  # noqa: BLE001  one failing job must never stop the others
            status, error = "failed", f"{type(e).__name__}: {e}"[:500]
            log.exception("scheduled job %s failed", name)
        finally:
            self._running.discard(name)
        with self.db_factory() as db:
            r = db.get(SchedulerRun, rid)
            r.finished, r.status, r.result, r.error = int(self.now().timestamp()), status, json.dumps(result, default=str)[:20000], error
            db.commit()
        return {"job": name, "status": status, "error": error or None, "result": result}

    async def tick(self) -> list[str]:
        ran = []
        for spec in list(self.jobs.values()):
            if self.is_due(spec):
                await self.run_job(spec.name)
                ran.append(spec.name)
        return ran

    def status(self) -> list[dict]:
        return [{"name": s.name, "title": s.title, "description": s.description, "schedule": s.schedule, "when": self.next_hint(s), "enabled": s.enabled,
                 "running": s.name in self._running, "due_now": self.is_due(s), "last_run": self.last_run(s.name)} for s in self.jobs.values()]

    async def loop(self, tick_seconds: int) -> None:
        log.info("scheduler started (tick %ss, jobs: %s)", tick_seconds, ", ".join(self.jobs))
        while True:
            try:
                await self.tick()
            except Exception:  # noqa: BLE001
                log.exception("scheduler tick failed")
            await asyncio.sleep(tick_seconds)


# ---------------- real jobs ----------------

def default_jobs(db_factory: Callable) -> list[JobSpec]:  # type: ignore[type-arg]
    from app.config import get_settings
    s = get_settings()

    async def refresh_prices() -> dict:
        from app.data.analysis import close_series  # noqa: F401
        from app.data.ingest import backfill_many
        from app.deps import get_router
        with db_factory() as db:
            from app.api.routes import get_watchlist
            syms = list(dict.fromkeys(get_watchlist(db) + ["NIFTY 50", "INDIA VIX"]))
            res = await backfill_many(db, get_router(), syms, "1d")
        return {"symbols": len(res), "ok": sum(r["ok"] for r in res), "new_bars": sum(r["new_bars"] for r in res), "failed": [r["symbol"] for r in res if not r["ok"]]}

    async def ingest_news() -> dict:
        from app.api.routes import get_watchlist, symbol_table
        from app.data.news_ingest import ingest_symbol
        from app.deps import get_news_router
        from app.nlp.entities import get_resolver
        from app.nlp.factory import get_scorer
        names = {x.symbol: x.name for x in symbol_table()}
        out = {"symbols": 0, "fetched": 0, "errors": {}}
        with db_factory() as db:
            for sym in get_watchlist(db):
                r = await ingest_symbol(db, get_news_router(), get_resolver(), get_scorer(), sym, names.get(sym, sym), 3)
                out["symbols"] += 1
                out["fetched"] += r["fetched"]
                out["errors"].update({f"{sym}:{k}": v for k, v in r["errors"].items()})
        return out

    async def enrich_news() -> dict:
        from app.api.routes import get_watchlist
        from app.deps import get_llm_router
        from app.llm.tasks.news_enrich import enrich_pending
        from app.nlp.entities import get_resolver
        r = get_llm_router()
        if not r.available("news_enrich"):
            return {"skipped": "no LLM provider configured"}
        done = 0
        stop = None
        with db_factory() as db:
            for sym in get_watchlist(db):
                o = await enrich_pending(db, r, get_resolver(), sym, 24)
                done += o["processed"]
                if o["stopped"]:
                    stop = o["stopped"]
                    break
        return {"processed": done, "stopped": stop}

    async def retrain_models() -> dict:
        from app.api.routes import get_watchlist
        from app.data.prices import apply_adjustment, load_prices
        from app.eval.runner import run_models
        from app.features.pipeline import to_frame
        names = [n.strip() for n in s.scheduler_models.split(",") if n.strip()]
        done, failed = [], {}
        with db_factory() as db:
            syms = get_watchlist(db)
            frames = {sym: to_frame(apply_adjustment(p)) for sym in syms if not (p := load_prices(db, sym, "1d")).empty}
        for sym, df in frames.items():
            try:
                await asyncio.to_thread(run_models, db_factory, sym, df, names, 5, True, "expanding", True)
                done.append(sym)
            except Exception as e:  # noqa: BLE001
                failed[sym] = str(e)[:120]
        return {"models": names, "retrained": done, "failed": failed}

    async def daily_briefing() -> dict:
        from app.deps import get_llm_router
        from app.llm.tasks.assistant import BRIEFING, briefing_pack, make_briefing
        r = get_llm_router()
        if not r.available(BRIEFING):
            return {"skipped": "no LLM provider configured"}
        with db_factory() as db:
            pack = briefing_pack(db)
        if not pack["facts"]:
            return {"skipped": "no stored data"}
        out = await make_briefing(r, pack)
        return {"asof": pack["asof"], "facts": pack["facts"], "missing": pack["missing"], **out}

    return [
        JobSpec("refresh_prices", "Refresh prices", "Fetch new daily bars for the watchlist and indices.", "after_close", refresh_prices),
        JobSpec("ingest_news", "Fetch news", "Pull the last 3 days of news for each watchlist stock and score it locally.", "every:180", ingest_news),
        JobSpec("enrich_news", "AI-enrich news", "Classify new articles with the LLM (skipped without a provider; respects the daily budget).", "every:360", enrich_news),
        JobSpec("daily_briefing", "Daily briefing", "Write the AI market briefing from the day's computed facts (skipped without an LLM provider).", "after_close", daily_briefing),
        JobSpec("retrain_models", "Retrain models", "Re-run the chosen models and their walk-forward test on each watchlist stock; adds a registry version.", "after_close",
                retrain_models, enabled=s.scheduler_retrain),
    ]
