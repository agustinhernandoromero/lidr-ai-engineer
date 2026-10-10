"""Estimación estructurada: JSON forzado por esquema + validación + reintento.

El modelo devuelve un ``EstimationResult`` en horas. Si una regla de negocio
falla (las fases no suman el total, confianza baja sin declararlo…), se le
reenvía su propio JSON con el error y se le pide corregirlo. Es lo mismo que
hace Instructor por dentro, pero visible y sin dependencias. El Markdown que
ve el usuario se genera aquí, en código, a partir del JSON validado.
"""

from __future__ import annotations

import json

import anthropic
import structlog
from pydantic import ValidationError

from app.schemas import EstimationResult, cost_range_eur

logger = structlog.get_logger(__name__)

# Esquema que la API usa para forzar la forma del JSON. transform_schema lo
# adapta a lo que acepta Anthropic (additionalProperties: False, restricciones
# numéricas pasadas a descripción); las reglas reales las valida Pydantic.
ESTIMATION_JSON_SCHEMA = anthropic.transform_schema(EstimationResult.model_json_schema())


class StructuredOutputError(RuntimeError):
    """El modelo no produjo un EstimationResult válido tras todos los intentos."""


def _json_slice(text: str) -> str:
    """Del primer ``{`` al último ``}``: tolera ```json y prosa alrededor."""
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        raise ValueError("la respuesta no contiene un objeto JSON")
    return text[start : end + 1]


def _describe(exc: Exception) -> str:
    if isinstance(exc, ValidationError):
        return "; ".join(err["msg"] for err in exc.errors()[:5])
    return str(exc)


def estimate_structured(llm, messages: list[dict], max_retries: int) -> tuple[EstimationResult, dict]:
    """Pide el JSON, lo valida y, si falla, reintenta enseñando el error al modelo.

    ``json.loads`` lanza ``JSONDecodeError`` (subclase de ``ValueError``): un
    JSON cortado por ``max_tokens`` entra por el mismo camino que una regla rota.
    """
    attempt_messages = list(messages)
    last_error = ""
    for attempt in range(1, max_retries + 2):
        out = llm.complete(attempt_messages, json_schema=ESTIMATION_JSON_SCHEMA)
        text = out["text"] or ""
        try:
            result = EstimationResult.model_validate(json.loads(_json_slice(text)))
        except (ValidationError, ValueError) as exc:
            last_error = _describe(exc)
            logger.warning("structured_output_invalid", attempt=attempt, error=last_error)
            attempt_messages = attempt_messages + [
                {"role": "assistant", "content": text.strip() or "{}"},
                {
                    "role": "user",
                    "content": (
                        f"Tu JSON no cumple las reglas: {last_error}. "
                        "Devuelve el JSON completo y corregido, sin texto alrededor."
                    ),
                },
            ]
            continue
        return result, {
            "model": out["model"],
            "provider": out["provider"],
            "fallback_used": out.get("fallback_used", False),
            "attempts": attempt,
        }
    raise StructuredOutputError(
        f"El modelo no produjo una estimación válida tras {max_retries + 1} intentos: {last_error}"
    )


def _fmt(n: int) -> str:
    """Miles con punto, como se escriben en España: 13500 → '13.500'."""
    return f"{n:,}".replace(",", ".")


def render_markdown(result: EstimationResult, output_format: str, rate: int) -> str:
    cost_min, cost_max = cost_range_eur(result, rate)
    totals = (
        f"**Total: {result.total_hours_min}–{result.total_hours_max} h** · "
        f"**Coste: {_fmt(cost_min)}–{_fmt(cost_max)} €** ({rate} €/h) · "
        f"**Duración: {result.total_duration_weeks} semanas** · "
        f"**Confianza: {result.confidence_pct}%**"
    )
    parts = [result.summary, ""]

    if output_format == "phases_table":
        parts += [
            "| Fase | Descripción | Horas min | Horas max | Confianza |",
            "|---|---|---|---|---|",
        ]
        parts += [
            f"| {p.name} | {p.summary} | {p.hours_min} | {p.hours_max} | {p.confidence_pct}% |"
            for p in result.phases
        ]
        parts += [
            f"| **Total** | | **{result.total_hours_min}–{result.total_hours_max} h** "
            f"| | **{result.confidence_pct}%** |",
            "",
            totals,
        ]
    elif output_format == "line_items":
        parts += [
            f"- **{p.name}**: {p.hours_min}–{p.hours_max} h ({p.confidence_pct}%) — {p.summary}"
            for p in result.phases
        ]
        parts += ["", totals]
    else:  # narrative
        parts += [
            f"**{p.name}** ({p.hours_min}–{p.hours_max} h, {p.confidence_pct}% de confianza): "
            f"{p.summary}"
            for p in result.phases
        ]
        parts += ["", totals]

    if result.assumptions:
        parts += ["", "**Supuestos:**"] + [f"- {a}" for a in result.assumptions]
    if result.out_of_scope:
        parts += ["", "**Fuera de alcance:**"] + [f"- {o}" for o in result.out_of_scope]
    return "\n".join(parts)
