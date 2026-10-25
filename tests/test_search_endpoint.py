"""POST /search: contrato de respuesta, validación de k y errores (sin red ni Postgres)."""

import httpx
import pytest
import pytest_asyncio

from app.db.repository import get_repository
from app.embedding_pipeline import search as search_module
from app.main import app
from tests.pgvector_fakes import FakeEmbedder, FakeRepository, search_row


async def _client(repository, embedder, monkeypatch):
    app.dependency_overrides[get_repository] = lambda: repository
    monkeypatch.setattr(search_module, "get_cached_embedder", lambda: embedder)
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


@pytest_asyncio.fixture(autouse=True)
async def _clean_overrides():
    yield
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_search_returns_rows_in_repository_order_with_contract_fields(monkeypatch):
    rows = [search_row(5, 0.41), search_row(6, 0.47), search_row(13, 0.52, document_id=4)]
    repository = FakeRepository(rows=rows)
    async with await _client(repository, FakeEmbedder(), monkeypatch) as client:
        response = await client.post("/search", json={"query": "API REST con JWT", "k": 3})

    assert response.status_code == 200
    data = response.json()
    assert data["query"] == "API REST con JWT"
    assert data["k"] == 3
    assert data["search_time_ms"] >= 0
    assert [r["chunk_id"] for r in data["results"]] == [5, 6, 13]
    assert [r["distance"] for r in data["results"]] == [0.41, 0.47, 0.52]
    first = data["results"][0]
    assert set(first) == {"chunk_id", "document_id", "chunk_type", "content", "distance", "metadata"}
    assert first["metadata"] == {"component_id": "C-5", "sector": "finance"}
    assert data["results"][2]["document_id"] == 4


@pytest.mark.asyncio
async def test_query_is_embedded_as_query_and_passed_to_repository(monkeypatch):
    repository, embedder = FakeRepository(), FakeEmbedder()
    async with await _client(repository, embedder, monkeypatch) as client:
        await client.post("/search", json={"query": "pasarela de pagos", "k": 7})

    [(texts, task)] = embedder.calls
    assert texts == ["pasarela de pagos"]
    assert task == "query"  # Gemini distingue query de documento
    [(vector, k)] = repository.searches
    assert len(vector) == 1536
    assert k == 7


@pytest.mark.asyncio
async def test_k_defaults_to_5(monkeypatch):
    repository = FakeRepository(rows=[search_row(i, i / 10) for i in range(1, 9)])
    async with await _client(repository, FakeEmbedder(), monkeypatch) as client:
        response = await client.post("/search", json={"query": "telemedicina"})

    assert response.status_code == 200
    assert response.json()["k"] == 5
    assert len(response.json()["results"]) == 5
    assert repository.searches[0][1] == 5


@pytest.mark.asyncio
async def test_empty_corpus_is_200_with_no_results(monkeypatch):
    async with await _client(FakeRepository(), FakeEmbedder(), monkeypatch) as client:
        response = await client.post("/search", json={"query": "cualquier cosa", "k": 5})

    assert response.status_code == 200
    assert response.json()["results"] == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "body",
    [
        {"query": "x", "k": 0},
        {"query": "x", "k": 51},
        {"query": "x", "k": "muchos"},
        {"query": ""},
        {"query": "x" * 2001},
        {"k": 5},
    ],
    ids=["k_cero", "k_mayor_50", "k_no_entero", "query_vacia", "query_larga", "sin_query"],
)
async def test_invalid_request_returns_422_without_embedding(monkeypatch, body):
    repository, embedder = FakeRepository(), FakeEmbedder()
    async with await _client(repository, embedder, monkeypatch) as client:
        response = await client.post("/search", json=body)

    assert response.status_code == 422
    assert embedder.calls == []
    assert repository.searches == []


@pytest.mark.asyncio
async def test_embedder_failure_returns_generic_500_without_querying(monkeypatch):
    repository = FakeRepository(rows=[search_row(1, 0.1)])
    async with await _client(repository, FakeEmbedder(fail=True), monkeypatch) as client:
        response = await client.post("/search", json={"query": "x", "k": 5})

    assert response.status_code == 500
    assert "X-Request-ID" in response.json()["detail"]
    assert "caído" not in response.json()["detail"]
    assert repository.searches == []
