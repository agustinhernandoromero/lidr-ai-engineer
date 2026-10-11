"""Crítico del Actor-Critic-Boss (sesión 05): auditoría independiente del borrador.

Función sin estado: (turno, memoria, tier, borrador) → ``CriticFeedback``. No
decide qué hacer con su revisión; eso es cosa del jefe. Si falla, devuelve
"aceptar" con confianza 0: el borrador del actor pasa sin cambios en vez de
dar un error al usuario.
"""

from __future__ import annotations

import json

import anthropic
import structlog
from pydantic import ValidationError

from app.prompts.loader import render_critic_prompt
from app.schemas import CriticFeedback, EstimationResult
from app.services.structured_estimator import _describe, _json_slice

logger = structlog.get_logger()

CRITIC_JSON_SCHEMA = anthropic.transform_schema(CriticFeedback.model_json_schema())
CRITIC_MAX_TOKENS = 1500
CRITIC_MAX_RETRIES = 2
# Las respuestas anteriores del estimador son Markdown largo: al crítico le basta
# con las cifras y decisiones del principio.
RECENT_ANSWER_MAX_CHARS = 800
REVISION_INTRO = "Un revisor independiente encontró estos fallos en tu estimación:"


def _fallback_accept() -> CriticFeedback:
    return CriticFeedback(verdict="aceptar", issues=[], confidence_in_review=0)


def review(
    llm,
    *,
    transcript: str,
    metadata: dict,
    anchors: list[dict],
    summary: str | None,
    tier: str,
    result: EstimationResult,
    attachments_text: str = "",
    recent_turns: list[dict] | None = None,
) -> CriticFeedback:
    # El crítico ve lo mismo que el actor (adjuntos y ventana reciente): si no,
    # un dato sacado de un PDF o del turno anterior le parecería inventado.
    system, user = render_critic_prompt(
        transcript=transcript,
        metadata=metadata,
        anchors=anchors,
        summary=summary,
        tier=tier,
        result_json=result.model_dump_json(),
        attachments_text=attachments_text,
        recent_turns=[
            {"user": t["user"], "assistant": t["assistant"][:RECENT_ANSWER_MAX_CHARS]}
            for t in recent_turns or []
        ],
    )
    messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
    for attempt in range(1, CRITIC_MAX_RETRIES + 2):
        try:
            out = llm.complete(messages, max_tokens=CRITIC_MAX_TOKENS, json_schema=CRITIC_JSON_SCHEMA)
        except Exception as exc:  # noqa: BLE001 — el crítico nunca tumba el turno
            logger.warning("critic_failed_fallback_accept", error=str(exc)[:200])
            return _fallback_accept()
        text = out["text"] or ""
        try:
            feedback = CriticFeedback.model_validate(json.loads(_json_slice(text)))
        except (ValidationError, ValueError) as exc:
            error = _describe(exc)
            logger.warning("critic_output_invalid", attempt=attempt, error=error)
            messages = messages + [
                {"role": "assistant", "content": text.strip() or "{}"},
                {"role": "user", "content": (
                    f"Tu JSON no cumple las reglas: {error}. "
                    "Devuelve el JSON completo y corregido, sin texto alrededor."
                )},
            ]
            continue
        logger.info(
            "critic_completed",
            verdict=feedback.verdict,
            issues=len(feedback.issues),
            confidence=feedback.confidence_in_review,
        )
        return feedback
    logger.warning("critic_failed_fallback_accept", error="JSON inválido tras todos los intentos")
    return _fallback_accept()


def revision_messages(draft: EstimationResult, feedback: CriticFeedback) -> list[dict]:
    """Mensajes que se añaden al actor para que rehaga el borrador con la revisión."""
    lines = []
    for issue in feedback.issues:
        line = f"- [{issue.severity}] {issue.category} ({issue.field_path}): {issue.description}"
        if issue.suggested_fix:
            line += f" Arreglo sugerido: {issue.suggested_fix}"
        lines.append(line)
    return [
        {"role": "assistant", "content": draft.model_dump_json()},
        {"role": "user", "content": (
            f"{REVISION_INTRO}\n" + "\n".join(lines)
            + "\nCorrígelos y devuelve el JSON completo y corregido, sin texto alrededor."
        )},
    ]
