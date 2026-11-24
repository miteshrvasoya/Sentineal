"""Copy an existing SQLite database (default data/quantlens.db) into the PostgreSQL database named by DATABASE_URL.

    make db-up                       # start PostgreSQL in Docker
    # put DATABASE_URL=postgresql+psycopg://... in .env
    make db-import                   # copies prices, news, runs, everything

Refuses to run if the target already has data, unless --replace is given (which empties the target tables first).
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import create_engine, func, select, text  # noqa: E402

from app.config import ROOT, get_settings  # noqa: E402
from app.data import db  # noqa: E402
from app.data.db import Base  # noqa: E402

CHUNK = 5000
SKIP = {"alembic_version"}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", default=str(ROOT / "data" / "quantlens.db"), help="path to the SQLite file")
    ap.add_argument("--replace", action="store_true", help="empty the target tables first")
    a = ap.parse_args()
    url = get_settings().database_url
    if url.startswith("sqlite"):
        print("DATABASE_URL points at SQLite. Set it to your PostgreSQL URL in .env first.")
        return 1
    if not Path(a.source).exists():
        print(f"No SQLite file at {a.source}")
        return 1
    target = db.init_engine(url)                                       # also applies the migrations
    source = create_engine(f"sqlite:///{a.source}")
    tables = [t for t in Base.metadata.sorted_tables if t.name not in SKIP]
    with target.begin() as conn:
        busy = [t.name for t in tables if conn.scalar(select(func.count()).select_from(t))]
        if busy and not a.replace:
            print(f"Target already has data in: {', '.join(busy)}. Use --replace to overwrite.")
            return 1
        for t in reversed(tables):
            conn.execute(t.delete())
    total = 0
    with source.connect() as src, target.begin() as dst:
        have = set(source.dialect.get_table_names(src))
        for t in tables:
            if t.name not in have:
                continue
            n = 0
            cols = [c.name for c in t.columns]
            res = src.execute(select(*[t.c[c] for c in cols]).execution_options(stream_results=True))
            while rows := res.fetchmany(CHUNK):
                dst.execute(t.insert(), [dict(zip(cols, r, strict=True)) for r in rows])
                n += len(rows)
            for c in t.primary_key.columns:                             # keep auto-increment ids moving forward
                seq = dst.scalar(text("SELECT pg_get_serial_sequence(:t, :c)"), {"t": t.name, "c": c.name})
                if seq:
                    dst.execute(text(f"SELECT setval(:s, COALESCE((SELECT MAX({c.name}) FROM {t.name}), 1))"), {"s": seq})
            print(f"{t.name:24s} {n:>9,d} rows")
            total += n
    print(f"Done: {total:,d} rows copied.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
