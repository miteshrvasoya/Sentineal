"""Tiny in-process job manager (no extra service). State lives in the `jobs` table so it survives page reloads."""
from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from collections.abc import Callable
from typing import Any

from app.data.models import JobRecord

log = logging.getLogger("quantlens.jobs")
_tasks: set[asyncio.Task] = set()   # keep references so tasks are not garbage collected mid-run


def create_job(db_factory: Callable, kind: str, symbol: str = "") -> str:  # type: ignore[type-arg]
    jid = uuid.uuid4().hex[:12]
    with db_factory() as db:
        db.add(JobRecord(id=jid, kind=kind, symbol=symbol, status="queued", created=int(time.time())))
        db.commit()
    return jid


def _update(db_factory: Callable, jid: str, **fields: Any) -> None:  # type: ignore[type-arg]
    with db_factory() as db:
        j = db.get(JobRecord, jid)
        if j:
            for k, v in fields.items():
                setattr(j, k, v)
            db.commit()


def job_dict(j: JobRecord) -> dict[str, Any]:
    dur = None if j.started is None else (j.finished or int(time.time())) - j.started
    return {"id": j.id, "kind": j.kind, "symbol": j.symbol, "status": j.status, "progress": round(j.progress, 3), "created": j.created,
            "started": j.started, "finished": j.finished, "duration_s": dur, "error": j.error or None,
            "result": json.loads(j.result) if j.result else None}


async def run_job(db_factory: Callable, jid: str, fn: Callable[[Callable[[float], None]], dict[str, Any]]) -> None:  # type: ignore[type-arg]
    """Run blocking `fn(progress)` in a worker thread and record status, progress, result or error."""
    _update(db_factory, jid, status="running", started=int(time.time()))

    def progress(p: float) -> None:
        _update(db_factory, jid, progress=min(0.99, max(0.0, p)))
    try:
        result = await asyncio.to_thread(fn, progress)
        _update(db_factory, jid, status="done", progress=1.0, finished=int(time.time()), result=json.dumps(result, default=float))
    except Exception as e:  # noqa: BLE001
        log.exception("job %s failed", jid)
        _update(db_factory, jid, status="failed", finished=int(time.time()), error=f"{type(e).__name__}: {e}"[:500])


def spawn(db_factory: Callable, jid: str, fn: Callable) -> asyncio.Task:  # type: ignore[type-arg]
    t = asyncio.create_task(run_job(db_factory, jid, fn))
    _tasks.add(t)
    t.add_done_callback(_tasks.discard)
    return t


async def run_async_job(db_factory: Callable, jid: str, fn: Callable[[Callable[[float], None]], Any]) -> None:  # type: ignore[type-arg]
    """Like run_job, but `fn(progress)` is a coroutine function (network work that must stay on the event loop)."""
    _update(db_factory, jid, status="running", started=int(time.time()))

    def progress(p: float) -> None:
        _update(db_factory, jid, progress=min(0.99, max(0.0, p)))
    try:
        result = await fn(progress)
        _update(db_factory, jid, status="done", progress=1.0, finished=int(time.time()), result=json.dumps(result, default=float))
    except Exception as e:  # noqa: BLE001
        log.exception("job %s failed", jid)
        _update(db_factory, jid, status="failed", finished=int(time.time()), error=f"{type(e).__name__}: {e}"[:500])


def spawn_async(db_factory: Callable, jid: str, fn: Callable) -> asyncio.Task:  # type: ignore[type-arg]
    t = asyncio.create_task(run_async_job(db_factory, jid, fn))
    _tasks.add(t)
    t.add_done_callback(_tasks.discard)
    return t
