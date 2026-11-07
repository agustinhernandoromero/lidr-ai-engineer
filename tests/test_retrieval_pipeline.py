"""retrieve(): the four configurations A-D of the exercise, with in-memory fakes."""

import pytest

from app.retrieval.pipeline import retrieve
from app.retrieval.reranker import Reranker
from tests.pgvector_fakes import search_row, unit_vector
from tests.retrieval_fakes import FakeBranchesRepository, ids, lexical_row


class ReverseScorer:
    """Scores later chunks higher, so reranking visibly flips the incoming order."""

    def __init__(self):
        self.pairs_seen = 0

    def predict(self, sentences):
        self.pairs_seen += len(sentences)
        return [float(int(content.split()[-1])) for _, content in sentences]


class ForbiddenScorer:
    def predict(self, sentences):
        raise AssertionError("the reranker must not run when reranking is off")


def repo() -> FakeBranchesRepository:
    return FakeBranchesRepository(
        vector_rows=[search_row(i, 0.1 * i) for i in range(1, 9)],  # 1..8, best first
        lexical_rows=[lexical_row(99, 0.9), lexical_row(5, 0.4)],
    )


async def run(**kwargs):
    return await retrieve(repo(), "integración con Stripe", unit_vector(0), **kwargs)


@pytest.mark.asyncio
async def test_config_a_vector_without_rerank_is_the_vector_top_k():
    chunks = await run(mode="vector", rerank=False, pool=8, top_k=3)
    assert ids(chunks) == [1, 2, 3]


@pytest.mark.asyncio
async def test_config_b_hybrid_without_rerank_brings_the_keyword_match_up():
    chunks = await run(mode="hybrid", rerank=False, pool=8, top_k=3)
    assert 99 in ids(chunks)  # found only by the keyword branch
    assert ids(chunks)[0] == 5  # in both branches: consensus wins


@pytest.mark.asyncio
async def test_config_c_vector_with_rerank_reorders_the_whole_pool():
    scorer = ReverseScorer()
    chunks = await run(
        mode="vector", rerank=True, pool=8, top_k=3, reranker=Reranker("fake", model=scorer)
    )
    assert scorer.pairs_seen == 8  # the wide pool is scored, not just the top_k
    assert ids(chunks) == [8, 7, 6]


@pytest.mark.asyncio
async def test_config_d_hybrid_with_rerank_scores_the_fused_pool():
    scorer = ReverseScorer()
    chunks = await run(
        mode="hybrid", rerank=True, pool=8, top_k=3, reranker=Reranker("fake", model=scorer)
    )
    # The fusion yields 9 distinct chunks (8 vector + 99); the pool caps it at 8.
    assert scorer.pairs_seen == 8
    assert ids(chunks)[0] == 99  # found by the keyword branch, inside the fused pool


@pytest.mark.asyncio
async def test_reranker_is_not_called_when_reranking_is_off():
    await run(
        mode="vector",
        rerank=False,
        pool=8,
        top_k=3,
        reranker=Reranker("fake", model=ForbiddenScorer()),
    )


@pytest.mark.asyncio
async def test_unknown_mode_is_rejected():
    with pytest.raises(ValueError, match="unknown search mode"):
        await run(mode="semantic", rerank=False)


@pytest.mark.asyncio
async def test_arguments_left_unset_follow_the_settings(monkeypatch):
    monkeypatch.setenv("SEARCH_MODE", "hybrid")
    monkeypatch.setenv("RERANKING_ENABLED", "false")
    monkeypatch.setenv("RETRIEVAL_TOP_K", "2")
    monkeypatch.setenv("RETRIEVAL_CANDIDATE_POOL", "8")
    from app.config import get_settings

    get_settings.cache_clear()
    try:
        chunks = await run()
    finally:
        get_settings.cache_clear()
    assert len(chunks) == 2
    assert 5 in ids(chunks)  # hybrid: chunk 5 appears in both branches
