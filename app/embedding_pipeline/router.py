"""Router FastAPI del pipeline de embeddings: POST /embeddings/ingest.

Los vectores se generan en memoria y se devuelven por HTTP; la persistencia
en una base de datos vectorial llega en la sesión 08.
"""

from functools import lru_cache

import structlog
from fastapi import APIRouter, Depends, HTTPException, status

from app.embedding_pipeline.chunker import JSONStructuralChunker
from app.embedding_pipeline.embedder import BaseEmbedder, get_embedder
from app.embedding_pipeline.schemas import IngestRequest, IngestResponse, IngestStats

logger = structlog.get_logger(__name__)

router = APIRouter(tags=["Embeddings"])


@lru_cache
def get_chunker() -> JSONStructuralChunker:
    """Chunker compartido (carga el tokenizador una sola vez)."""
    return JSONStructuralChunker()


@lru_cache
def get_cached_embedder() -> BaseEmbedder:
    """Embedder compartido del proveedor configurado en EMBEDDING_PROVIDER."""
    return get_embedder()


@router.post(
    "/ingest",
    response_model=IngestResponse,
    status_code=status.HTTP_200_OK,
    summary="Trocear y vectorizar presupuestos históricos",
    description=(
        "Parte cada presupuesto en un chunk por componente (con la cabecera del presupuesto "
        "padre), genera sus embeddings en lotes y devuelve los chunks vectorizados con "
        "estadísticas de tokens y coste estimado. No persiste nada."
    ),
)
def ingest_budgets(
    payload: IngestRequest,
    chunker: JSONStructuralChunker = Depends(get_chunker),
) -> IngestResponse:
    # Endpoint síncrono a propósito: los SDK de embeddings bloquean, y FastAPI
    # ejecuta los endpoints def en un hilo aparte sin parar el event loop.
    try:
        embedder = get_cached_embedder()
        chunks = chunker.chunk(payload.budgets)
        embedded = embedder.embed_many(chunks)
    except Exception:  # noqa: BLE001
        # Detalle completo solo en el log; el cliente recibe un mensaje genérico
        # y lo correlaciona con la cabecera X-Request-ID.
        logger.exception("embeddings_ingest_failed", budgets=len(payload.budgets))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error generando los embeddings. Consulta los logs con el X-Request-ID de la respuesta.",
        )

    total_tokens = sum(chunk.token_count for chunk in embedded)
    stats = IngestStats(
        total_budgets=len(payload.budgets),
        total_chunks=len(embedded),
        total_tokens=total_tokens,
        estimated_cost_usd=embedder.estimate_cost_usd(total_tokens),
        embedding_model=embedder.model,
    )
    logger.info("embeddings_ingest", **stats.model_dump())
    return IngestResponse(chunks=embedded, stats=stats)
