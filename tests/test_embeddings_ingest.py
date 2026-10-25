"""POST /embeddings/ingest: persistencia, 409 y errores (embedder y repositorio falsos, $0)."""

import httpx
import pytest
import pytest_asyncio

from app.db.models import EMBEDDING_DIMENSION
from app.db.repository import get_repository
from app.embedding_pipeline import router as ingest_module
from app.main import app
from tests.pgvector_fakes import (
    FakeEmbedder,
    FakeRepository,
    ingest_payload,
    load_budget,
)

BUDGET = load_budget("BUD-2024-014")


async def _client(repository, embedder, monkeypatch):
    app.dependency_overrides[get_repository] = lambda: repository
    monkeypatch.setattr(ingest_module, "get_cached_embedder", lambda: embedder)
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


@pytest_asyncio.fixture(autouse=True)
async def _clean_overrides():
    yield
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_ingest_persists_one_document_with_one_chunk_per_component(monkeypatch):
    repository, embedder = FakeRepository(), FakeEmbedder()
    async with await _client(repository, embedder, monkeypatch) as client:
        response = await client.post("/embeddings/ingest", json=ingest_payload())

    assert response.status_code == 200
    data = response.json()
    n_components = len(BUDGET["components"])
    assert data["document_id"] == 100
    assert data["chunks_created"] == n_components
    assert data["embedding_dimension"] == EMBEDDING_DIMENSION
    assert data["ingestion_time_ms"] >= 0

    [document] = repository.saved
    assert document.source_path == "data/budgets/BUD-2024-014.json"
    assert document.document_type == "historical_budget"
    assert len(document.chunks) == n_components
    assert all(chunk.chunk_type == "budget_component" for chunk in document.chunks)
    assert all(len(chunk.embedding) == EMBEDDING_DIMENSION for chunk in document.chunks)


@pytest.mark.asyncio
async def test_ingest_embeds_all_chunks_in_one_batch_as_documents(monkeypatch):
    repository, embedder = FakeRepository(), FakeEmbedder()
    async with await _client(repository, embedder, monkeypatch) as client:
        await client.post("/embeddings/ingest", json=ingest_payload())

    [(texts, task)] = embedder.calls
    assert len(texts) == len(BUDGET["components"])
    assert task == "document"


@pytest.mark.asyncio
async def test_ingest_stores_document_and_chunk_metadata(monkeypatch):
    repository = FakeRepository()
    async with await _client(repository, FakeEmbedder(), monkeypatch) as client:
        await client.post("/embeddings/ingest", json=ingest_payload())

    [document] = repository.saved
    assert document.metadata_["budget_id"] == BUDGET["budget_id"]
    assert document.metadata_["sector"] == BUDGET["client_metadata"]["sector"]
    assert document.metadata_["components"] == len(BUDGET["components"])

    first_component = BUDGET["components"][0]
    first_chunk = document.chunks[0]
    assert first_chunk.metadata_["component_id"] == first_component["component_id"]
    assert first_chunk.metadata_["tech_stack"] == first_component["tech_stack"]
    assert first_component["name"] in first_chunk.content


@pytest.mark.asyncio
async def test_duplicate_source_path_returns_409_without_calling_the_embedder(monkeypatch):
    payload = ingest_payload()
    repository = FakeRepository(existing={payload["source_path"]: 7})
    embedder = FakeEmbedder()
    async with await _client(repository, embedder, monkeypatch) as client:
        response = await client.post("/embeddings/ingest", json=payload)

    assert response.status_code == 409
    assert response.json() == {"detail": "Document already ingested", "document_id": 7}
    assert embedder.calls == []
    assert repository.saved == []


@pytest.mark.asyncio
async def test_losing_the_insert_race_also_returns_409_with_the_winner_id(monkeypatch):
    # La comprobación previa no ve el documento, pero el UNIQUE salta al guardar.
    repository = FakeRepository(race_winner_id=42)
    async with await _client(repository, FakeEmbedder(), monkeypatch) as client:
        response = await client.post("/embeddings/ingest", json=ingest_payload())

    assert response.status_code == 409
    assert response.json() == {"detail": "Document already ingested", "document_id": 42}


@pytest.mark.asyncio
async def test_embedder_failure_returns_generic_500_and_persists_nothing(monkeypatch):
    repository = FakeRepository()
    async with await _client(repository, FakeEmbedder(fail=True), monkeypatch) as client:
        response = await client.post("/embeddings/ingest", json=ingest_payload())

    assert response.status_code == 500
    detail = response.json()["detail"]
    assert "X-Request-ID" in detail
    assert "caído" not in detail  # el error interno solo va al log
    assert response.headers["X-Request-ID"]
    assert repository.saved == []


@pytest.mark.asyncio
async def test_embedder_with_wrong_dimension_is_rejected_before_persisting(monkeypatch):
    repository = FakeRepository()
    async with await _client(repository, FakeEmbedder(dimension=768), monkeypatch) as client:
        response = await client.post("/embeddings/ingest", json=ingest_payload())

    assert response.status_code == 500
    assert repository.saved == []


@pytest.mark.asyncio
async def test_unconfigured_embedder_returns_500(monkeypatch):
    def missing_key():
        raise RuntimeError("Falta GEMINI_API_KEY")

    repository = FakeRepository()
    app.dependency_overrides[get_repository] = lambda: repository
    monkeypatch.setattr(ingest_module, "get_cached_embedder", missing_key)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/embeddings/ingest", json=ingest_payload())

    assert response.status_code == 500
    assert "GEMINI_API_KEY" not in response.json()["detail"]
    assert repository.saved == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "mutate",
    [
        lambda p: p.pop("source_path"),
        lambda p: p.update(source_path=""),
        lambda p: p.update(document_type="x" * 51),
        lambda p: p["content"].update(components=[]),
        lambda p: p["content"]["client_metadata"].update(sector="gaming"),
    ],
    ids=["sin_source_path", "source_path_vacio", "document_type_largo", "sin_componentes",
         "sector_desconocido"],
)
async def test_invalid_payload_returns_422_before_touching_anything(monkeypatch, mutate):
    payload = ingest_payload()
    mutate(payload)
    repository, embedder = FakeRepository(), FakeEmbedder()
    async with await _client(repository, embedder, monkeypatch) as client:
        response = await client.post("/embeddings/ingest", json=payload)

    assert response.status_code == 422
    assert embedder.calls == []
    assert repository.saved == []
