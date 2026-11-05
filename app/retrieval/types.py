"""Common result type for every retrieval strategy."""

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class RetrievedChunk:
    """A chunk returned by retrieval, whichever branch found it.

    The vector branch fills `distance` (cosine, 0 = same direction) and the
    lexical branch fills `lexical_rank` (ts_rank, higher = better). A chunk that
    both branches found carries both; a chunk found by one carries None in the
    other. Fusion and reranking use only the order, never these raw scores.
    """

    id: int
    document_id: int
    chunk_type: str
    content: str
    metadata: dict[str, Any]
    distance: float | None = None
    lexical_rank: float | None = None

    @classmethod
    def from_row(cls, row: Any) -> "RetrievedChunk":
        """Build from a DocumentRepository row (nearest_chunks or lexical_chunks)."""
        return cls(
            id=row.id,
            document_id=row.document_id,
            chunk_type=row.chunk_type,
            content=row.content,
            metadata=row.metadata_,
            distance=getattr(row, "distance", None),
            lexical_rank=getattr(row, "rank", None),
        )
