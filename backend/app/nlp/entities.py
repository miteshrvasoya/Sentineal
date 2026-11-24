"""Ticker resolution from an alias table (data/aliases.csv) and simple term extraction."""
from __future__ import annotations

import csv
import re
from collections import Counter
from functools import lru_cache
from pathlib import Path

from app.config import ROOT

ALIASES_CSV = ROOT / "data" / "aliases.csv"
STOP = set("""a an and are as at be but by for from has have in is it its of on or that the this to was were will with
after over new says said not more than into out up about their they we you his her he she who what when how why also
stock stocks share shares market markets india indian rs crore lakh per cent pct today news report reports""".split())


class AliasResolver:
    """Names match case-insensitively; aliases of <=3 characters (TCS, ITC, SBI, L&T, HUL) must match
    exactly in upper case to avoid hits on ordinary words. Matches need non-alphanumeric boundaries."""

    def __init__(self, path: Path = ALIASES_CSV) -> None:
        self._rules: list[tuple[str, re.Pattern[str]]] = []
        with open(path, newline="") as f:
            for row in csv.DictReader(f):
                sym = row["symbol"].strip().upper()
                names = {sym, *[a.strip() for a in row["aliases"].split("|") if a.strip()]}
                for a in names:
                    flags = 0 if (len(a) <= 3 or a.upper() == sym) else re.IGNORECASE
                    self._rules.append((sym, re.compile(rf"(?<![A-Za-z0-9]){re.escape(a)}(?![A-Za-z0-9])", flags)))

    def resolve(self, text: str, extra: set[str] | None = None) -> set[str]:
        found = {sym for sym, rx in self._rules if rx.search(text)}
        return found | {e.upper() for e in (extra or set())}

    def known(self) -> set[str]:
        return {s for s, _ in self._rules}


@lru_cache
def get_resolver() -> AliasResolver:
    return AliasResolver()


def top_terms(texts: list[str], n: int = 25) -> list[tuple[str, int]]:
    c: Counter[str] = Counter()
    for t in texts:
        for w in re.findall(r"[A-Za-z][A-Za-z&'-]{2,}", t.lower()):
            if w not in STOP:
                c[w] += 1
    return c.most_common(n)
