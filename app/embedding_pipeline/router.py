"""Router FastAPI del pipeline de embeddings: POST /embeddings/ingest.

Cada petición trae un presupuesto; se trocea, se embebe en un único lote y se
persiste como un document con sus chunks en una sola transacción.
"""

import asyncio
import time
from functools import lru_cache

import structlog
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import JSONResponse

from app.db.models import EMBEDDING_DIMENSION, Chunk, Document
from app.db.repository import DocumentRepository, DuplicateSourcePath, get_repository
from app.embedding_pipeline.chunker import JSONStructuralChunker
from app.embedding_pipeline.embedder import BaseEmbedder, get_embedder
from app.embedding_pipeline.schemas import Budget, IngestConflict, IngestRequest, IngestResponse

logger = structlog.get_logger(__name__)

router = APIRouter(tags=["Embeddings"])

CHUNK_TYPE_COMPONENT = "budget_component"


@lru_cache
def get_chunker() -> JSONStructuralChunker:
    """Chunker compartido (carga el tokenizador una sola vez)."""
    return JSONStructuralChunker()


@lru_cache
def get_cached_embedder() -> BaseEmbedder:
    """Embedder compartido del proveedor configurado en EMBEDDING_PROVIDER."""
    return get_embedder()


def _conflict(document_id: int) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_409_CONFLICT,
        content=IngestConflict(document_id=document_id).model_dump(),
    )


def _document_metadata(budget: Budget) -> dict:
    """Metadata del presupuesto completo; los chunks no la duplican."""
    return {
        "budget_id": budget.budget_id,
        "client_name": budget.client_metadata.name,
        "sector": budget.client_metadata.sector,
        "country": budget.client_metadata.country,
        "main_technology": budget.main_technology,
        "year": budget.year,
        "total_estimated_hours": budget.total_estimated_hours,
        "components": len(budget.components),
    }


@router.post(
    "/ingest",
    response_model=IngestResponse,
    status_code=status.HTTP_200_OK,
    responses={status.HTTP_409_CONFLICT: {"model": IngestConflict}},
    summary="Trocear, vectorizar y persistir un presupuesto histórico",
    description=(
        "Parte el presupuesto en un chunk por componente, genera los embeddings en un único "
        "lote y guarda el documento y sus chunks en una sola transacción. Devuelve 409 si el "
        "source_path ya estaba ingestado."
    ),
)
async def ingest_budget(
    payload: IngestRequest,
    repository: DocumentRepository = Depends(get_repository),
    chunker: JSONStructuralChunker = Depends(get_chunker),
) -> IngestResponse | JSONResponse:
    started = time.perf_counter()

    # 1. Duplicado: se responde antes de gastar llamadas al embedder.
    existing_id = await repository.find_document_id(payload.source_path)
    if existing_id is not None:
        return _conflict(existing_id)

    # 2. Chunking y embeddings, fuera de la transacción: la llamada a la API
    # no retiene una conexión de Postgres. Los SDK bloquean, así que van en un hilo.
    budget = payload.content
    try:
        embedder = get_cached_embedder()
        chunks = chunker.chunk([budget])
        embedded = await asyncio.to_thread(embedder.embed_many, chunks, "document")
    except Exception:  # noqa: BLE001
        # Detalle completo solo en el log; el cliente lo correlaciona con X-Request-ID.
        logger.exception("embeddings_ingest_failed", source_path=payload.source_path)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error generando los embeddings. Consulta los logs con el X-Request-ID de la respuesta.",
        )

    # 3. Una sola transacción: el documento y todos sus chunks, o nada.
    tech_stacks = {component.component_id: component.tech_stack for component in budget.components}
    document = Document(
        source_path=payload.source_path,
        document_type=payload.document_type,
        metadata_=_document_metadata(budget),
    )
    document.chunks = [
        Chunk(
            chunk_type=CHUNK_TYPE_COMPONENT,
            content=chunk.text,
            embedding=chunk.embedding,
            metadata_={**chunk.metadata, "tech_stack": tech_stacks[chunk.metadata["component_id"]]},
        )
        for chunk in embedded
    ]
    try:
        await repository.save(document)
    except DuplicateSourcePath as exc:
        # Otra petición con el mismo source_path ganó la carrera entre la
        # comprobación del paso 1 y el INSERT; se responde igual que allí.
        return _conflict(exc.document_id)

    response = IngestResponse(
        document_id=document.id,
        chunks_created=len(document.chunks),
        embedding_dimension=EMBEDDING_DIMENSION,
        ingestion_time_ms=round((time.perf_counter() - started) * 1000),
    )
    logger.info(
        "embeddings_ingest",
        source_path=payload.source_path,
        total_tokens=sum(chunk.token_count for chunk in embedded),
        embedding_model=embedder.model,
        **response.model_dump(),
    )
    return response
