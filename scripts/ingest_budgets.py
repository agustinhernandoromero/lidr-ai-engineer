"""Carga los presupuestos de data/budgets/ en Postgres vía POST /embeddings/ingest.

Uso (con la API levantada):
    uv run python scripts/ingest_budgets.py
    docker compose run --rm api python scripts/ingest_budgets.py

La URL del servicio sale de AI_SERVICE_URL (compose la fija a http://api:8000).
Envía un presupuesto por petición. Los ya ingestados devuelven 409 y se
cuentan como omitidos, así que el script se puede relanzar sin duplicar nada.
"""

import argparse
import json
import os
import sys
from pathlib import Path

import requests

BUDGETS_DIR = Path("data/budgets")
DOCUMENT_TYPE = "historical_budget"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--base-url",
        default=os.environ.get("AI_SERVICE_URL", "http://localhost:8000"),
        help="URL base del servicio IA",
    )
    args = parser.parse_args()

    paths = sorted(BUDGETS_DIR.glob("*.json"))
    if not paths:
        print(f"No hay presupuestos en {BUDGETS_DIR}/", file=sys.stderr)
        return 1

    created = skipped = failed = 0
    for path in paths:
        payload = {
            "source_path": path.as_posix(),
            "document_type": DOCUMENT_TYPE,
            "content": json.loads(path.read_text(encoding="utf-8")),
        }
        response = requests.post(f"{args.base_url}/embeddings/ingest", json=payload, timeout=120)
        body = response.json()
        if response.status_code == 200:
            created += 1
            print(
                f"OK    {path.name}: document_id={body['document_id']} "
                f"chunks={body['chunks_created']} {body['ingestion_time_ms']} ms"
            )
        elif response.status_code == 409:
            skipped += 1
            print(f"YA    {path.name}: document_id={body['document_id']} (ya ingestado)")
        else:
            failed += 1
            print(f"ERROR {path.name}: HTTP {response.status_code} {body}", file=sys.stderr)

    print(f"\n{created} ingestados, {skipped} ya existían, {failed} con error")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
