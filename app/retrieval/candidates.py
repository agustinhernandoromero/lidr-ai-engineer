"""Candidate retrieval: the wide net that feeds the rest of the pipeline.

Two strategies with the same contract (a query in, a ranked list of chunks out),
so the caller switches between them with a setting:

- vector_search: semantic only (the session 08 behavior).
- hybrid_search: semantic + keyword search, merged with Reciprocal Rank Fusion.
"""

import dataclasses

import structlog

from app.db.repository import DocumentRepository
from app.retrieval.fusion import RRF_SMOOTHING_K, reciprocal_rank_fusion
from app.retrieval.types import RetrievedChunk

logger = structlog.get_logger(__name__)


async def vector_search(
    repository: DocumentRepository,
    query_vector: list[float],
    limit: int,
) -> list[RetrievedChunk]:
    """The `limit` chunks closest to the query vector."""
    rows = await repository.nearest_chunks(query_vector, limit)
    return [RetrievedChunk.from_row(row) for row in rows]


async def hybrid_search(
    repository: DocumentRepository,
    query_text: str,
    query_vector: list[float],
    limit: int,
    rrf_k: int = RRF_SMOOTHING_K,
) -> list[RetrievedChunk]:
    """Semantic and keyword search, merged into a single ranking with RRF.

    The two queries run one after the other: they share the request's database
    session, and an AsyncSession cannot run two operations at once.
    """
    vector_chunks = await vector_search(repository, query_vector, limit)
    lexical_rows = await repository.lexical_chunks(query_text, limit)
    lexical_chunks = [RetrievedChunk.from_row(row) for row in lexical_rows]

    fused_ids = reciprocal_rank_fusion(
        [[chunk.id for chunk in vector_chunks], [chunk.id for chunk in lexical_chunks]],
        k=rrf_k,
    )

    # A chunk found by both branches keeps both of its scores.
    by_id = {chunk.id: chunk for chunk in lexical_chunks}
    for chunk in vector_chunks:
        found_lexically = by_id.get(chunk.id)
        by_id[chunk.id] = (
            dataclasses.replace(chunk, lexical_rank=found_lexically.lexical_rank)
            if found_lexically
            else chunk
        )

    logger.info(
        "hybrid_search",
        vector_hits=len(vector_chunks),
        lexical_hits=len(lexical_chunks),
        in_both=len(vector_chunks) + len(lexical_chunks) - len(fused_ids),
        fused=len(fused_ids),
        returned=min(limit, len(fused_ids)),
    )
    return [by_id[chunk_id] for chunk_id in fused_ids[:limit]]
