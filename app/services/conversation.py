"""Orquestación de un turno conversacional del estimador.

Orden deliberado: primero todo lo que puede fallar (render, llamada al LLM,
extracción) y solo al final se muta la sesión. Así un fallo del proveedor no
deja el historial o el contador a medias.
"""

from __future__ import annotations

import time

import structlog

from app.prompts.loader import render_session_prompt
from app.services.attachments import ExtractedAttachment, format_attachments
from app.services.metadata_extractor import extract_metadata
from app.services.sessions import Session

logger = structlog.get_logger(__name__)


class EmptyLLMResponseError(RuntimeError):
    """El proveedor devolvió una respuesta vacía (bloqueo de seguridad, tokens
    agotados…). Guardarla en el historial haría que Anthropic rechazara los
    turnos siguientes, así que el turno se rechaza entero.
    """


def history_entry(transcript: str, attachments: list[ExtractedAttachment]) -> str:
    """Mensaje de usuario tal y como queda en el historial.

    El texto completo de los adjuntos solo viaja en el turno en que se suben;
    al historial pasa una marca. Los hechos relevantes del documento ya están
    a salvo en ``project_metadata``.
    """
    if not attachments:
        return transcript
    names = ", ".join(f"{a.filename} ({a.chars} caracteres)" for a in attachments)
    return f"{transcript}\n\n[adjuntos: {names}]"


def run_turn(
    session: Session,
    llm,
    *,
    transcript: str,
    project_type: str,
    detail_level: str,
    output_format: str,
    attachments: list[ExtractedAttachment],
    prompt_version: str,
) -> dict:
    """Ejecuta un turno completo. Bloqueante: el router lo lanza en un threadpool."""
    attachments_text = format_attachments(attachments)
    system, user = render_session_prompt(
        transcript=transcript,
        project_type=project_type,
        detail_level=detail_level,
        output_format=output_format,
        metadata=session.metadata.model_dump(),
        attachments_text=attachments_text,
        version=prompt_version,
    )

    history_turns = len(session.history)
    messages = session.history.to_messages_list(system) + [{"role": "user", "content": user}]

    started = time.perf_counter()
    result = llm.complete(messages)
    if not result["text"].strip():
        raise EmptyLLMResponseError(
            f"El proveedor '{result['provider']}' devolvió una respuesta vacía."
        )
    metadata = extract_metadata(
        llm,
        session.metadata,
        transcript=transcript,
        attachments_text=attachments_text,
        answer=result["text"],
    )
    elapsed = time.perf_counter() - started

    # A partir de aquí no hay nada que pueda fallar: se muta la sesión.
    session.metadata = metadata
    session.history.add_turn(history_entry(transcript, attachments), result["text"])
    session.turn_count += 1

    logger.info(
        "session_turn_completed",
        session_id=session.session_id,
        turn=session.turn_count,
        history_turns_sent=history_turns,
        messages_sent=len(messages),
        attachments=len(attachments),
        provider=result["provider"],
        fallback_used=result["fallback_used"],
        elapsed_s=round(elapsed, 3),
    )

    return {
        "text": result["text"],
        "model": result["model"],
        "provider": result["provider"],
        "fallback_used": result["fallback_used"],
        "prompt_version": prompt_version,
        "session_id": session.session_id,
        "turn": session.turn_count,
        "history_turns": history_turns,
        "project_metadata": metadata,
        "warnings": [w for a in attachments for w in a.warnings],
    }
