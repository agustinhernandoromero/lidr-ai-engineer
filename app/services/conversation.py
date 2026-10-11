"""Orquestación de un turno conversacional del estimador.

Orden deliberado: primero todo lo que puede fallar (render, caché, estimación
estructurada, extracción) y solo después se muta la sesión. La compresión del
historial va al final y nunca lanza. Así un fallo del proveedor no deja el
historial, la metadata o el contador a medias.
"""

from __future__ import annotations

import time

import structlog

from app.guardrails.input import check_input
from app.prompts.loader import render_session_prompt
from app.schemas import EstimationResult, cost_range_eur
from app.services.attachments import ExtractedAttachment, format_attachments
from app.services.boss import Boss
from app.services.compression.policy import compress
from app.services.critic import review, revision_messages
from app.services.metadata_extractor import extract_metadata
from app.services.sessions import ProjectMetadata, Session
from app.services.structured_estimator import estimate_structured, render_markdown
from app.services.tier_resolver import resolve_tier
from app.services.usage_meter import UsageMeter

logger = structlog.get_logger(__name__)

# Los 13 campos mínimos del evento turn_observed (enunciado de la sesión 06).
OBSERVATION_FIELDS = (
    "turn_index", "session_id", "enriched_transcript_chars", "attachments_total_chars",
    "messages_in_window", "anchors_count", "summary_chars", "tokens_in", "tokens_out",
    "cost_usd", "latency_ms", "cache_hit_kind", "last_resolved_tier",
)


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


def _from_cache(payload: dict) -> tuple[EstimationResult, ProjectMetadata, dict] | None:
    """Reconstruye un turno cacheado; ``None`` si el payload es de un esquema antiguo."""
    try:
        result = EstimationResult.model_validate(payload["result"])
        metadata = ProjectMetadata.model_validate(payload["metadata"])
        meta = {
            "model": payload["model"],
            "provider": payload["provider"],
            "fallback_used": False,
            "attempts": 0,
        }
    except Exception as exc:  # noqa: BLE001 — payload de un esquema antiguo
        logger.warning("session_cache_payload_invalid", error=str(exc))
        return None
    return result, metadata, meta


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
    acb: bool = False,
) -> dict:
    """Ejecuta un turno completo. Bloqueante: el router lo lanza en un threadpool."""
    turn_started = time.perf_counter()
    # Todas las llamadas del turno (estimador, extractor, resumidor) pasan por
    # el medidor: así la observación agrega su gasto sin cambiar firmas.
    llm = UsageMeter(llm, settings)
    attachments_text = format_attachments(attachments)
    # Guardrails antes de la caché y de tocar la sesión: un turno bloqueado no
    # muta nada. Pasa por el medidor, así que la moderación cuenta en el coste.
    check_input(
        f"{transcript}\n{attachments_text}".strip(),
        llm=llm,
        moderation_enabled=settings.GUARDRAILS_MODERATION_ENABLED,
    )
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
    # El ACB tampoco cachea: mezclaría estimaciones revisadas y sin revisar.
    turn1_cache = cache if session.turn_count == 0 and not acb else None
    cache_key = cache_bucket = ""
    cached = None
    cache_hit_kind, cache_similarity = "none", None
    if turn1_cache is not None:
        cache_key = turn1_cache.exact_key(settings.ANTHROPIC_MODEL, prompt_version, system, user)
        cache_bucket = turn1_cache.bucket(
            prompt_version, project_type, detail_level, output_format, tier.value, attachments_text
        )
        hit = turn1_cache.lookup(key=cache_key, bucket=cache_bucket, transcript=transcript)
        if hit is not None:
            cached = _from_cache(hit.payload)
            if cached is not None:
                cache_hit_kind, cache_similarity = hit.kind, hit.similarity

    acb_trace = None
    if cached is not None:
        result, metadata, meta = cached
        markdown = render_markdown(result, output_format, settings.HOURLY_RATE_EUR)
        if cache_hit_kind == "semantic":
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
    else:
        if acb:
            result, meta, acb_trace = _run_acb(
                llm, messages, session, transcript=transcript,
                attachments_text=attachments_text, tier=tier.value, settings=settings,
            )
        else:
            result, meta = estimate_structured(llm, messages, settings.STRUCTURED_MAX_RETRIES)
        markdown = render_markdown(result, output_format, settings.HOURLY_RATE_EUR)
        metadata = extract_metadata(
            llm,
            session.metadata,
            transcript=transcript,
            attachments_text=attachments_text,
            answer=markdown,
        )
        # Una respuesta de fallback no se cachea: seguiría sirviéndose aunque
        # el proveedor principal ya se hubiera recuperado.
        if turn1_cache is not None and not meta["fallback_used"]:
            turn1_cache.store(
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
    observation = {
        "turn_index": session.turn_count,
        "session_id": session.session_id,
        "enriched_transcript_chars": len(transcript) + len(attachments_text),
        "attachments_total_chars": sum(len(a.text) for a in attachments),
        "messages_in_window": len(session.history) * 2,
        "anchors_count": len(session.history.anchors),
        "summary_chars": len(session.history.summary or ""),
        "tokens_in": llm.tokens_in,
        "tokens_out": llm.tokens_out,
        "cost_usd": round(llm.cost_usd, 6),
        "latency_ms": round((time.perf_counter() - turn_started) * 1000, 1),
        "cache_hit_kind": cache_hit_kind,
        "last_resolved_tier": tier.value,
        "tier_rule": tier_rule,
        "llm_calls": llm.llm_calls,
        "structured_attempts": meta["attempts"],
    }
    if acb_trace is not None:
        observation["acb_iterations"] = acb_trace.iterations_run
        observation["acb_final_decision"] = acb_trace.final_decision
    session.last_observation = observation
    # Un único evento agregado por turno: se convierte a CSV en una pasada, sin
    # reconciliar marcas de tiempo de varios eventos sueltos.
    logger.info("turn_observed", **observation)
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
        "cache_similarity": cache_similarity,
        "observation": observation,
        "acb": acb_trace.model_dump() if acb_trace is not None else None,
    }


def _run_acb(
    llm,
    messages: list[dict],
    session: Session,
    *,
    transcript: str,
    attachments_text: str,
    tier: str,
    settings,
):
    """Bucle actor → crítico → jefe sobre los mensajes del turno.

    El actor es el estimador de siempre; en cada ronda nueva recibe su borrador
    anterior y la revisión. Los intentos estructurados se suman en ``meta`` para
    que la observación cuente todos los reintentos del turno.
    """
    state: dict = {"draft": None, "meta": None, "attempts": 0}

    def actor(feedback):
        round_messages = messages
        if feedback is not None:
            round_messages = messages + revision_messages(state["draft"], feedback)
        draft, meta = estimate_structured(llm, round_messages, settings.STRUCTURED_MAX_RETRIES)
        state.update(draft=draft, meta=meta, attempts=state["attempts"] + meta["attempts"])
        return draft

    def critic(draft):
        return review(
            llm,
            transcript=transcript,
            metadata=session.metadata.model_dump(),
            anchors=[{"user": a.user, "rule": a.rule} for a in session.history.anchors],
            summary=session.history.summary,
            tier=tier,
            result=draft,
            attachments_text=attachments_text,
            recent_turns=session.history.as_dicts(),
        )

    result, trace = Boss(max_iterations=settings.ACB_MAX_ITERATIONS).run(actor, critic)
    return result, {**state["meta"], "attempts": state["attempts"]}, trace
