"""SQLAlchemy engine/session management."""
from collections.abc import Iterator

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import get_settings


class Base(DeclarativeBase):
    pass


_engine: Engine | None = None
_SessionLocal: sessionmaker[Session] | None = None


def init_engine(url: str | None = None) -> Engine:
    """(Re)initialise the global engine. Tests pass an in-memory/temp URL."""
    global _engine, _SessionLocal
    url = url or get_settings().database_url
    kwargs: dict = {}
    if url.startswith("sqlite"):
        kwargs["connect_args"] = {"check_same_thread": False}
        if ":memory:" in url:
            from sqlalchemy.pool import StaticPool
            kwargs["poolclass"] = StaticPool
    if not url.startswith("sqlite"):
        kwargs["pool_pre_ping"] = True              # survive a restarted database container
    _engine = create_engine(url, **kwargs)
    if url.startswith("sqlite"):
        @event.listens_for(_engine, "connect")
        def _pragma(dbapi_conn, _):  # type: ignore[no-untyped-def]
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA journal_mode=WAL")
            cur.close()
    _SessionLocal = sessionmaker(_engine, expire_on_commit=False)
    from app.data import models  # noqa: F401  (register tables)
    if url.startswith("sqlite"):
        Base.metadata.create_all(_engine)            # zero-setup local use and tests
    else:
        migrate(_engine)                             # a server database is managed by Alembic migrations
    return _engine


def migrate(engine: Engine) -> None:
    """Bring a server database (PostgreSQL) up to the latest schema. Safe to run on every start."""
    from pathlib import Path

    from alembic.config import Config

    from alembic import command

    backend = Path(__file__).resolve().parents[2]
    cfg = Config(str(backend / "alembic.ini"))
    cfg.set_main_option("script_location", str(backend / "alembic"))
    with engine.begin() as conn:
        cfg.attributes["connection"] = conn
        command.upgrade(cfg, "head")


def get_session() -> Iterator[Session]:
    if _SessionLocal is None:
        init_engine()
    assert _SessionLocal is not None
    with _SessionLocal() as s:
        yield s
