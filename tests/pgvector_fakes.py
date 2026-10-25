"""Dobles de la sesión 08: embedder y repositorio en memoria (sin red ni Postgres)."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from app.db.models import EMBEDDING_DIMENSION
from app.db.repository import DuplicateSourcePath
from app.embedding_pipeline.embedder import BaseEmbedder

BUDGETS_DIR = Path(__file__).resolve().parent.parent / "data" / "budgets"


def load_budget(name: str = "BUD-2024-014") -> dict:
    return json.loads((BUDGETS_DIR / f"{name}.json").read_text(encoding="utf-8"))


def ingest_payload(name: str = "BUD-2024-014", source_path: str | None = None) -> dict:
    return {
        "source_path": source_path or f"data/budgets/{name}.json",
        "document_type": "historical_budget",
        "content": load_budget(name),
    }


def unit_vector(index: int) -> list[float]:
    """Vector de norma 1 con un único componente distinto de cero."""
    vector = [0.0] * EMBEDDING_DIMENSION
    vector[index] = 1.0
    return vector


class FakeEmbedder(BaseEmbedder):
    """Hereda lotes y validación de dimensión de BaseEmbedder; solo falsea la llamada."""

    provider = "fake"
    model = "fake-embedding"
    usd_per_mtok = 0.0

    def __init__(self, fail: bool = False, dimension: int = EMBEDDING_DIMENSION) -> None:
        self.fail = fail
        self.dimension = dimension
        self.calls: list[tuple[list[str], str]] = []

    def _embed_batch(self, texts: list[str], task: str) -> list[list[float]]:
        self.calls.append((texts, task))
        if self.fail:
            raise RuntimeError("proveedor de embeddings caído")
        vector = [0.0] * self.dimension
        vector[0] = 1.0
        return [list(vector) for _ in texts]

    def _is_retryable(self, exc: Exception) -> bool:
        return False


class FakeRepository:
    """Sustituto de DocumentRepository.

    - existing: source_path → id ya ingestado (el 409 del paso 1).
    - race_winner_id: save() pierde la carrera contra otra petición (el 409 del UNIQUE).
    - rows: lo que devuelve nearest_chunks, ya ordenado.
    """

    def __init__(
        self,
        existing: dict[str, int] | None = None,
        race_winner_id: int | None = None,
        rows: list[SimpleNamespace] | None = None,
    ) -> None:
        self.existing = dict(existing or {})
        self.race_winner_id = race_winner_id
        self.rows = list(rows or [])
        self.saved = []
        self.searches: list[tuple[list[float], int]] = []

    async def find_document_id(self, source_path: str) -> int | None:
        return self.existing.get(source_path)

    async def save(self, document) -> None:
        if self.race_winner_id is not None:
            raise DuplicateSourcePath(self.race_winner_id)
        document.id = 100 + len(self.saved)
        self.saved.append(document)

    async def nearest_chunks(self, query_vector: list[float], k: int) -> list[SimpleNamespace]:
        self.searches.append((query_vector, k))
        return self.rows[:k]


def search_row(chunk_id: int, distance: float, document_id: int = 1) -> SimpleNamespace:
    """Fila con los mismos atributos que devuelve DocumentRepository.nearest_chunks."""
    return SimpleNamespace(
        id=chunk_id,
        document_id=document_id,
        chunk_type="budget_component",
        content=f"chunk {chunk_id}",
        metadata_={"component_id": f"C-{chunk_id}", "sector": "finance"},
        distance=distance,
    )
