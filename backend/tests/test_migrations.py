"""The Alembic migrations must produce exactly the schema the ORM models describe (fails if someone adds a column but no migration)."""
from pathlib import Path

from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import create_engine, inspect

from alembic import command
from app.data import models  # noqa: F401
from app.data.db import Base

BACKEND = Path(__file__).resolve().parents[1]


def cfg(url: str) -> Config:
    c = Config(str(BACKEND / "alembic.ini"))
    c.set_main_option("script_location", str(BACKEND / "alembic"))
    c.set_main_option("sqlalchemy.url", url)
    return c


def test_migrations_match_models_and_are_reversible(tmp_path):
    url = f"sqlite:///{tmp_path / 'm.db'}"
    command.upgrade(cfg(url), "head")
    eng = create_engine(url)
    with eng.connect() as conn:
        diff = compare_metadata(MigrationContext.configure(conn), Base.metadata)
    assert diff == [], diff
    assert {"prices", "scheduler_runs", "model_runs", "llm_usage"} <= set(inspect(eng).get_table_names())
    command.downgrade(cfg(url), "base")
    assert set(inspect(create_engine(url)).get_table_names()) <= {"alembic_version"}
