"""Router FastAPI de búsqueda semántica: POST /search.

Embebe la query con el mismo modelo que la ingesta y devuelve los k chunks más
cercanos por distancia coseno (operador <=>). Sin índice vectorial: Postgres
hace sequential scan, la línea base contra la que se medirá HNSW.
"""

import asyncio
import time

import structlog
from fastapi import APIRouter, Depends, HTTPException, status

from app.db.repository import DocumentRepository, get_repository
from app.embedding_pipeline.router import get_cached_embedder
from app.embedding_pipeline.schemas import SearchRequest, SearchResponse, SearchResult

logger = structlog.get_logger(__name__)

router = APIRouter(tags=["Search"])


@router.post(
    "",
    response_model=SearchResponse,
    summary="Búsqueda semántica sobre los presupuestos históricos",
    description=(
        "Devuelve los k chunks más cercanos a la query por distancia coseno "
        "(0 = misma dirección, 2 = opuestos)."
    ),
)
async def search(
    payload: SearchRequest,
    repository: DocumentRepository = Depends(get_repository),
) -> SearchResponse:
    started = time.perf_counter()
    try:
        embedder = get_cached_embedder()
        query_vector = await asyncio.to_thread(embedder.embed_one, payload.query, "query")
    except Exception:  # noqa: BLE001
        logger.exception("search_embedding_failed")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error generando el embedding de la query. Consulta los logs con el X-Request-ID de la respuesta.",
        )
    embedded_at = time.perf_counter()

    rows = await repository.nearest_chunks(query_vector, payload.k)
    finished = time.perf_counter()

    results = [
        SearchResult(
            chunk_id=row.id,
            document_id=row.document_id,
            chunk_type=row.chunk_type,
            content=row.content,
            distance=row.distance,
            metadata=row.metadata_,
        )
        for row in rows
    ]
    response = SearchResponse(
        query=payload.query,
        k=payload.k,
        search_time_ms=round((finished - started) * 1000),
        results=results,
    )
    # Por separado: el índice vectorial solo acelerará db_ms.
    logger.info(
        "semantic_search",
        k=payload.k,
        results=len(results),
        embed_ms=round((embedded_at - started) * 1000, 1),
        db_ms=round((finished - embedded_at) * 1000, 1),
        search_time_ms=response.search_time_ms,
    )
    return response
