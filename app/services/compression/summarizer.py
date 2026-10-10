"""Resumen acumulativo de los turnos que salen de la ventana.

Una llamada barata que funde el resumen anterior con los pares expulsados. Hay
un único resumen por sesión que se va reescribiendo. Si falla, se devuelve
``None`` y la política conserva el anterior: perder una pasada de compactación
es mejor que borrar memoria que el modelo ya estaba usando.
"""

from __future__ import annotations

import structlog

from app.prompts.loader import render_summary_prompt

logger = structlog.get_logger(__name__)

SUMMARY_MAX_CHARS = 4000


def summarize(
    llm, previous_summary: str | None, evicted: list[tuple[str, str]], max_tokens: int
) -> str | None:
    system, user = render_summary_prompt(previous_summary=previous_summary, evicted=evicted)
    try:
        out = llm.complete(
            [{"role": "system", "content": system}, {"role": "user", "content": user}],
            max_tokens=max_tokens,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("summarizer_failed", error=str(exc))
        return None
    text = (out.get("text") or "").strip()
    if not text:
        logger.warning("summarizer_failed", error="respuesta vacía")
        return None
    logger.info("summarizer_completed", summary_chars=len(text), evicted_pairs=len(evicted))
    return text[:SUMMARY_MAX_CHARS]
