"""Artisanal retrieval measurement against a hand-annotated golden set.

Runs the four configurations of the session 10 exercise over the golden set:

    A  vector search            B  hybrid search (vector + keywords, RRF)
    C  vector + reranking       D  hybrid + reranking

and reports precision@5, recall@5 and retrieval latency for each one.

Usage (from the repository root, with the Postgres of docker compose running):

    .venv/Scripts/python scripts/measure_retrieval.py

It embeds each query once (a call to the embeddings provider), so it needs the
provider key in .env. The embedding is reused by the four configurations, and its
latency is reported apart: it is identical for all of them.

Relevance is judged per budget, not per chunk: a budget is split into several
chunks, so the chunks are collapsed to the budgets they belong to, keeping the
rank of the best chunk of each budget.
"""

import asyncio
import json
import sys
import time
from pathlib import Path
from statistics import mean, median
from typing import Any

# Scripts run from the repository root without installing the package.
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from sqlalchemy import select  # noqa: E402

from app.db.models import Document  # noqa: E402
from app.db.repository import DocumentRepository  # noqa: E402
from app.db.session import dispose_engine, get_sessionmaker  # noqa: E402
from app.embedding_pipeline.router import get_cached_embedder  # noqa: E402
from app.retrieval.pipeline import retrieve  # noqa: E402
from app.retrieval.reranker import get_reranker  # noqa: E402
from app.retrieval.types import RetrievedChunk  # noqa: E402

GOLDEN_SET_PATH = Path(__file__).parent / "golden_set.json"
RESULTS_PATH = ROOT / "docs" / "s10" / "medicion.md"

TOP_K = 5  # budgets that reach the LLM: precision and recall are measured on these
POOL = 50  # wide net: candidates each search branch returns
RUNS_PER_QUERY = 3  # timed runs per configuration and query (after one warm-up run)

# name -> (search mode, reranking)
CONFIGS: dict[str, tuple[str, bool]] = {
    "A": ("vector", False),
    "B": ("hybrid", False),
    "C": ("vector", True),
    "D": ("hybrid", True),
}


def distinct_budgets(chunks: list[RetrievedChunk], budget_by_document: dict[int, str]) -> list[str]:
    """Budget ids in rank order, each one at the position of its best chunk."""
    seen: list[str] = []
    for chunk in chunks:
        budget_id = budget_by_document[chunk.document_id]
        if budget_id not in seen:
            seen.append(budget_id)
    return seen


def precision_at_k(retrieved: list[str], relevant: set[str], k: int) -> float:
    """Fraction of the top-k retrieved budgets that are relevant."""
    top = retrieved[:k]
    if not top:
        return 0.0
    return sum(1 for budget_id in top if budget_id in relevant) / len(top)


def recall_at_k(retrieved: list[str], relevant: set[str], k: int) -> float:
    """Fraction of the relevant budgets that appear in the top-k."""
    if not relevant:
        return 0.0
    return sum(1 for budget_id in retrieved[:k] if budget_id in relevant) / len(relevant)


def max_precision_at_k(relevant: set[str], k: int) -> float:
    """Best possible precision@k for a query with this many relevant budgets."""
    return min(len(relevant), k) / k


async def load_budget_ids(session: Any) -> dict[int, str]:
    """document id -> budget id (from the document metadata written at ingestion)."""
    rows = (await session.execute(select(Document.id, Document.metadata_))).all()
    return {document_id: metadata["budget_id"] for document_id, metadata in rows}


async def measure() -> str:
    golden_set = json.loads(GOLDEN_SET_PATH.read_text(encoding="utf-8"))
    queries = golden_set["queries"]

    embedder = get_cached_embedder()
    vectors: dict[str, list[float]] = {}
    embed_ms: list[float] = []
    for entry in queries:
        started = time.perf_counter()
        vectors[entry["id"]] = await asyncio.to_thread(embedder.embed_one, entry["query"], "query")
        embed_ms.append((time.perf_counter() - started) * 1000)

    get_reranker()  # load the model once, outside every timer

    # config -> query id -> {"precision", "recall", "latencies", "top"}
    results: dict[str, dict[str, dict[str, Any]]] = {name: {} for name in CONFIGS}
    async with get_sessionmaker()() as session:
        repository = DocumentRepository(session)
        budget_by_document = await load_budget_ids(session)

        known = set(budget_by_document.values())
        for entry in queries:
            unknown = set(entry["relevant_budget_ids"]) - known
            if unknown:
                raise SystemExit(f"{entry['id']}: budgets not in the database: {sorted(unknown)}")

        for name, (mode, rerank) in CONFIGS.items():
            for entry in queries:
                relevant = set(entry["relevant_budget_ids"])

                async def run() -> list[RetrievedChunk]:
                    # top_k = POOL: keep the whole ranking, then collapse chunks to budgets.
                    return await retrieve(
                        repository,
                        entry["query"],
                        vectors[entry["id"]],
                        mode=mode,
                        rerank=rerank,
                        pool=POOL,
                        top_k=POOL,
                    )

                await run()  # warm-up: cold caches and connections are not the normal operation
                latencies: list[float] = []
                for _ in range(RUNS_PER_QUERY):
                    started = time.perf_counter()
                    chunks = await run()
                    latencies.append((time.perf_counter() - started) * 1000)

                retrieved = distinct_budgets(chunks, budget_by_document)
                results[name][entry["id"]] = {
                    "precision": precision_at_k(retrieved, relevant, TOP_K),
                    "recall": recall_at_k(retrieved, relevant, TOP_K),
                    "latencies": latencies,
                    "top": retrieved[:TOP_K],
                }

    await dispose_engine()
    return render(golden_set, results, embed_ms)


def render(golden_set: dict, results: dict[str, dict[str, dict[str, Any]]], embed_ms: list[float]) -> str:
    queries = golden_set["queries"]
    lines = [
        f"# Retrieval measurement (golden set of {len(queries)} queries, k={TOP_K}, pool={POOL})",
        "",
        f"Annotation criterion: {golden_set['annotation_criterion']}",
        "",
        "## Summary",
        "",
        f"| Config | Search | Reranking | precision@{TOP_K} | recall@{TOP_K} | Retrieval latency (median) |",
        "|---|---|---|---|---|---|",
    ]
    for name, (mode, rerank) in CONFIGS.items():
        per_query = results[name].values()
        latency = median(ms for item in per_query for ms in item["latencies"])
        lines.append(
            f"| {name} | {mode} | {'yes' if rerank else 'no'} "
            f"| {mean(i['precision'] for i in per_query):.2f} "
            f"| {mean(i['recall'] for i in per_query):.2f} "
            f"| {latency:.0f} ms |"
        )
    lines += [
        "",
        f"Median latency of embedding the query: {median(embed_ms):.0f} ms "
        "(same for the four configurations, not included above).",
        f"Latency: median of {RUNS_PER_QUERY} timed runs per query after one warm-up run.",
        "",
        f"## precision@{TOP_K} per query",
        "",
        f"| Query | Type | Relevant | Best possible | {' | '.join(CONFIGS)} |",
        "|---|---|---|---|" + "---|" * len(CONFIGS),
    ]
    for entry in queries:
        relevant = set(entry["relevant_budget_ids"])
        cells = " | ".join(f"{results[name][entry['id']]['precision']:.2f}" for name in CONFIGS)
        lines.append(
            f"| {entry['id']} | {entry['type']} | {len(relevant)} "
            f"| {max_precision_at_k(relevant, TOP_K):.2f} | {cells} |"
        )
    lines += ["", f"## Top {TOP_K} budgets per query and configuration", ""]
    for entry in queries:
        lines.append(f"**{entry['id']}** relevant: {', '.join(entry['relevant_budget_ids'])}")
        for name in CONFIGS:
            top = results[name][entry["id"]]["top"]
            relevant = set(entry["relevant_budget_ids"])
            marked = [f"{b}{' (relevant)' if b in relevant else ''}" for b in top]
            lines.append(f"- {name}: {', '.join(marked)}")
        lines.append("")
    return "\n".join(lines)


def main() -> None:
    report = asyncio.run(measure())
    RESULTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    RESULTS_PATH.write_text(report, encoding="utf-8")
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    print(report)
    print(f"\nSaved to {RESULTS_PATH}")


if __name__ == "__main__":
    main()
