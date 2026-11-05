"""Acceso a datos de documents y chunks.

Los routers no escriben SQL: piden al repositorio lo que necesitan. Así los
tests sustituyen el repositorio por uno en memoria (dependency_overrides) y
prueban el HTTP sin base de datos.
"""

from typing import Any

from fastapi import Depends
from sqlalchemy import Row, Text, cast, func, literal_column, select
from sqlalchemy.dialects.postgresql import TSQUERY
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Chunk, Document
from app.db.session import get_session


class DuplicateSourcePath(Exception):
    """El source_path ya existe; lleva el id del documento que lo ocupa."""

    def __init__(self, document_id: int) -> None:
        super().__init__(f"source_path ya ingestado (document_id={document_id})")
        self.document_id = document_id


class DocumentRepository:
    """Consultas y escrituras sobre documents/chunks con una sesión por petición."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def find_document_id(self, source_path: str) -> int | None:
        return await self._session.scalar(
            select(Document.id).where(Document.source_path == source_path)
        )

    async def save(self, document: Document) -> None:
        """Guarda el documento y sus chunks en una sola transacción.

        Si otra petición con el mismo source_path gana la carrera entre la
        comprobación previa y este INSERT, el índice UNIQUE lo detecta y se
        lanza DuplicateSourcePath con el id del documento que ya existe.
        """
        self._session.add(document)
        try:
            await self._session.commit()
        except IntegrityError:
            await self._session.rollback()
            existing_id = await self.find_document_id(document.source_path)
            if existing_id is None:
                raise
            raise DuplicateSourcePath(existing_id) from None

    async def nearest_chunks(self, query_vector: list[float], k: int) -> list[Row[Any]]:
        """Los k chunks más cercanos por distancia coseno (operador <=>).

        El mismo operador en el ORDER BY que en el futuro índice HNSW con
        vector_cosine_ops: si no coinciden, Postgres ignora el índice.
        """
        distance = Chunk.embedding.cosine_distance(query_vector)
        stmt = (
            select(
                Chunk.id,
                Chunk.document_id,
                Chunk.chunk_type,
                Chunk.content,
                Chunk.metadata_,
                distance.label("distance"),
            )
            .order_by(distance)
            .limit(k)
        )
        return list((await self._session.execute(stmt)).all())

    async def lexical_chunks(self, query_text: str, k: int) -> list[Row[Any]]:
        """The k chunks that best match the query words (full-text search).

        Uses the generated content_tsv column (migration 0002). The 'spanish'
        configuration must match the one the column was built with. Rows come
        back ordered by ts_rank; same columns as nearest_chunks, with `rank`
        instead of `distance`.

        Query terms are combined with OR, not AND. websearch_to_tsquery joins
        them with AND, so a long project description (many terms) would almost
        never find a chunk containing all of them and return nothing. With OR,
        a chunk matches if it has any term and ts_rank puts the ones with more
        matches first. plainto_tsquery tolerates free text (it ignores syntax)
        and applies the same stemming and stopwords.
        """
        and_query = func.plainto_tsquery(literal_column("'spanish'"), query_text)
        tsquery = func.replace(cast(and_query, Text), "&", "|").cast(TSQUERY)
        rank = func.ts_rank(Chunk.content_tsv, tsquery)
        stmt = (
            select(
                Chunk.id,
                Chunk.document_id,
                Chunk.chunk_type,
                Chunk.content,
                Chunk.metadata_,
                rank.label("rank"),
            )
            .where(Chunk.content_tsv.bool_op("@@")(tsquery))
            # Chunk.id breaks ties so the ranking is deterministic.
            .order_by(rank.desc(), Chunk.id)
            .limit(k)
        )
        return list((await self._session.execute(stmt)).all())


def get_repository(session: AsyncSession = Depends(get_session)) -> DocumentRepository:
    """Dependencia FastAPI: repositorio sobre la sesión de la petición."""
    return DocumentRepository(session)
