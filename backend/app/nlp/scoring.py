"""Scorer interface shared by FinBERT and VADER."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class Probs:
    pos: float
    neg: float
    neu: float

    @property
    def score(self) -> float:
        """Signed score in [-1, 1]: P(positive) - P(negative)."""
        return self.pos - self.neg


class Scorer(Protocol):
    name: str

    def score(self, texts: list[str]) -> list[Probs]: ...
