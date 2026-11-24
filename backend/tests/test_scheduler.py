"""Phase 10: scheduler timing rules, isolation, recording, API."""
from datetime import date, datetime, timedelta

import pytest

from app.data import calendar as cal
from app.data import db as dbmod
from app.data.models import SchedulerRun
from app.scheduler import IST, JobSpec, Scheduler
from tests.llm.fakes import session_ctx

WED = date(2026, 3, 4)
SAT = date(2026, 3, 7)


@pytest.fixture
def mem():
    dbmod.init_engine("sqlite:///:memory:")


class Clock:
    def __init__(self, d, h, m=0):
        self.t = datetime(d.year, d.month, d.day, h, m, tzinfo=IST)

    def __call__(self):
        return self.t

    def advance(self, **kw):
        self.t += timedelta(**kw)


def make(clock, fn=None, schedule="after_close", enabled=True):
    calls = []

    async def ok():
        calls.append(1)
        return {"n": len(calls)}
    return Scheduler(session_ctx, [JobSpec("j", "J", "d", schedule, fn or ok, enabled)], now=clock), calls


def test_test_dates_are_what_we_think():
    assert cal.is_trading_day(WED) and not cal.is_trading_day(SAT)


async def test_after_close_job_waits_for_16_30_runs_once_and_not_on_weekends(mem):
    c = Clock(WED, 15, 0)
    s, calls = make(c)
    assert await s.tick() == []                                  # market still open
    c.advance(hours=1, minutes=29)                               # 16:29
    assert await s.tick() == []
    c.advance(minutes=1)                                         # 16:30
    assert await s.tick() == ["j"] and len(calls) == 1
    c.advance(hours=3)
    assert await s.tick() == [] and len(calls) == 1              # already ran today
    c.advance(days=1)                                            # Thursday 19:30: a missed 16:30 still runs (catch-up)
    assert await s.tick() == ["j"] and len(calls) == 2
    w = Clock(SAT, 18)
    s2, calls2 = make(w)
    assert await s2.tick() == [] and calls2 == []                # no trading on Saturday


async def test_interval_job_respects_its_period(mem):
    c = Clock(WED, 10)
    s, calls = make(c, schedule="every:60")
    assert await s.tick() == ["j"]
    c.advance(minutes=59)
    assert await s.tick() == []
    c.advance(minutes=2)
    assert await s.tick() == ["j"] and len(calls) == 2


async def test_failure_is_recorded_isolated_and_retried_with_a_limit(mem):
    c = Clock(WED, 17)

    async def boom():
        raise RuntimeError("provider down")
    s = Scheduler(session_ctx, [JobSpec("bad", "B", "d", "after_close", boom), JobSpec("good", "G", "d", "after_close", lambda: _ok())], now=c)
    assert await s.tick() == ["bad", "good"]                     # the failure did not stop the next job
    assert s.last_run("bad")["status"] == "failed" and "provider down" in s.last_run("bad")["error"] and s.last_run("good")["status"] == "ok"
    assert await s.tick() == []                                  # too soon to retry
    for _ in range(4):
        c.advance(minutes=31)
        await s.tick()
    fails = [r for r in s.recent(50) if r["job"] == "bad" and r["status"] == "failed"]
    assert len(fails) == 3                                       # capped at 3 attempts per day


async def _ok():
    return {"fine": True}


async def test_disabled_job_never_runs_and_overlap_is_prevented(mem):
    c = Clock(WED, 17)
    s, calls = make(c, enabled=False)
    assert await s.tick() == [] and not s.status()[0]["enabled"] and s.status()[0]["when"] == "disabled"
    import asyncio
    gate = asyncio.Event()

    async def slow():
        await gate.wait()
        return {}
    s2 = Scheduler(session_ctx, [JobSpec("j", "J", "d", "every:1", slow)], now=c)
    t = asyncio.create_task(s2.run_job("j", "manual"))
    await asyncio.sleep(0.05)
    assert (await s2.run_job("j"))["status"] == "skipped" and s2.status()[0]["running"] and not s2.is_due(s2.jobs["j"])
    gate.set()
    assert (await t)["status"] == "ok"


async def test_runs_are_recorded_with_result_and_stale_running_rows_are_ignored(mem):
    c = Clock(WED, 17)
    s, _ = make(c)
    await s.run_job("j", "manual")
    r = s.last_run("j")
    assert r["trigger"] == "manual" and r["status"] == "ok" and r["result"] == {"n": 1} and r["duration_s"] is not None
    # a crash leaves a 'running' row behind; after two hours it must not block the job forever
    s3, _ = make(Clock(WED, 17))
    with session_ctx() as db:
        db.query(SchedulerRun).delete()
        db.add(SchedulerRun(job="j", started=int(Clock(WED, 16, 31)()  .timestamp()), status="running"))
        db.commit()
    assert not s3.is_due(s3.jobs["j"])                           # 29 minutes: maybe still running
    s3.now = Clock(WED, 19, 0)
    assert s3.is_due(s3.jobs["j"])


def test_default_jobs_and_api(client):
    r = client.get("/scheduler/status").json()
    names = {j["name"] for j in r["jobs"]}
    assert r["enabled"] is False and {"refresh_prices", "ingest_news", "enrich_news", "retrain_models"} == names
    retrain = next(j for j in r["jobs"] if j["name"] == "retrain_models")
    assert retrain["enabled"] is False and retrain["last_run"] is None
    assert client.post("/scheduler/run/nope").status_code == 404
