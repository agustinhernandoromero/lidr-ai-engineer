"""Similitud coseno entre dos textos con los embeddings del pipeline.

Uso (desde la raíz del repo, para que se lea el .env):
    uv run python scripts/compare.py --text-a "..." --text-b "..."
    docker compose exec api python scripts/compare.py --text-a "..." --text-b "..."

Usa el mismo proveedor que POST /embeddings/ingest (EMBEDDING_PROVIDER).
"""

import argparse
import math
import sys


def cosine_similarity(vec_a: list[float], vec_b: list[float]) -> float:
    """Producto escalar dividido por el producto de las normas, en [-1, 1]."""
    if len(vec_a) != len(vec_b):
        # Pasa si se mezclan vectores de modelos distintos (p. ej. 3072 frente a 1536).
        raise ValueError(f"Dimensiones distintas: {len(vec_a)} frente a {len(vec_b)}")
    dot = sum(a * b for a, b in zip(vec_a, vec_b))
    norm_a = l2_norm(vec_a)
    norm_b = l2_norm(vec_b)
    if norm_a == 0 or norm_b == 0:
        raise ValueError("No se puede calcular la similitud de un vector de norma cero")
    return dot / (norm_a * norm_b)


def l2_norm(vec: list[float]) -> float:
    """Norma euclídea; 1.0 si el modelo entrega vectores normalizados."""
    return math.sqrt(sum(x * x for x in vec))


def main() -> int:
    parser = argparse.ArgumentParser(description="Similitud coseno entre dos textos.")
    parser.add_argument("--text-a", required=True, help="Primer texto.")
    parser.add_argument("--text-b", required=True, help="Segundo texto.")
    args = parser.parse_args()

    from app.embedding_pipeline.embedder import get_embedder

    try:
        embedder = get_embedder()
        vec_a = embedder.embed_one(args.text_a)
        vec_b = embedder.embed_one(args.text_b)
        similarity = cosine_similarity(vec_a, vec_b)
    except Exception as exc:  # noqa: BLE001
        print(f"Error: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1

    print(f"Text A: {args.text_a}")
    print(f"Text B: {args.text_b}")
    print(f"Model: {embedder.model} ({len(vec_a)} dims)")
    print(f"Norms: A={l2_norm(vec_a):.4f} B={l2_norm(vec_b):.4f}")
    print(f"Cosine similarity: {similarity:.4f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
