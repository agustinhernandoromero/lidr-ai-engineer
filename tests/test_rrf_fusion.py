"""Reciprocal Rank Fusion: pure function, no database or network."""

import pytest

from app.retrieval.fusion import RRF_SMOOTHING_K, reciprocal_rank_fusion


def test_document_in_both_rankings_beats_the_winner_of_only_one():
    # "a" is 1st in the first ranking and absent from the second; "b" is 2nd and 2nd.
    fused = reciprocal_rank_fusion([["a", "b", "c"], ["x", "b", "y"]])
    assert fused[0] == "b"


def test_scores_match_the_formula_with_k_60():
    # Doc 2nd in one ranking and 5th in the other: 1/62 + 1/65 (about 0.0315).
    first = ["p", "doc", "q", "r", "s"]
    second = ["t", "u", "v", "w", "doc"]
    # Only "doc" appears twice, so it must lead the fused ranking.
    fused = reciprocal_rank_fusion([first, second], k=RRF_SMOOTHING_K)
    assert fused[0] == "doc"
    assert RRF_SMOOTHING_K == 60
    assert 1 / 62 + 1 / 65 == pytest.approx(0.0315, abs=1e-4)
    assert 1 / 61 == pytest.approx(0.0164, abs=1e-4)


def test_accepts_any_number_of_rankings():
    fused = reciprocal_rank_fusion([[1, 2], [2, 3], [2, 4]])
    assert fused[0] == 2
    assert set(fused) == {1, 2, 3, 4}


def test_agreeing_rankings_give_the_same_order():
    ranking = [10, 20, 30]
    assert reciprocal_rank_fusion([ranking, ranking]) == ranking


def test_empty_inputs():
    assert reciprocal_rank_fusion([]) == []
    assert reciprocal_rank_fusion([[], []]) == []


def test_ties_keep_first_appearance_order():
    # Both lists put a different id first: equal scores, so input order decides.
    assert reciprocal_rank_fusion([["a"], ["b"]]) == ["a", "b"]


def test_consensus_wins_with_small_and_large_k():
    # "a" is 1st in one ranking only; "b" is 2nd in both.
    rankings = [["a", "b"], ["x", "b"]]
    assert reciprocal_rank_fusion(rankings, k=1)[0] == "b"  # 1/3 + 1/3 > 1/2
    assert reciprocal_rank_fusion(rankings, k=60)[0] == "b"


def test_k_must_be_positive():
    with pytest.raises(ValueError):
        reciprocal_rank_fusion([["a"]], k=0)
