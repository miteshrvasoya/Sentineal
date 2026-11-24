"""ProsusAI/finbert run locally (free, no rate limits). Requires the optional `nlp` extra
(`uv sync --extra nlp`) and a one-time weight download from Hugging Face."""
from __future__ import annotations

import logging
import math
from collections.abc import Callable

from app.nlp.scoring import Probs

log = logging.getLogger("quantlens.finbert")
MODEL = "ProsusAI/finbert"


class FinBertScorer:
    name = "finbert"

    def __init__(self, model_name: str = MODEL, predict: Callable[[list[str]], list[dict[str, float]]] | None = None,
                 batch: int = 16) -> None:
        self.model_name, self.batch = model_name, batch
        self._predict = predict or self._load()

    def _load(self) -> Callable[[list[str]], list[dict[str, float]]]:
        import torch  # noqa: PLC0415  (optional heavy dependency)
        from transformers import AutoModelForSequenceClassification, AutoTokenizer  # noqa: PLC0415

        tok = AutoTokenizer.from_pretrained(self.model_name)
        model = AutoModelForSequenceClassification.from_pretrained(self.model_name).eval()
        id2label = {int(k): v.lower() for k, v in model.config.id2label.items()}   # never assume label order

        def predict(texts: list[str]) -> list[dict[str, float]]:
            enc = tok(texts, padding=True, truncation=True, max_length=256, return_tensors="pt")
            with torch.no_grad():
                probs = torch.softmax(model(**enc).logits, dim=-1).tolist()
            return [{id2label[i]: p for i, p in enumerate(row)} for row in probs]

        return predict

    def score(self, texts: list[str]) -> list[Probs]:
        out: list[Probs] = []
        for i in range(0, len(texts), self.batch):
            for d in self._predict(texts[i:i + self.batch]):
                pos, neg, neu = d.get("positive", 0.0), d.get("negative", 0.0), d.get("neutral", 0.0)
                if not math.isclose(pos + neg + neu, 1.0, abs_tol=1e-3):
                    raise ValueError(f"finbert probabilities do not sum to 1: {d}")
                out.append(Probs(pos, neg, neu))
        return out
