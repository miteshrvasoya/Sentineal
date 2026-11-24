"""Result cache: key = sha256(task | prompt id+version | model | content hash)."""
from __future__ import annotations

import hashlib
import time
from collections.abc import Callable

from app.data.models import LLMCache


def content_hash(system: str, user: str) -> str:
    return hashlib.sha256(f"{system}\n\x00\n{user}".encode()).hexdigest()


def cache_key(task: str, prompt_id: str, prompt_version: int, model: str, chash: str) -> str:
    return hashlib.sha256(f"{task}|{prompt_id}.v{prompt_version}|{model}|{chash}".encode()).hexdigest()


class LLMResultCache:
    def __init__(self, db_factory: Callable) -> None:  # type: ignore[type-arg]
        self.db_factory = db_factory

    def get(self, key: str) -> str | None:
        with self.db_factory() as db:
            row = db.get(LLMCache, key)
            return row.payload if row else None

    def put(self, key: str, payload: str, model: str) -> None:
        with self.db_factory() as db:
            db.merge(LLMCache(key=key, payload=payload, model=model, created=int(time.time())))
            db.commit()
