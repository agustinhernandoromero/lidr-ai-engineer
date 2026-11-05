"""Reranker with a fake scoring model: no PyTorch, no model download."""

import subprocess
import sys

from app.retrieval.reranker import Reranker
from app.retrieval.types import RetrievedChunk
from tests.retrieval_fakes import ids


class FakeScorer:
    """Gives each pair the score mapped to its chunk text; records what it was asked."""

    def __init__(self, scores_by_content: dict[str, float]):
        self.scores_by_content = scores_by_content
        self.calls: list[list[tuple[str, str]]] = []

    def predict(self, sentences):
        self.calls.append(list(sentences))
        return [self.scores_by_content[content] for _, content in sentences]


def chunk(chunk_id: int) -> RetrievedChunk:
    return RetrievedChunk(
        id=chunk_id,
        document_id=1,
        chunk_type="budget_component",
        content=f"chunk {chunk_id}",
        metadata={},
    )


def reranker_with(scores: dict[int, float]) -> tuple[Reranker, FakeScorer]:
    scorer = FakeScorer({f"chunk {i}": s for i, s in scores.items()})
    return Reranker(model_name="fake-model", model=scorer), scorer


def test_orders_by_pair_score_and_keeps_only_top_k():
    reranker, _ = reranker_with({1: 0.1, 2: 0.9, 3: 0.5, 4: 0.7})
    result = reranker.rerank("query", [chunk(1), chunk(2), chunk(3), chunk(4)], top_k=2)

    assert ids(result) == [2, 4]


def test_scores_each_pair_of_query_and_chunk_text():
    reranker, scorer = reranker_with({1: 0.2, 2: 0.4})
    reranker.rerank("e-commerce platform", [chunk(1), chunk(2)], top_k=5)

    assert scorer.calls == [[("e-commerce platform", "chunk 1"), ("e-commerce platform", "chunk 2")]]


def test_top_k_larger_than_candidates_returns_all_of_them_reordered():
    reranker, _ = reranker_with({1: 0.1, 2: 0.9})
    assert ids(reranker.rerank("q", [chunk(1), chunk(2)], top_k=10)) == [2, 1]


def test_no_candidates_returns_empty_without_calling_the_model():
    reranker, scorer = reranker_with({})
    assert reranker.rerank("q", [], top_k=5) == []
    assert scorer.calls == []


def test_equal_scores_keep_the_incoming_order():
    reranker, _ = reranker_with({1: 0.5, 2: 0.5, 3: 0.5})
    assert ids(reranker.rerank("q", [chunk(3), chunk(1), chunk(2)], top_k=3)) == [3, 1, 2]


def test_importing_the_module_does_not_load_pytorch():
    # The heavy import happens in Reranker.__init__, only when no model is injected.
    # A clean process, because other tests in this run may already have loaded torch.
    code = "import sys, app.retrieval.reranker; print('torch' in sys.modules)"
    result = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, check=True, timeout=60
    )
    assert result.stdout.strip() == "False"
