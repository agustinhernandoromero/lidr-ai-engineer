"""Chunker estructural: un componente del presupuesto = un chunk.

Cada chunk lleva delante una cabecera con el contexto del presupuesto padre
(contextual chunk header): sin ella, un "Authentication backend" de banca y
otro de una clínica serían casi indistinguibles.
"""

from abc import ABC, abstractmethod
from typing import Any

import structlog
import tiktoken

from app.embedding_pipeline.schemas import Budget, BudgetComponent, Chunk

logger = structlog.get_logger(__name__)

# Tokenizador de text-embedding-3-small (cl100k_base). Con otro proveedor de
# embeddings el recuento es aproximado, pero sigue sirviendo para detectar
# chunks anormalmente grandes.
TOKENIZER_MODEL = "text-embedding-3-small"

# Por encima de este tamaño se avisa en el log; el chunk no se parte. En el
# sample, la mediana es ~85 tokens y el p90 ~95: 200 marca solo lo atípico.
LARGE_CHUNK_TOKENS = 200


class Chunker(ABC):
    """Interfaz común de las estrategias de chunking del pipeline.

    Cada tipo de documento tiene su chunker (presupuestos JSON aquí; otros,
    como las transcripciones, se añaden sobre esta misma base).
    """

    @abstractmethod
    def chunk(self, documents: list[Any]) -> list[Chunk]:
        """Parte los documentos en chunks listos para embeber."""


class JSONStructuralChunker(Chunker):
    """Convierte presupuestos JSON en chunks respetando su estructura."""

    def __init__(self) -> None:
        self._encoding = tiktoken.encoding_for_model(TOKENIZER_MODEL)

    def chunk(self, budgets: list[Budget]) -> list[Chunk]:
        """Un chunk por componente, en el mismo orden que la entrada."""
        chunks: list[Chunk] = []
        for budget in budgets:
            budget_chunks = [self._build_chunk(budget, component) for component in budget.components]
            logger.info(
                "embedding_budget_chunked",
                budget_id=budget.budget_id,
                chunks=len(budget_chunks),
                tokens=sum(chunk.token_count for chunk in budget_chunks),
            )
            chunks.extend(budget_chunks)
        return chunks

    def _build_chunk(self, budget: Budget, component: BudgetComponent) -> Chunk:
        text = _render_text(budget, component)
        token_count = len(self._encoding.encode(text))
        chunk_id = f"{budget.budget_id}::{component.component_id}"

        if token_count > LARGE_CHUNK_TOKENS:
            logger.warning(
                "embedding_chunk_large",
                chunk_id=chunk_id,
                token_count=token_count,
                threshold=LARGE_CHUNK_TOKENS,
            )

        return Chunk(
            chunk_id=chunk_id,
            text=text,
            metadata={
                "budget_id": budget.budget_id,
                "component_id": component.component_id,
                "client_sector": budget.client_metadata.sector,
                "main_technology": budget.main_technology,
                "year": budget.year,
                "complexity": component.complexity,
                "estimated_hours": component.estimated_hours,
            },
            token_count=token_count,
        )


def _render_text(budget: Budget, component: BudgetComponent) -> str:
    """Texto que se embebe: cabecera del presupuesto + detalle del componente.

    El nombre del cliente y las dependencias (ids como AUTH-001) se dejan fuera:
    no aportan significado y solo meterían ruido en el vector.
    """
    return (
        f"[Project: {budget.project_summary}]\n"
        f"[Client sector: {budget.client_metadata.sector} | Year: {budget.year} "
        f"| Main tech: {budget.main_technology}]\n"
        "\n"
        f"Component: {component.name}\n"
        f"Description: {component.description}\n"
        f"Tech stack: {', '.join(component.tech_stack)}\n"
        f"Complexity: {component.complexity}\n"
        f"Estimated hours: {component.estimated_hours}"
    )
