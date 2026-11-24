"""VADER: fast, offline, general-purpose lexicon fallback (not finance-specific)."""
from __future__ import annotations

from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer

from app.nlp.scoring import Probs


class VaderScorer:
    name = "vader"

    def __init__(self) -> None:
        self._a = SentimentIntensityAnalyzer()

    def score(self, texts: list[str]) -> list[Probs]:
        out = []
        for t in texts:
            s = self._a.polarity_scores(t)
            # Use the compound score as the signed value; split probability mass by the pos/neg shares.
            comp = s["compound"]
            pos, neg = max(comp, 0.0), max(-comp, 0.0)
            out.append(Probs(pos=pos, neg=neg, neu=1.0 - pos - neg))
        return out
