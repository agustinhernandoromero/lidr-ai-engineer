"""Retrieval pipeline: wide candidate search, then optional fine reranking.

    candidates (vector or hybrid, `pool` of them)  ->  reranker (optional)  ->  top_k

The four configurations of the session 10 exercise are the combinations of
`mode` ("vector" / "hybrid") and `rerank` (False / True). Every argument left
as None falls back to the setting of the same name, so the endpoint follows the
configuration while a measurement script can force each combination.
"""

import asyncio
import time

import structlog

from app.config import get_settings
from app.db.repository import DocumentRepository
from app.retrieval.candidates import hybrid_search, vector_search
from app.retrieval.reranker import Reranker, get_reranker
from app.retrieval.types import RetrievedChunk

logger = structlog.get_logger(__name__)


async def retrieve(
    repository: DocumentRepository,
    query_text: str,
    query_vector: list[float],
    *,
    mode: str | None = None,
    rerank: bool | None = None,
    pool: int | None = None,
    top_k: int | None = None,
    rrf_k: int | None = None,
    reranker: Reranker | None = None,
) -> list[RetrievedChunk]:
    """The `top_k` chunks for a query, with the chosen search mode and reranking."""
    settings = get_settings()
    mode = mode or settings.SEARCH_MODE
    rerank = settings.RERANKING_ENABLED if rerank is None else rerank
    pool = pool or settings.RETRIEVAL_CANDIDATE_POOL
    top_k = top_k or settings.RETRIEVAL_TOP_K
    rrf_k = rrf_k or settings.RRF_K

    if mode == "hybrid":
        candidates = await hybrid_search(repository, query_text, query_vector, pool, rrf_k)
    elif mode == "vector":
        candidates = await vector_search(repository, query_vector, pool)
    else:
        raise ValueError(f"unknown search mode: {mode!r}")

    if not rerank:
        results = candidates[:top_k]
        logger.info(
            "retrieval_completed",
            mode=mode,
            rerank=False,
            candidates=len(candidates),
            returned=len(results),
        )
        return results

    started = time.perf_counter()
    # Scoring is CPU work: a worker thread keeps the event loop free for other requests.
    results = await asyncio.to_thread(
        (reranker or get_reranker()).rerank, query_text, candidates, top_k
    )
    logger.info(
        "retrieval_completed",
        mode=mode,
        rerank=True,
        candidates=len(candidates),
        returned=len(results),
        rerank_ms=round((time.perf_counter() - started) * 1000, 1),
    )
    return results
