"""Wrapper de Anthropic (proveedor principal) y orquestación de la estimación.

El prompt ya no se construye aquí: vive en ``app/prompts/estimation/<version>/``
y lo renderiza el loader. Este módulo solo sabe hablar con Anthropic y, como
red de seguridad gratuita si Anthropic falla, con Gemini.
"""

from __future__ import annotations

import time
from typing import Any, Dict, Iterator, List

import structlog

from app.config import get_settings
from app.dependencies import get_cache, get_llm_wrapper
from app.prompts.loader import DEFAULT_VERSION, render_estimation_prompt
from app.schemas import EstimationRequest

logger = structlog.get_logger(__name__)

MAX_TOKENS = 4000

Messages = List[Dict[str, str]]


def _split_system(messages: Messages) -> tuple[str, Messages]:
    """Separa el system prompt del resto: ambos SDK lo reciben aparte."""
    system = "\n\n".join(m["content"] for m in messages if m["role"] == "system")
    chat = [m for m in messages if m["role"] != "system"]
    return system, chat


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

def call_anthropic(messages: Messages, settings, max_tokens: int = MAX_TOKENS) -> Dict[str, Any]:
    """Llamada bloqueante a Anthropic. El system va en su parámetro propio."""
    from anthropic import Anthropic

    if not settings.ANTHROPIC_API_KEY:
        raise ValueError(
            "ANTHROPIC_API_KEY no está configurada. Por favor define la variable en el archivo .env"
        )

    system, chat = _split_system(messages)
    client = Anthropic(api_key=settings.ANTHROPIC_API_KEY)
    response = client.messages.create(
        model=settings.ANTHROPIC_MODEL,
        max_tokens=max_tokens,
        system=system,
        messages=chat,
    )
    text = "".join(block.text for block in response.content if hasattr(block, "text"))
    return {
        "text": text,
        "model": settings.ANTHROPIC_MODEL,
        "provider": "anthropic",
    }


def call_gemini(messages: Messages, settings, max_tokens: int = MAX_TOKENS) -> Dict[str, Any]:
    """Llamada bloqueante a Gemini. Se usa solo como red de seguridad gratuita
    cuando Anthropic falla. Gemini llama ``model`` al rol ``assistant``.
    """
    from google import genai
    from google.genai import errors, types

    if not settings.GEMINI_API_KEY:
        raise ValueError(
            "GEMINI_API_KEY no está configurada. Por favor define la variable en el archivo .env"
        )

    system, chat = _split_system(messages)
    contents = [
        {
            "role": "model" if m["role"] == "assistant" else "user",
            "parts": [{"text": m["content"]}],
        }
        for m in chat
    ]

    client = genai.Client(api_key=settings.GEMINI_API_KEY)
    config = types.GenerateContentConfig(
        system_instruction=system,
        temperature=0.3,
        max_output_tokens=max_tokens,
    )

    # El tier gratuito de Gemini devuelve 503 "high demand" de forma intermitente
    # (~1 de cada 4 llamadas en pruebas reales). Al ser nuestra propia red de
    # seguridad, un único reintento tras 1s basta para absorber esos picos
    # puntuales sin añadir latencia relevante a un flujo que ya viene de un
    # fallo del proveedor principal.
    try:
        response = client.models.generate_content(
            model=settings.GEMINI_MODEL, contents=contents, config=config
        )
    except errors.ServerError:
        time.sleep(1)
        response = client.models.generate_content(
            model=settings.GEMINI_MODEL, contents=contents, config=config
        )

    return {
        "text": response.text or "",
        "model": settings.GEMINI_MODEL,
        "provider": "gemini",
    }


def stream_anthropic(messages: Messages, settings) -> Iterator[str]:
    """Deltas de texto desde Anthropic."""
    from anthropic import Anthropic

    if not settings.ANTHROPIC_API_KEY:
        raise ValueError("ANTHROPIC_API_KEY no está configurada.")

    system, chat = _split_system(messages)
    client = Anthropic(api_key=settings.ANTHROPIC_API_KEY)
    with client.messages.stream(
        model=settings.ANTHROPIC_MODEL,
        max_tokens=MAX_TOKENS,
        system=system,
        messages=chat,
    ) as stream:
        for text in stream.text_stream:
            yield text


# --------------------------------------------------------------------------- #
# Wrapper inyectable: punto único para hablar con los proveedores LLM
# --------------------------------------------------------------------------- #

class LLMWrapper:
    """Envuelve las llamadas a Anthropic, con fallback a Gemini.

    No guarda configuración en el constructor: cada método llama a
    ``get_settings()`` en el momento de usarla. Es deliberado — si guardara la
    configuración en ``__init__``, el singleton de ``get_llm_wrapper()``
    (``@lru_cache``) se quedaría pegado a la primera configuración que viera
    para siempre, lo que rompería los tests que mockean ``get_settings()``.
    """

    def complete(self, messages: Messages, max_tokens: int = MAX_TOKENS) -> Dict[str, Any]:
        """Llama a Anthropic; si falla, cae a Gemini (gratuito).

        ``messages`` usa el formato neutral ``{"role", "content"}`` con un
        mensaje ``system`` opcional al principio; cada proveedor lo traduce.
        """
        settings = get_settings()

        try:
            result = call_anthropic(messages, settings, max_tokens)
            return {**result, "fallback_used": False}
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "llm_primary_failed_falling_back",
                provider="anthropic",
                model=settings.ANTHROPIC_MODEL,
                error=str(exc),
            )
            result = call_gemini(messages, settings, max_tokens)
            return {**result, "fallback_used": True}

    def complete_stream(self, messages: Messages) -> Iterator[str]:
        """Streaming de Anthropic. Sin fallback (ver docstring de
        ``stream_estimation``) y sin cachear.
        """
        settings = get_settings()

        logger.info(
            "llm_stream_started",
            provider="anthropic",
            model=settings.ANTHROPIC_MODEL,
        )

        yield from stream_anthropic(messages, settings)


# --------------------------------------------------------------------------- #
# Orquestación
# --------------------------------------------------------------------------- #

async def generate_estimation(
    request: EstimationRequest,
    prompt_version: str = DEFAULT_VERSION,
) -> Dict[str, Any]:
    """Renderiza el prompt, consulta la caché y llama a Anthropic.

    Si Anthropic falla (rate limit, timeout, caída del servicio),
    ``LLMWrapper`` reintenta automáticamente con Gemini como red de
    seguridad gratuita. La respuesta de fallback deliberadamente NO se
    cachea: si se cacheara bajo la clave de Anthropic, seguiría sirviéndose
    durante el TTL aunque Anthropic ya se hubiera recuperado.
    """
    settings = get_settings()

    system, user = render_estimation_prompt(request, version=prompt_version)

    cache = get_cache()
    key = cache.make_key(system, user, settings.ANTHROPIC_MODEL, "anthropic")
    hit = cache.get(key)
    if hit is not None:
        return {**hit, "prompt_version": prompt_version, "cached": True, "fallback_used": False}

    llm = get_llm_wrapper()
    started = time.perf_counter()
    result = llm.complete(
        [{"role": "system", "content": system}, {"role": "user", "content": user}]
    )
    elapsed = time.perf_counter() - started

    logger.info(
        "llm_call_completed",
        provider=result["provider"],
        model=result["model"],
        prompt_version=prompt_version,
        elapsed_s=round(elapsed, 3),
        response_chars=len(result["text"]),
        fallback_used=result["fallback_used"],
    )

    if not result["fallback_used"]:
        cache.set(key, {"text": result["text"], "model": result["model"], "provider": result["provider"]})

    return {**result, "prompt_version": prompt_version, "cached": False}


def stream_estimation(
    request: EstimationRequest,
    prompt_version: str = DEFAULT_VERSION,
) -> Iterator[str]:
    """Versión en streaming. No cachea, y tampoco hace fallback a Gemini: si
    Anthropic falla a mitad de la respuesta, no hay forma limpia de
    reintentar sin mezclar texto de dos modelos en la misma respuesta.
    """
    system, user = render_estimation_prompt(request, version=prompt_version)
    llm = get_llm_wrapper()
    yield from llm.complete_stream(
        [{"role": "system", "content": system}, {"role": "user", "content": user}]
    )
