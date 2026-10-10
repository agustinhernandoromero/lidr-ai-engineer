"""Orquestación de un turno conversacional del estimador.

Orden deliberado: primero todo lo que puede fallar (render, caché, estimación
estructurada, extracción) y solo después se muta la sesión. La compresión del
historial va al final y nunca lanza. Así un fallo del proveedor no deja el
historial, la metadata o el contador a medias.
"""

from __future__ import annotations

import time

import structlog

from app.prompts.loader import render_session_prompt
from app.schemas import EstimationResult, cost_range_eur
from app.services.attachments import ExtractedAttachment, format_attachments
from app.services.compression.policy import compress
from app.services.metadata_extractor import extract_metadata
from app.services.sessions import ProjectMetadata, Session
from app.services.structured_estimator import estimate_structured, render_markdown
from app.services.tier_resolver import resolve_tier

logger = structlog.get_logger(__name__)


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
    settings,
    tier_override=None,
    cache=None,
) -> dict:
    """Ejecuta un turno completo. Bloqueante: el router lo lanza en un threadpool."""
    attachments_text = format_attachments(attachments)
    tier, tier_rule = resolve_tier(transcript, session.metadata, tier_override)
    system, user = render_session_prompt(
        transcript=transcript,
        project_type=project_type,
        detail_level=detail_level,
        output_format=output_format,
        metadata=session.metadata.model_dump(),
        attachments_text=attachments_text,
        version=prompt_version,
        anchors=[{"user": a.user, "rule": a.rule} for a in session.history.anchors],
        summary=session.history.summary,
        tier=tier.value,
    )
    history_turns = len(session.history)
    messages = session.history.to_messages_list(system) + [{"role": "user", "content": user}]

    started = time.perf_counter()
    # Solo el turno 1 es cacheable: después la respuesta depende del historial.
    cacheable = cache is not None and session.turn_count == 0
    cache_key = cache_bucket = None
    hit = None
    if cacheable:
        cache_key = cache.exact_key(settings.ANTHROPIC_MODEL, prompt_version, system, user)
        cache_bucket = cache.bucket(
            prompt_version, project_type, detail_level, output_format, tier.value, attachments_text
        )
        hit = cache.lookup(key=cache_key, bucket=cache_bucket, transcript=transcript)
        if hit is not None:
            try:
                result = EstimationResult.model_validate(hit.payload["result"])
                metadata = ProjectMetadata.model_validate(hit.payload["metadata"])
                meta = {
                    "model": hit.payload["model"],
                    "provider": hit.payload["provider"],
                    "fallback_used": False,
                    "attempts": 0,
                }
            except Exception as exc:  # noqa: BLE001 — payload de un esquema antiguo
                logger.warning("session_cache_payload_invalid", error=str(exc))
                hit = None

    if hit is None:
        result, meta = estimate_structured(llm, messages, settings.STRUCTURED_MAX_RETRIES)
    markdown = render_markdown(result, output_format, settings.HOURLY_RATE_EUR)
    if hit is not None and hit.kind == "semantic":
        # Un acierto semántico reutiliza la estimación de un mensaje parecido,
        # pero los hechos del proyecto (nombre, tecnologías…) tienen que salir
        # del mensaje real: si no, la sesión arrastraría los de otro proyecto.
        metadata = extract_metadata(
            llm,
            session.metadata,
            transcript=transcript,
            attachments_text=attachments_text,
            answer=markdown,
        )
    if hit is None:
        metadata = extract_metadata(
            llm,
            session.metadata,
            transcript=transcript,
            attachments_text=attachments_text,
            answer=markdown,
        )
        # Una respuesta de fallback no se cachea: seguiría sirviéndose aunque
        # el proveedor principal ya se hubiera recuperado.
        if cacheable and not meta["fallback_used"]:
            cache.store(
                key=cache_key,
                bucket=cache_bucket,
                transcript=transcript,
                payload={
                    "result": result.model_dump(),
                    "metadata": metadata.model_dump(),
                    "model": meta["model"],
                    "provider": meta["provider"],
                },
            )
    elapsed = time.perf_counter() - started

    # A partir de aquí no hay nada que pueda fallar: se muta la sesión.
    session.metadata = metadata
    session.history.add_turn(history_entry(transcript, attachments), markdown)
    session.turn_count += 1
    session.last_tier, session.last_tier_rule = tier.value, tier_rule
    compression = compress(session.history, llm, summary_max_tokens=settings.SUMMARY_MAX_TOKENS)

    cost_min, cost_max = cost_range_eur(result, settings.HOURLY_RATE_EUR)
    cache_hit_kind = hit.kind if hit is not None else "none"
    logger.info(
        "session_turn_completed",
        session_id=session.session_id,
        turn=session.turn_count,
        history_turns_sent=history_turns,
        messages_sent=len(messages),
        attachments=len(attachments),
        provider=meta["provider"],
        fallback_used=meta["fallback_used"],
        structured_attempts=meta["attempts"],
        tier=tier.value,
        tier_rule=tier_rule,
        cache_hit_kind=cache_hit_kind,
        evicted=compression.evicted,
        elapsed_s=round(elapsed, 3),
    )

    return {
        "text": markdown,
        "result": result,
        "cost_min_eur": cost_min,
        "cost_max_eur": cost_max,
        "model": meta["model"],
        "provider": meta["provider"],
        "fallback_used": meta["fallback_used"],
        "prompt_version": prompt_version,
        "session_id": session.session_id,
        "turn": session.turn_count,
        "history_turns": history_turns,
        "project_metadata": metadata,
        "warnings": [w for a in attachments for w in a.warnings],
        "tier": tier.value,
        "tier_rule": tier_rule,
        "anchors_count": len(session.history.anchors),
        "summary_chars": len(session.history.summary or ""),
        "structured_attempts": meta["attempts"],
        "cache_hit_kind": cache_hit_kind,
        "cache_similarity": hit.similarity if hit is not None else None,
    }
