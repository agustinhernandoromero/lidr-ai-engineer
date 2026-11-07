"""Cross-encoder reranker: fine ordering of the wide candidate set.

Vector search is good at finding candidates and mediocre at ordering them: each
text is squeezed into one vector without ever seeing the query. A cross-encoder
reads query and candidate together and scores the pair directly. It is accurate
but cannot be precomputed, so it only scores the few dozen candidates that vector
(or hybrid) search already retrieved. It reorders; it cannot rescue a document
that was not retrieved.
"""

from functools import lru_cache
from typing import Protocol

import structlog

from app.config import get_settings
from app.retrieval.types import RetrievedChunk

logger = structlog.get_logger(__name__)


class PairScorer(Protocol):
    """What the reranker needs from a model (a CrossEncoder satisfies it)."""

    def predict(self, sentences: list[tuple[str, str]]) -> list[float]: ...


class Reranker:
    """Scores (query, chunk) pairs jointly and keeps the best `top_k`."""

    def __init__(self, model_name: str | None = None, model: PairScorer | None = None) -> None:
        self.model_name = model_name or get_settings().RERANKER_MODEL
        if model is None:
            # Heavy import (PyTorch): only when a real model is needed, so importing
            # this module and the tests that inject a fake stay light.
            from sentence_transformers import CrossEncoder

            model = CrossEncoder(self.model_name)
        self._model = model
        logger.info("reranker_loaded", model=self.model_name)

    def rerank(
        self,
        query: str,
        candidates: list[RetrievedChunk],
        top_k: int,
    ) -> list[RetrievedChunk]:
        """Return the `top_k` candidates with the highest relevance to the query.

        Synchronous and CPU-bound: async callers must run it in a worker thread.
        """
        if not candidates:
            return []
        scores = self._model.predict([(query, chunk.content) for chunk in candidates])
        # sorted() is stable: equal scores keep the incoming order.
        ranked = sorted(zip(candidates, scores), key=lambda pair: float(pair[1]), reverse=True)
        logger.info(
            "rerank_completed",
            model=self.model_name,
            candidates_in=len(candidates),
            candidates_out=min(top_k, len(ranked)),
        )
        return [chunk for chunk, _ in ranked[:top_k]]


@lru_cache
def get_reranker() -> Reranker:
    """Shared reranker: loading the model takes seconds, so it happens once."""
    return Reranker()
