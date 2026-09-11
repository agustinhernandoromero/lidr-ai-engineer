"""LLM Service implementing Context-Augmented Generation (CAG) for software estimation."""

from typing import Any, Dict
from app.config import get_settings
from app.context.examples import ESTIMATION_EXAMPLES


def build_cag_system_prompt() -> str:
    """Build the system prompt injecting static historical examples (CAG pattern)."""
    examples_text = ""
    for idx, ex in enumerate(ESTIMATION_EXAMPLES, start=1):
        examples_text += f"\n--- EJEMPLO {idx} ---\n"
        examples_text += f"Resumen de la reunión del cliente:\n{ex['meeting_summary']}\n\n"
        examples_text += f"Estimación generada de referencia:\n{ex['estimation']}\n"

    system_prompt = (
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
        "   - Desglose detallado de tareas por categoría técnica (Backend, Frontend, UI/UX, QA/DevOps, Integraciones) con estimación de horas por tarea.\n"
        "   - Total acumulado de horas.\n"
        "   - Composición de equipo recomendada (roles y seniority).\n"
        "   - Duración estimada en semanas/meses.\n"
        "   - Riesgos técnicos o supuestos clave identificados.\n"
        "3. Sé coherente con la escala de tiempo y complejidad observada en los ejemplos de referencia."
    )
    return system_prompt


def call_openai(system_prompt: str, transcription: str, settings) -> Dict[str, Any]:
    """Call OpenAI API for estimation."""
    from openai import OpenAI

    if not settings.OPENAI_API_KEY:
        raise ValueError(
            "OPENAI_API_KEY no está configurada. Por favor define la variable en el archivo .env"
        )

    client = OpenAI(api_key=settings.OPENAI_API_KEY)
    response = client.chat.completions.create(
        model=settings.OPENAI_MODEL,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"Transcripción de la reunión:\n\n{transcription}"},
        ],
        temperature=0.3,
    )
    estimation_text = response.choices[0].message.content or ""
    return {
        "estimation": estimation_text,
        "model": settings.OPENAI_MODEL,
        "provider": "openai",
    }


def call_anthropic(system_prompt: str, transcription: str, settings) -> Dict[str, Any]:
    """Call Anthropic Claude API for estimation."""
    from anthropic import Anthropic

    if not settings.ANTHROPIC_API_KEY:
        raise ValueError(
            "ANTHROPIC_API_KEY no está configurada. Por favor define la variable en el archivo .env"
        )

    client = Anthropic(api_key=settings.ANTHROPIC_API_KEY)
    response = client.messages.create(
        model=settings.ANTHROPIC_MODEL,
        max_tokens=4000,
        system=system_prompt,
        messages=[
            {"role": "user", "content": f"Transcripción de la reunión:\n\n{transcription}"}
        ],
        temperature=0.3,
    )
    # Extract text from content blocks
    estimation_text = "".join(
        block.text for block in response.content if hasattr(block, "text")
    )
    return {
        "estimation": estimation_text,
        "model": settings.ANTHROPIC_MODEL,
        "provider": "anthropic",
    }


async def generate_estimation(transcription: str) -> Dict[str, Any]:
    """
    Generate software estimation from meeting transcription using CAG architecture.
    """
    settings = get_settings()
    system_prompt = build_cag_system_prompt()

    provider = settings.LLM_PROVIDER.lower()
    if provider == "openai":
        return call_openai(system_prompt, transcription, settings)
    elif provider == "anthropic":
        return call_anthropic(system_prompt, transcription, settings)
    else:
        raise ValueError(
            f"Proveedor de LLM no soportado: '{provider}'. Usa 'openai' o 'anthropic'."
        )
