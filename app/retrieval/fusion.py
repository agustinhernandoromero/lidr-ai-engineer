"""Reciprocal Rank Fusion (RRF): merge several rankings into one.

Vector distances and ts_rank scores live on different scales, so they cannot be
added. RRF ignores the scores and uses only positions: a document earns
1 / (k + position) from each ranking it appears in, and the earnings are summed.
A document that several rankings place reasonably high beats one that a single
ranking places first.
"""

from collections import defaultdict
from collections.abc import Hashable, Sequence
from typing import TypeVar

# 60 is the value from the original RRF paper; it rarely needs tuning.
RRF_SMOOTHING_K = 60

T = TypeVar("T", bound=Hashable)


def reciprocal_rank_fusion(
    rankings: Sequence[Sequence[T]],
    k: int = RRF_SMOOTHING_K,
) -> list[T]:
    """Fuse ranked lists of ids (best first) into a single ranking.

    Takes any number of rankings, not just two. Ties keep the order in which
    the ids first appeared across the input rankings, so the result is
    deterministic.
    """
    if k <= 0:
        raise ValueError("k must be positive")
    scores: dict[T, float] = defaultdict(float)
    for ranking in rankings:
        for position, item_id in enumerate(ranking, start=1):
            scores[item_id] += 1.0 / (k + position)
    # sorted() is stable: equal scores keep the dict's insertion order.
    return [item_id for item_id, _ in sorted(scores.items(), key=lambda pair: pair[1], reverse=True)]
