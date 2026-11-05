"""Session 10 test doubles: in-memory repository with both search branches."""

from types import SimpleNamespace

from app.retrieval.types import RetrievedChunk


def lexical_row(chunk_id: int, rank: float, document_id: int = 1) -> SimpleNamespace:
    """Row shaped like DocumentRepository.lexical_chunks (`rank`, no `distance`)."""
    return SimpleNamespace(
        id=chunk_id,
        document_id=document_id,
        chunk_type="budget_component",
        content=f"chunk {chunk_id}",
        metadata_={"component_id": f"C-{chunk_id}"},
        rank=rank,
    )


class FakeBranchesRepository:
    """Stands in for DocumentRepository: returns canned rows and records the calls."""

    def __init__(self, vector_rows=(), lexical_rows=()):
        self.vector_rows = list(vector_rows)
        self.lexical_rows = list(lexical_rows)
        self.calls: list[tuple] = []

    async def nearest_chunks(self, query_vector, k):
        self.calls.append(("vector", k))
        return self.vector_rows[:k]

    async def lexical_chunks(self, query_text, k):
        self.calls.append(("lexical", query_text, k))
        return self.lexical_rows[:k]


def ids(chunks: list[RetrievedChunk]) -> list[int]:
    return [chunk.id for chunk in chunks]
