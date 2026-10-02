"""Extractor de ``project_metadata`` mediante una segunda llamada al LLM.

Elegimos un extractor LLM frente a una heurística con regex porque los hechos
que importan llegan en prosa libre ("seremos cuatro", "los pagos van a la fase
2") y una regex los captura mal. Coste: una llamada extra por turno, acotada a
``EXTRACTION_MAX_TOKENS``. Si la extracción falla por cualquier motivo, se
conserva la metadata anterior: perder un turno de memoria es preferible a
romper la estimación que el usuario ya ha recibido.
"""

from __future__ import annotations

import json

import structlog

from app.prompts.loader import render_extraction_prompt
from app.services.sessions import ProjectMetadata

logger = structlog.get_logger(__name__)

EXTRACTION_MAX_TOKENS = 500


def _parse_json_object(text: str) -> dict:
    """Recorta del primer ``{`` al último ``}``: tolera ```json y prosa alrededor."""
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        raise ValueError("la respuesta no contiene un objeto JSON")
    return json.loads(text[start : end + 1])


def extract_metadata(
    llm,
    previous: ProjectMetadata,
    *,
    transcript: str,
    attachments_text: str,
    answer: str,
) -> ProjectMetadata:
    """Devuelve ``previous`` fusionada con los hechos del turno. Nunca lanza."""
    system, user = render_extraction_prompt(
        previous=previous.model_dump(),
        transcript=transcript,
        attachments_text=attachments_text,
        answer=answer,
    )
    try:
        result = llm.complete(
            [{"role": "system", "content": system}, {"role": "user", "content": user}],
            max_tokens=EXTRACTION_MAX_TOKENS,
        )
        extracted = ProjectMetadata.model_validate(_parse_json_object(result["text"]))
    except Exception as exc:  # noqa: BLE001
        logger.warning("metadata_extraction_failed", error=str(exc))
        return previous

    merged = previous.merge(extracted)
    logger.info(
        "metadata_extracted",
        project_name=merged.project_name,
        technologies=len(merged.mentioned_technologies),
        provider=result.get("provider"),
    )
    return merged
