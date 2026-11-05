"""Metrics and golden set of scripts/measure_retrieval.py (no database, no API)."""

import importlib.util
import json
from pathlib import Path

import pytest

from app.retrieval.types import RetrievedChunk

ROOT = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location(
    "measure_retrieval", ROOT / "scripts" / "measure_retrieval.py"
)
measure_retrieval = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(measure_retrieval)


def chunk(chunk_id: int, document_id: int) -> RetrievedChunk:
    return RetrievedChunk(
        id=chunk_id, document_id=document_id, chunk_type="c", content="", metadata={}
    )


def test_precision_counts_relevant_among_the_top_k():
    retrieved = ["a", "x", "b", "y", "z", "c"]
    assert measure_retrieval.precision_at_k(retrieved, {"a", "b", "c"}, 5) == pytest.approx(2 / 5)


def test_precision_divides_by_what_was_returned_when_fewer_than_k():
    assert measure_retrieval.precision_at_k(["a", "x"], {"a"}, 5) == pytest.approx(1 / 2)
    assert measure_retrieval.precision_at_k([], {"a"}, 5) == 0.0


def test_recall_is_the_fraction_of_relevant_found_in_the_top_k():
    retrieved = ["a", "x", "y", "z", "w", "b"]  # b is 6th: outside k=5
    assert measure_retrieval.recall_at_k(retrieved, {"a", "b"}, 5) == pytest.approx(1 / 2)
    assert measure_retrieval.recall_at_k(retrieved, set(), 5) == 0.0


def test_first_relevant_rank_is_one_based_and_none_when_absent():
    assert measure_retrieval.first_relevant_rank(["x", "a", "b"], {"a", "b"}) == 2
    assert measure_retrieval.first_relevant_rank(["x", "y"], {"a"}) is None


def test_reciprocal_rank_rewards_order_where_precision_does_not():
    relevant = {"a"}
    third = ["x", "y", "a", "z", "w"]
    second = ["x", "a", "y", "z", "w"]
    # Same precision@5, different reciprocal rank.
    assert measure_retrieval.precision_at_k(third, relevant, 5) == measure_retrieval.precision_at_k(
        second, relevant, 5
    )
    assert measure_retrieval.reciprocal_rank(third, relevant) == pytest.approx(1 / 3)
    assert measure_retrieval.reciprocal_rank(second, relevant) == pytest.approx(1 / 2)
    assert measure_retrieval.reciprocal_rank(["x"], relevant) == 0.0


def test_best_possible_precision_is_capped_by_the_number_of_relevant():
    assert measure_retrieval.max_precision_at_k({"a"}, 5) == pytest.approx(0.2)
    assert measure_retrieval.max_precision_at_k({"a", "b"}, 5) == pytest.approx(0.4)
    assert measure_retrieval.max_precision_at_k({"a", "b", "c", "d", "e", "f"}, 5) == 1.0


def test_chunks_collapse_to_budgets_keeping_the_best_chunk_rank():
    budget_by_document = {1: "BUD-A", 2: "BUD-B", 3: "BUD-C"}
    chunks = [chunk(10, 1), chunk(11, 1), chunk(12, 2), chunk(13, 1), chunk(14, 3)]
    assert measure_retrieval.distinct_budgets(chunks, budget_by_document) == [
        "BUD-A",
        "BUD-B",
        "BUD-C",
    ]


def test_golden_set_is_well_formed_and_points_to_real_budgets():
    golden_set = json.loads((ROOT / "scripts" / "golden_set.json").read_text(encoding="utf-8"))
    assert golden_set["annotation_criterion"]
    queries = golden_set["queries"]
    assert len(queries) == 5
    assert len({q["id"] for q in queries}) == len(queries)

    budgets_on_disk = {path.stem for path in (ROOT / "data" / "budgets").glob("BUD-*.json")}
    for entry in queries:
        assert entry["query"].strip()
        assert entry["relevant_budget_ids"], entry["id"]
        assert set(entry["relevant_budget_ids"]) <= budgets_on_disk, entry["id"]
