"""Cinco queries representativas contra POST /search, con el top-5 de cada una.

Uso (con la API levantada y el corpus cargado con scripts/ingest_budgets.py):
    docker compose run --rm api python query_examples.py
    uv run python query_examples.py            # fuera de Docker, contra localhost:8000

La URL del servicio sale de AI_SERVICE_URL (compose la fija a http://api:8000).
"""

import os
import sys

import requests

BASE_URL = os.environ.get("AI_SERVICE_URL", "http://localhost:8000")
K = 5
CONTENT_PREVIEW_CHARS = 120

# Cada query ejercita el corpus desde un ángulo distinto.
QUERIES = [
    ("Componente directo conocido", "REST API development with JWT authentication for financial sector"),
    (
        "Reformulación semántica",
        "secure backend service with token-based access control for banking applications",
    ),
    ("Dominio distinto", "mobile application for restaurant reservations"),
    ("Consulta ambigua", "integration with external system"),
    ("Consulta muy específica", "migration from monolith to microservices architecture using Kubernetes"),
]


def _component_line(content: str) -> str:
    """Línea "Component: ..." del chunk; los primeros 120 caracteres son la
    cabecera del presupuesto, común a todos sus componentes."""
    for line in content.splitlines():
        if line.startswith("Component: "):
            return line
    return ""


def _print_results(label: str, query: str, body: dict) -> None:
    print(f"=== {label} ===")
    print(f'Query: "{query}"')
    print(f"search_time_ms: {body['search_time_ms']}")
    for rank, result in enumerate(body["results"], start=1):
        preview = " ".join(result["content"].split())[:CONTENT_PREVIEW_CHARS]
        print(
            f"  {rank}. chunk_id={result['chunk_id']:<4} distance={result['distance']:.4f}  "
            f"{result['chunk_type']}"
        )
        print(f"     {preview}")
        print(f"     -> {_component_line(result['content'])}")
    print()


def main() -> int:
    for label, query in QUERIES:
        response = requests.post(f"{BASE_URL}/search", json={"query": query, "k": K}, timeout=60)
        if response.status_code != 200:
            print(f"ERROR en '{query}': HTTP {response.status_code} {response.text}", file=sys.stderr)
            return 1
        _print_results(label, query, response.json())
    return 0


if __name__ == "__main__":
    sys.exit(main())
