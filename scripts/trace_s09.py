"""Traza del pre-work de la sesión 09: una transcripción cruda contra el sistema actual.

Uso (con `docker compose up` levantado; Postgres en localhost:5432):
    uv run python scripts/trace_s09.py examples/transcripts/02_ambiguous.txt

Solo es un cliente: usa el embedder y el repositorio tal cual están y llama a
POST /search sin modificarlo. No añade lógica de recuperación.

Pasos:
  1. Embebe la transcripción completa (task "query", igual que /search).
  2a. POST /search con la transcripción completa.
  2b. Top-5 con el vector del paso 1 (mismo SQL que /search, vía DocumentRepository).
  2c. POST /search con la transcripción cortada a 2000 caracteres (lo que admite hoy).
  +   Distribución de distancias contra los 58 chunks del corpus.
"""

import argparse
import asyncio
import json
import math
import os
import statistics
from pathlib import Path

import requests
import tiktoken

from app.db.repository import DocumentRepository
from app.db.session import dispose_engine, get_sessionmaker
from app.embedding_pipeline.router import get_cached_embedder

SEARCH_MAX_CHARS = 2000  # SearchRequest.query max_length
TOP_K = 5


def _row_summary(row) -> dict:
    meta = row.metadata_
    return {
        "chunk_id": row.id,
        "budget_id": meta["budget_id"],
        "component_id": meta["component_id"],
        "client_sector": meta["client_sector"],
        "distance": round(row.distance, 4),
        "content_first_lines": row.content.splitlines()[:3],
    }


async def _nearest(vector: list[float], k: int) -> list:
    async with get_sessionmaker()() as session:
        return await DocumentRepository(session).nearest_chunks(vector, k)


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("transcript", type=Path)
    parser.add_argument("--base-url", default=os.environ.get("AI_SERVICE_URL", "http://localhost:8000"))
    args = parser.parse_args()

    text = args.transcript.read_text(encoding="utf-8")
    tokens = len(tiktoken.get_encoding("cl100k_base").encode(text))
    print(f"# {args.transcript} — {len(text)} chars, ~{tokens} tokens (cl100k_base)\n")

    # 1. Embedding de la transcripción completa.
    embedder = get_cached_embedder()
    vector = await asyncio.to_thread(embedder.embed_one, text, "query")
    print("## Step 1 — embed full transcript")
    print(json.dumps({
        "provider": embedder.provider,
        "model": embedder.model,
        "dimensions": len(vector),
        "l2_norm": round(math.sqrt(sum(x * x for x in vector)), 6),
        "first_component": vector[0],
        "last_component": vector[-1],
    }, indent=2))

    # 2a. /search con la transcripción completa.
    print("\n## Step 2a — POST /search with the full transcript")
    response = requests.post(f"{args.base_url}/search", json={"query": text, "k": TOP_K}, timeout=60)
    print(f"HTTP {response.status_code}")
    body = response.json()
    if response.status_code == 422:
        # El cuerpo de error repite la query entera en "input"; se omite.
        for error in body["detail"]:
            error.pop("input", None)
    print(json.dumps(body, indent=2, ensure_ascii=False))

    # 2b. Top-5 con el vector completo.
    print(f"\n## Step 2b — top-{TOP_K} with the full-transcript vector (DocumentRepository.nearest_chunks)")
    rows = await _nearest(vector, TOP_K)
    print(json.dumps([_row_summary(row) for row in rows], indent=2, ensure_ascii=False))

    # Distribución contra todo el corpus: ¿discrimina el coseno?
    all_rows = await _nearest(vector, 1000)
    distances = [row.distance for row in all_rows]
    best_by_budget: dict[str, float] = {}
    for row in all_rows:
        best_by_budget.setdefault(row.metadata_["budget_id"], round(row.distance, 4))
    print("\n## Distance distribution over the whole corpus")
    print(json.dumps({
        "chunks": len(distances),
        "min": round(min(distances), 4),
        "p50": round(statistics.median(distances), 4),
        "max": round(max(distances), 4),
        "spread_top1_to_top5": round(distances[TOP_K - 1] - distances[0], 4),
        "spread_min_to_max": round(max(distances) - min(distances), 4),
        "best_distance_per_budget": best_by_budget,
    }, indent=2))

    # 2c. /search con lo que el endpoint admite hoy.
    print(f"\n## Step 2c — POST /search with the transcript cut to {SEARCH_MAX_CHARS} chars")
    response = requests.post(
        f"{args.base_url}/search", json={"query": text[:SEARCH_MAX_CHARS], "k": TOP_K}, timeout=60
    )
    print(f"HTTP {response.status_code}")
    body = response.json()
    body["query"] = f"<{len(body['query'])} chars, ends with: ...{body['query'][-80:]!r}>"
    print(json.dumps(body, indent=2, ensure_ascii=False))

    await dispose_engine()


if __name__ == "__main__":
    asyncio.run(main())
