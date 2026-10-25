"""Integración con Postgres + pgvector reales (embedder falso, $0).

Usa una base de datos aparte, estimator_test, que se crea desde cero y se migra
con Alembic: nunca toca el corpus de la base de datos de desarrollo. Solo corre
con RUN_DB_TESTS=1 y el Postgres de docker compose levantado:

    docker compose up -d postgres
    RUN_DB_TESTS=1 uv run pytest -m db -v
"""

import asyncio
import math
import os
import subprocess
import sys
from pathlib import Path

import asyncpg
import httpx
import pytest
import pytest_asyncio
from sqlalchemy import delete, func, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.config import get_settings
from app.db.models import EMBEDDING_DIMENSION, Chunk, Document
from app.db.repository import DocumentRepository, DuplicateSourcePath
from app.db.session import get_session
from app.embedding_pipeline import router as ingest_module
from app.embedding_pipeline import search as search_module
from app.main import app
from tests.pgvector_fakes import FakeEmbedder, ingest_payload, load_budget, unit_vector

pytestmark = [
    pytest.mark.db,
    pytest.mark.skipif(
        os.getenv("RUN_DB_TESTS") != "1",
        reason="Solo con RUN_DB_TESTS=1 y el Postgres de docker compose levantado",
    ),
]

ROOT = Path(__file__).resolve().parent.parent
TEST_DB = "estimator_test"


def _test_url() -> str:
    return make_url(get_settings().DATABASE_URL).set(database=TEST_DB).render_as_string(
        hide_password=False
    )


def _asyncpg_dsn(url: str) -> str:
    return make_url(url).set(drivername="postgresql").render_as_string(hide_password=False)


async def _recreate_database() -> None:
    admin = make_url(get_settings().DATABASE_URL).set(drivername="postgresql")
    conn = await asyncpg.connect(admin.render_as_string(hide_password=False))
    try:
        await conn.execute(f"DROP DATABASE IF EXISTS {TEST_DB} WITH (FORCE)")
        await conn.execute(f"CREATE DATABASE {TEST_DB}")
    finally:
        await conn.close()


def _alembic(*args: str) -> None:
    env = {**os.environ, "DATABASE_URL": _test_url()}
    subprocess.run(
        [sys.executable, "-m", "alembic", *args], cwd=ROOT, env=env, check=True,
        capture_output=True,
    )


async def _fetch(sql: str):
    conn = await asyncpg.connect(_asyncpg_dsn(_test_url()))
    try:
        return await conn.fetch(sql)
    finally:
        await conn.close()


@pytest.fixture(scope="module", autouse=True)
def migrated_database():
    """Base de datos nueva; se prueba upgrade → downgrade → upgrade de la migración."""
    asyncio.run(_recreate_database())
    _alembic("upgrade", "head")
    _alembic("downgrade", "base")
    tables = asyncio.run(_fetch("SELECT tablename FROM pg_tables WHERE schemaname = 'public'"))
    extensions = asyncio.run(_fetch("SELECT extname FROM pg_extension"))
    _alembic("upgrade", "head")
    return {
        "tables_after_downgrade": {row["tablename"] for row in tables},
        "extensions_after_downgrade": {row["extname"] for row in extensions},
    }


@pytest_asyncio.fixture
async def sessionmaker():
    # NullPool: cada test usa su propio event loop y no debe heredar conexiones.
    engine = create_async_engine(_test_url(), poolclass=NullPool)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        await session.execute(delete(Document))
        await session.commit()
    yield factory
    await engine.dispose()


@pytest_asyncio.fixture
async def client(sessionmaker, monkeypatch):
    async def test_session():
        async with sessionmaker() as session:
            yield session

    embedder = FakeEmbedder()
    app.dependency_overrides[get_session] = test_session
    monkeypatch.setattr(ingest_module, "get_cached_embedder", lambda: embedder)
    monkeypatch.setattr(search_module, "get_cached_embedder", lambda: embedder)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as http:
        yield http
    app.dependency_overrides.clear()


def test_downgrade_drops_tables_but_keeps_the_vector_extension(migrated_database):
    assert "documents" not in migrated_database["tables_after_downgrade"]
    assert "chunks" not in migrated_database["tables_after_downgrade"]
    assert "vector" in migrated_database["extensions_after_downgrade"]


@pytest.mark.asyncio
async def test_schema_has_vector_1536_unique_source_path_and_no_vector_index():
    [column] = await _fetch(
        "SELECT format_type(atttypid, atttypmod) AS type FROM pg_attribute "
        "WHERE attrelid = 'chunks'::regclass AND attname = 'embedding'"
    )
    assert column["type"] == f"vector({EMBEDDING_DIMENSION})"

    indexes = {
        row["indexname"]: row["indexdef"]
        for row in await _fetch("SELECT indexname, indexdef FROM pg_indexes WHERE schemaname = 'public'")
    }
    assert "UNIQUE" in indexes["ix_documents_source_path"]
    assert "gin" in indexes["ix_chunks_metadata_gin"]
    assert not any("hnsw" in d or "ivfflat" in d for d in indexes.values())


@pytest.mark.asyncio
async def test_ingest_persists_document_and_chunks_then_409_on_repeat(client, sessionmaker):
    budget = load_budget("BUD-2024-014")
    first = await client.post("/embeddings/ingest", json=ingest_payload())
    assert first.status_code == 200
    document_id = first.json()["document_id"]

    async with sessionmaker() as session:
        n_chunks = await session.scalar(
            select(func.count()).select_from(Chunk).where(Chunk.document_id == document_id)
        )
        sector = await session.scalar(
            text("SELECT metadata->>'sector' FROM documents WHERE id = :id"), {"id": document_id}
        )
    assert n_chunks == len(budget["components"]) == first.json()["chunks_created"]
    assert sector == budget["client_metadata"]["sector"]

    again = await client.post("/embeddings/ingest", json=ingest_payload())
    assert again.status_code == 409
    assert again.json() == {"detail": "Document already ingested", "document_id": document_id}


@pytest.mark.asyncio
async def test_unique_index_resolves_the_race_with_the_winner_id(sessionmaker):
    """Simula al perdedor de la carrera: guarda sin la comprobación previa."""
    source_path = "data/budgets/BUD-RACE.json"
    async with sessionmaker() as session:
        winner = Document(source_path=source_path, document_type="historical_budget")
        await DocumentRepository(session).save(winner)

    async with sessionmaker() as session:
        loser = Document(source_path=source_path, document_type="historical_budget")
        loser.chunks = [Chunk(chunk_type="budget_component", content="x", embedding=unit_vector(0))]
        with pytest.raises(DuplicateSourcePath) as excinfo:
            await DocumentRepository(session).save(loser)
    assert excinfo.value.document_id == winner.id

    async with sessionmaker() as session:
        orphan_chunks = await session.scalar(select(func.count()).select_from(Chunk))
    assert orphan_chunks == 0  # el rollback no dejó chunks del perdedor


@pytest.mark.asyncio
async def test_search_ranks_by_real_cosine_distance(client, sessionmaker):
    # El embedder falso devuelve unit_vector(0) para cualquier query.
    diagonal = [0.0] * EMBEDDING_DIMENSION
    diagonal[0] = diagonal[1] = 1 / math.sqrt(2)
    async with sessionmaker() as session:
        document = Document(source_path="tests/rank.json", document_type="historical_budget")
        document.chunks = [
            Chunk(chunk_type="budget_component", content="ortogonal", embedding=unit_vector(1)),
            Chunk(chunk_type="budget_component", content="identico", embedding=unit_vector(0)),
            Chunk(chunk_type="budget_component", content="a 45 grados", embedding=diagonal),
        ]
        await DocumentRepository(session).save(document)

    response = await client.post("/search", json={"query": "cualquier cosa", "k": 2})
    assert response.status_code == 200
    results = response.json()["results"]
    assert [r["content"] for r in results] == ["identico", "a 45 grados"]
    assert results[0]["distance"] == pytest.approx(0.0, abs=1e-6)
    assert results[1]["distance"] == pytest.approx(1 - 1 / math.sqrt(2), abs=1e-6)
    assert all(r["document_id"] == document.id for r in results)


@pytest.mark.asyncio
async def test_deleting_a_document_cascades_to_its_chunks(client, sessionmaker):
    document_id = (await client.post("/embeddings/ingest", json=ingest_payload())).json()[
        "document_id"
    ]
    async with sessionmaker() as session:
        await session.execute(delete(Document).where(Document.id == document_id))
        await session.commit()
        remaining = await session.scalar(select(func.count()).select_from(Chunk))
    assert remaining == 0
