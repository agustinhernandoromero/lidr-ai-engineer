"""Pre-flight check: does the cross-encoder download, load and score?

Run it before touching any retrieval code::

    python -m app.retrieval.verify_reranker

It loads the configured model and scores a tiny pair of documents where one is
obviously relevant to the query. Exit code 0 means the model is ready; any other
code means stop and fix the environment first.
"""

from __future__ import annotations

import sys

from app.retrieval.reranker import Reranker

_QUERY = "e-commerce checkout and shopping cart platform"
_DOCUMENTS = [
    "Online store checkout flow with shopping cart, payment and order management.",
    "Hospital patient appointment scheduling and telemedicine video consultations.",
]


def main() -> int:
    print("Loading reranker model...")
    try:
        reranker = Reranker()
        scores = [float(s) for s in reranker._model.predict([(_QUERY, doc) for doc in _DOCUMENTS])]
    except Exception as exc:  # noqa: BLE001 - surface any load or scoring failure
        print(f"FAILED to load or run the reranker: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1

    print(f"Model:          {reranker.model_name}")
    print(f"Relevant doc:   score = {scores[0]:.4f}")
    print(f"Irrelevant doc: score = {scores[1]:.4f}")
    if scores[0] <= scores[1]:
        print("WARNING: the relevant document did not outscore the irrelevant one.", file=sys.stderr)
        return 2

    print("OK: reranker loaded and ranked the relevant document first.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
