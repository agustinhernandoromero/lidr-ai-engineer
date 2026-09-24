"""Wrapper de proveedores LLM y orquestación de la estimación.

El prompt ya no se construye aquí: vive en ``app/prompts/estimation/<version>/``
y lo renderiza el loader. Este módulo solo sabe hablar con OpenAI y con Anthropic.
"""

from __future__ import annotations

import time
from typing import Any, Dict, Iterator

import structlog

from app.config import get_settings
from app.dependencies import get_cache
from app.prompts.loader import DEFAULT_VERSION, render_estimation_prompt
from app.schemas import EstimationRequest

logger = structlog.get_logger(__name__)

MAX_TOKENS = 4000


# --------------------------------------------------------------------------- #
# Compatibilidad con la sesión 02/03
# --------------------------------------------------------------------------- #

def build_cag_system_prompt() -> str:
    """System prompt CAG de la sesión 02, conservado para el modo chat libre.

    El endpoint tipado ya no lo usa: renderiza la plantilla Jinja2 correspondiente.
    Se mantiene porque ``streamlit_app.py`` sigue ofreciendo el chat conversacional
    de la sesión 03, que no tiene formulario ni contrato tipado.
    """
    from app.context.examples import ESTIMATION_EXAMPLES

    examples_text = ""
    for idx, ex in enumerate(ESTIMATION_EXAMPLES, start=1):
        examples_text += f"\n--- EJEMPLO {idx} ---\n"
        examples_text += f"Resumen de la reunión del cliente:\n{ex['meeting_summary']}\n\n"
        examples_text += f"Estimación generada de referencia:\n{ex['estimation']}\n"

    return (
        "Eres un Arquitecto de Software y Estimador Técnico Senior experto en desarrollo ágil.\n"
        "Tu objetivo es analizar minuciosamente la transcripción de una reunión de requerimientos "
        "con un cliente y generar una estimación de software profesional, realista y estructurada.\n\n"
        "### CONTEXTO DE REFERENCIA (EJEMPLOS HISTÓRICOS):\n"
        "A continuación se presentan ejemplos reales de estimaciones previas que debes usar "
        "como estándar de calidad, formato, nivel de detalle y desglose técnico:\n"
        f"{examples_text}\n"
        "### INSTRUCCIONES DE FORMATO DE RESPUESTA:\n"
        "1. Estructura la respuesta usando Markdown claro y profesional.\n"
        "2. Incluye siempre:\n"
        "   - Título y Resumen Ejecutivo de la solución.\n"
        "   - Desglose detallado de tareas por categoría técnica (Backend, Frontend, UI/UX, "
        "QA/DevOps, Integraciones) con estimación de horas por tarea.\n"
        "   - Total acumulado de horas.\n"
        "   - Composición de equipo recomendada (roles y seniority).\n"
        "   - Duración estimada en semanas/meses.\n"
        "   - Riesgos técnicos o supuestos clave identificados.\n"
        "3. Sé coherente con la escala de tiempo y complejidad observada en los ejemplos."
    )


# --------------------------------------------------------------------------- #
# Wrapper de proveedores
# --------------------------------------------------------------------------- #

def call_openai(system: str, user: str, settings) -> Dict[str, Any]:
    """Llamada bloqueante a OpenAI con system y user como mensajes separados."""
    from openai import OpenAI

    if not settings.OPENAI_API_KEY:
        raise ValueError(
            "OPENAI_API_KEY no está configurada. Por favor define la variable en el archivo .env"
        )

    client = OpenAI(api_key=settings.OPENAI_API_KEY)
    response = client.chat.completions.create(
        model=settings.OPENAI_MODEL,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        temperature=0.3,
    )
    return {
        "text": response.choices[0].message.content or "",
        "model": settings.OPENAI_MODEL,
        "provider": "openai",
    }


def call_anthropic(system: str, user: str, settings) -> Dict[str, Any]:
    """Llamada bloqueante a Anthropic. El system va en su parámetro propio."""
    from anthropic import Anthropic

    if not settings.ANTHROPIC_API_KEY:
        raise ValueError(
            "ANTHROPIC_API_KEY no está configurada. Por favor define la variable en el archivo .env"
        )

    client = Anthropic(api_key=settings.ANTHROPIC_API_KEY)
    response = client.messages.create(
        model=settings.ANTHROPIC_MODEL,
        max_tokens=MAX_TOKENS,
        system=system,
        messages=[{"role": "user", "content": user}],
    )
    text = "".join(block.text for block in response.content if hasattr(block, "text"))
    return {
        "text": text,
        "model": settings.ANTHROPIC_MODEL,
        "provider": "anthropic",
    }


def stream_openai(system: str, user: str, settings) -> Iterator[str]:
    """Deltas de texto desde OpenAI."""
    from openai import OpenAI

    if not settings.OPENAI_API_KEY:
        raise ValueError("OPENAI_API_KEY no está configurada.")

    client = OpenAI(api_key=settings.OPENAI_API_KEY)
    stream = client.chat.completions.create(
        model=settings.OPENAI_MODEL,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        temperature=0.3,
        stream=True,
    )
    for chunk in stream:
        delta = chunk.choices[0].delta.content
        if delta:
            yield delta


def stream_anthropic(system: str, user: str, settings) -> Iterator[str]:
    """Deltas de texto desde Anthropic."""
    from anthropic import Anthropic

    if not settings.ANTHROPIC_API_KEY:
        raise ValueError("ANTHROPIC_API_KEY no está configurada.")

    client = Anthropic(api_key=settings.ANTHROPIC_API_KEY)
    with client.messages.stream(
        model=settings.ANTHROPIC_MODEL,
        max_tokens=MAX_TOKENS,
        system=system,
        messages=[{"role": "user", "content": user}],
    ) as stream:
        for text in stream.text_stream:
            yield text


def _resolve_provider(settings) -> str:
    provider = settings.LLM_PROVIDER.lower()
    if provider not in ("openai", "anthropic"):
        raise ValueError(
            f"Proveedor de LLM no soportado: '{provider}'. Usa 'openai' o 'anthropic'."
        )
    return provider


def _model_for(provider: str, settings) -> str:
    return settings.OPENAI_MODEL if provider == "openai" else settings.ANTHROPIC_MODEL


# --------------------------------------------------------------------------- #
# Orquestación
# --------------------------------------------------------------------------- #

async def generate_estimation(
    request: EstimationRequest,
    prompt_version: str = DEFAULT_VERSION,
) -> Dict[str, Any]:
    """Renderiza el prompt, consulta la caché y llama al proveedor configurado."""
    settings = get_settings()
    provider = _resolve_provider(settings)
    model = _model_for(provider, settings)

    system, user = render_estimation_prompt(request, version=prompt_version)

    cache = get_cache()
    key = cache.make_key(system, user, model, provider)
    hit = cache.get(key)
    if hit is not None:
        return {**hit, "prompt_version": prompt_version, "cached": True}

    started = time.perf_counter()
    if provider == "openai":
        result = call_openai(system, user, settings)
    else:
        result = call_anthropic(system, user, settings)
    elapsed = time.perf_counter() - started

    logger.info(
        "llm_call_completed",
        provider=provider,
        model=model,
        prompt_version=prompt_version,
        elapsed_s=round(elapsed, 3),
        response_chars=len(result["text"]),
    )

    cache.set(key, result)
    return {**result, "prompt_version": prompt_version, "cached": False}


def stream_estimation(
    request: EstimationRequest,
    prompt_version: str = DEFAULT_VERSION,
) -> Iterator[str]:
    """Versión en streaming. No cachea: el cuerpo se consume una sola vez."""
    settings = get_settings()
    provider = _resolve_provider(settings)

    system, user = render_estimation_prompt(request, version=prompt_version)

    logger.info(
        "llm_stream_started",
        provider=provider,
        model=_model_for(provider, settings),
        prompt_version=prompt_version,
    )

    if provider == "openai":
        yield from stream_openai(system, user, settings)
    else:
        yield from stream_anthropic(system, user, settings)
