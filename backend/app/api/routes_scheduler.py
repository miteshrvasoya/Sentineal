"""Scheduler status and manual triggers."""
from __future__ import annotations

import asyncio

from fastapi import APIRouter, HTTPException, Request

from app.config import get_settings

router = APIRouter()
_tasks: set[asyncio.Task] = set()


@router.get("/scheduler/status")
def status(request: Request) -> dict:
    sch = request.app.state.scheduler
    return {"enabled": get_settings().scheduler_enabled, "tick_seconds": get_settings().scheduler_tick_seconds, "jobs": sch.status(), "recent": sch.recent(15),
            "note": "The scheduler is off unless SCHEDULER_ENABLED=true in .env. Jobs only run while the backend is running; a missed daily job runs when the backend next starts after 16:30 IST on a trading day."}


@router.post("/scheduler/run/{job}", status_code=202)
async def run_now(job: str, request: Request) -> dict:
    sch = request.app.state.scheduler
    if job not in sch.jobs:
        raise HTTPException(404, f"unknown job {job!r}; choose from {list(sch.jobs)}")
    if job in sch._running:
        raise HTTPException(409, f"{job} is already running")
    t = asyncio.create_task(sch.run_job(job, "manual"))
    _tasks.add(t)
    t.add_done_callback(_tasks.discard)
    return {"started": job}
