"""Pick the best available scorer once: FinBERT if it can load, else VADER."""
from __future__ import annotations

import logging
import os

from app.nlp.scoring import Scorer

log = logging.getLogger("quantlens.nlp")
_scorer: Scorer | None = None


def get_scorer() -> Scorer:
    global _scorer
    if _scorer is None:
        if os.environ.get("QUANTLENS_DISABLE_FINBERT") != "1":
            try:
                from app.nlp.finbert import FinBertScorer

                _scorer = FinBertScorer()
                log.info("using FinBERT")
            except Exception as e:  # noqa: BLE001 - missing extra, no network, bad weights
                log.warning("FinBERT unavailable (%s: %s); falling back to VADER", type(e).__name__, str(e)[:120])
        if _scorer is None:
            from app.nlp.vader import VaderScorer

            _scorer = VaderScorer()
    return _scorer


def set_scorer(s: Scorer | None) -> None:
    """Test hook."""
    global _scorer
    _scorer = s
