"""Opt-in checks against a real PostgreSQL (skipped unless TEST_PG_URL is set, e.g. after `make db-up`):

    TEST_PG_URL=postgresql+psycopg://quantlens:quantlens@127.0.0.1:5432/quantlens uv run pytest tests/test_postgres.py

The tests use whatever database that URL names and delete only the rows they create.
"""
import os

import numpy as np
import pandas as pd
import pytest
from sqlalchemy import inspect, select

from app.data import db as dbmod
from app.data.models import JobRecord, Price, SchedulerRun
from app.data.prices import load_prices, upsert_prices

URL = os.environ.get("TEST_PG_URL", "")
pytestmark = pytest.mark.skipif(not URL, reason="set TEST_PG_URL to run PostgreSQL checks")


@pytest.fixture
def pg():
    eng = dbmod.init_engine(URL)
    yield eng
    with next(dbmod.get_session()) as s:
        s.query(Price).filter(Price.symbol == "PGTEST").delete()
        s.query(JobRecord).filter(JobRecord.symbol == "PGTEST").delete()
        s.query(SchedulerRun).filter(SchedulerRun.job == "pgtest").delete()
        s.commit()


def test_startup_migrates_and_is_repeatable(pg):
    assert {"prices", "articles", "model_runs", "scheduler_runs", "alembic_version"} <= set(inspect(pg).get_table_names())
    dbmod.init_engine(URL)                                                   # a second start must not fail


def test_prices_roundtrip_and_incremental_upsert(pg):
    idx = pd.bdate_range("2024-01-01", periods=30, tz="UTC")
    df = pd.DataFrame({"open": 1.0, "high": 2.0, "low": 0.5, "close": np.linspace(1, 2, 30), "adj_close": np.linspace(1, 2, 30), "volume": 10.0}, index=idx)
    with next(dbmod.get_session()) as s:
        assert upsert_prices(s, "PGTEST", "1d", df, "t") == 30
        assert upsert_prices(s, "PGTEST", "1d", df, "t") == 0                # idempotent
        assert len(load_prices(s, "PGTEST", "1d")) == 30


def test_autoincrement_ids_and_text_columns(pg):
    with next(dbmod.get_session()) as s:
        a, b = SchedulerRun(job="pgtest", started=1, status="ok", result="x" * 50_000), SchedulerRun(job="pgtest", started=2, status="ok")
        s.add_all([a, b])
        s.commit()
        assert b.id == a.id + 1
        assert len(s.scalars(select(SchedulerRun.result).where(SchedulerRun.id == a.id)).one()) == 50_000
