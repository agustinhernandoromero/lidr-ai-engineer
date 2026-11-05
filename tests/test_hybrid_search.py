"""vector_search and hybrid_search with an in-memory repository (no database)."""

import pytest

from app.config import Settings
from app.retrieval.candidates import hybrid_search, vector_search
from tests.pgvector_fakes import search_row, unit_vector
from tests.retrieval_fakes import FakeBranchesRepository, ids, lexical_row


@pytest.mark.asyncio
async def test_vector_search_keeps_order_and_distance():
    repo = FakeBranchesRepository(vector_rows=[search_row(1, 0.1), search_row(2, 0.4)])
    chunks = await vector_search(repo, unit_vector(0), limit=5)

    assert ids(chunks) == [1, 2]
    assert chunks[0].distance == 0.1
    assert chunks[0].lexical_rank is None


@pytest.mark.asyncio
async def test_hybrid_rescues_the_exact_term_buried_in_the_vector_ranking():
    # The Stripe budget (chunk 99) is 6th for the embedding but 1st for the keywords.
    vector_rows = [search_row(i, 0.1 * i) for i in (1, 2, 3, 4, 5, 99)]
    repo = FakeBranchesRepository(vector_rows=vector_rows, lexical_rows=[lexical_row(99, 0.9)])

    # `limit` is the candidate pool of each branch, so it must reach position 6.
    chunks = await hybrid_search(repo, "integración con Stripe", unit_vector(0), limit=10)

    assert chunks[0].id == 99  # 1/61 + 1/66 beats any chunk found by only one branch
    assert ids(chunks)[1:] == [1, 2, 3, 4, 5]


@pytest.mark.asyncio
async def test_chunk_found_by_both_branches_keeps_both_scores_and_appears_once():
    repo = FakeBranchesRepository(
        vector_rows=[search_row(7, 0.2), search_row(8, 0.3)],
        lexical_rows=[lexical_row(7, 0.5), lexical_row(9, 0.1)],
    )
    chunks = await hybrid_search(repo, "q", unit_vector(0), limit=10)

    assert sorted(ids(chunks)) == [7, 8, 9]
    both = next(chunk for chunk in chunks if chunk.id == 7)
    assert both.distance == 0.2
    assert both.lexical_rank == 0.5
    only_vector = next(chunk for chunk in chunks if chunk.id == 8)
    assert only_vector.lexical_rank is None
    only_lexical = next(chunk for chunk in chunks if chunk.id == 9)
    assert only_lexical.distance is None


@pytest.mark.asyncio
async def test_limit_applies_to_each_branch_and_to_the_fused_result():
    repo = FakeBranchesRepository(
        vector_rows=[search_row(i, 0.1) for i in range(1, 6)],
        lexical_rows=[lexical_row(i, 0.1) for i in range(10, 15)],
    )
    chunks = await hybrid_search(repo, "q", unit_vector(0), limit=3)

    assert ("vector", 3) in repo.calls
    assert ("lexical", "q", 3) in repo.calls
    assert len(chunks) == 3


@pytest.mark.asyncio
async def test_without_keyword_matches_hybrid_keeps_the_vector_order():
    repo = FakeBranchesRepository(vector_rows=[search_row(i, 0.1 * i) for i in (3, 1, 2)])
    chunks = await hybrid_search(repo, "q", unit_vector(0), limit=5)

    assert ids(chunks) == [3, 1, 2]


def test_search_defaults_keep_the_session_08_behavior():
    settings = Settings(_env_file=None)
    assert settings.SEARCH_MODE == "vector"
    assert settings.RETRIEVAL_CANDIDATE_POOL == 50
    assert settings.RRF_K == 60
