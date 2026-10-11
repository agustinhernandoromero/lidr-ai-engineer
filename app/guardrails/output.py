"""Guardrail de salida (sesión 04): filtro sobre el JSON crudo del estimador.

El validador del esquema exige que una confianza < 30 empiece por
"Fuera de alcance:". En la ejecución real de la sesión 06, 12 de 30 turnos
reintentaron solo por olvidar ese prefijo, y cada reintento reenvía todo el
contexto. Este filtro lo añade antes de validar; el validador queda como
última defensa.

Política ``filter``: nunca lanza. Lo que no entiende lo deja pasar tal cual
para que el validador dé el error de siempre.
"""

from __future__ import annotations

import structlog

from app.schemas import LOW_CONFIDENCE_THRESHOLD, OUT_OF_SCOPE_PREFIX, SUMMARY_MAX_CHARS

logger = structlog.get_logger()


def enforce_scope(data: object) -> object:
    if not isinstance(data, dict):
        return data
    confidence, summary = data.get("confidence_pct"), data.get("summary")
    if not isinstance(confidence, int) or not isinstance(summary, str):
        return data
    if confidence >= LOW_CONFIDENCE_THRESHOLD or summary.startswith(OUT_OF_SCOPE_PREFIX):
        return data
    logger.info("output_guardrail_filtered", confidence_pct=confidence)
    return {**data, "summary": f"{OUT_OF_SCOPE_PREFIX} {summary}"[:SUMMARY_MAX_CHARS]}
