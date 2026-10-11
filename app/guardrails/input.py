"""Guardrails de entrada (sesión 04): se ejecutan antes de llamar al LLM.

Tres capas, de la gratis a la de pago, para que un texto que se va a
rechazar igualmente no pague la moderación:

1. Inyección de prompt: reglas fijas en español e inglés.
2. Datos personales (email, IBAN, teléfono): reglas fijas, conservadoras
   para no confundir cifras de presupuesto con teléfonos.
3. Moderación: una llamada corta a Haiku. Falla abierto: si la llamada o
   su JSON fallan, se registra y se deja pasar.

Política ``exception``: cualquier violación lanza ``InputGuardrailViolation``
y el router la convierte en 400 con ``{reason, message}``.
"""

from __future__ import annotations

import json
import re
from typing import Literal

import anthropic
import structlog
from pydantic import BaseModel, Field

logger = structlog.get_logger()

Reason = Literal["prompt_injection", "pii", "moderation"]


class InputGuardrailViolation(Exception):
    """Un guardrail de entrada rechazó el texto; ``reason`` decide el mensaje al usuario."""

    def __init__(self, reason: Reason, message: str) -> None:
        super().__init__(message)
        self.reason: Reason = reason
        self.message = message

    def detail(self) -> dict[str, str]:
        return {"reason": self.reason, "message": self.message}


_FLAGS = re.IGNORECASE | re.DOTALL
# Solo cuenta como inyección si lo que se pide olvidar o ignorar son
# instrucciones, reglas o prompts, o si se impone un rol nuevo: "Olvida lo
# anterior: el presupuesto es 80.000" es una corrección normal del cliente.
_INJECTION_PATTERNS = [re.compile(p, _FLAGS) for p in (
    # Español
    r"\bignora(?:r)?\s+(?:todas\s+)?(?:las\s+)?(?:instrucciones|indicaciones|reglas)\s+(?:anteriores|previas)",
    r"\bolvida\s+(?:todas\s+)?(?:las\s+|tus\s+)(?:instrucciones|indicaciones|reglas)\b",
    r"\bahora\s+eres\s+(?:un|una)\b",
    r"\bnuevas\s+instrucciones\s*[:.\-]",
    r"\b(?:no\s+hagas\s+caso|haz\s+caso\s+omiso)\s+(?:de|a)\s+(?:las\s+)?(?:instrucciones|reglas)",
    # Inglés
    r"\bignore\s+(?:previous|prior|all|the)\s+(?:instructions?|prompts?|rules?)",
    r"\bforget\s+(?:everything\s+(?:you|above|before)\b"
    r"|(?:all\s+)?(?:your|the|previous|prior)\s+(?:instructions?|rules?|prompts?))",
    r"\byou\s+are\s+now\s+(?:a|an|my|the)\b",
    r"\bnew\s+instructions?\s*[:.\-]",
    r"\bdisregard\b.{0,40}\b(?:instructions?|prompts?|rules?)\b",
    # Etiquetas que imitan la estructura del prompt
    r"</?\s*(?:system|instructions?|prompt)\s*>",
)]

_EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_IBAN = re.compile(r"\b[A-Z]{2}\d{2}(?:\s?[A-Z0-9]{4}){3,7}\b")
# Teléfono: con prefijo internacional, o español de 9 cifras que empieza por
# 6/7/8/9 en sus formatos habituales (612345678, 612 345 678, 612 34 56 78,
# 91 234 56 78), con el MISMO separador en todo el número y nunca el punto:
# así "8.000-12.000 horas" o "800.000.000 registros" no parecen teléfonos.
_PHONE = re.compile(
    r"\+\d{1,3}[\s.-]?\d(?:[\s.-]?\d){7,11}"
    r"|(?<![\d.,-])\b(?:"
    r"[6789]\d{2}([ -]?)\d{3}\1\d{3}"
    r"|[6789]\d{2}([ -]?)\d{2}\2\d{2}\2\d{2}"
    r"|[89]\d([ -]?)\d{3}\3\d{2}\3\d{2}"
    r")\b(?![.,-]?\d)"
)
_PII = [(_EMAIL, "un email"), (_IBAN, "un IBAN"), (_PHONE, "un teléfono")]

MODERATION_SYSTEM = (
    "Eres un moderador de contenido para un servicio que estima proyectos de software. "
    "Marca flagged=true solo si el texto contiene odio, acoso, violencia, contenido sexual, "
    "autolesiones o la petición de ayudar en actividades ilegales, e indica las categorías "
    "en español. Una descripción normal de un proyecto de software NO se marca, aunque hable "
    "de seguridad, pagos, datos médicos o de un videojuego con combates."
)
MODERATION_MAX_TOKENS = 100


class ModerationVerdict(BaseModel):
    flagged: bool
    categories: list[str] = Field(default_factory=list)


MODERATION_JSON_SCHEMA = anthropic.transform_schema(ModerationVerdict.model_json_schema())


def check_input(text: str, *, llm=None, moderation_enabled: bool = True) -> None:
    """Lanza ``InputGuardrailViolation`` en la primera capa que rechace el texto."""
    try:
        _check_injection(text)
        _check_pii(text)
        if llm is not None and moderation_enabled:
            _check_moderation(text, llm)
    except InputGuardrailViolation as exc:
        # Sin el texto: podría llevar justo los datos personales que se rechazan.
        logger.info("input_guardrail_blocked", reason=exc.reason)
        raise


def _check_injection(text: str) -> None:
    for pattern in _INJECTION_PATTERNS:
        match = pattern.search(text)
        if match:
            raise InputGuardrailViolation(
                "prompt_injection",
                f"El mensaje contiene texto que parece una instrucción para el sistema "
                f"(«{match.group(0)[:80]}»). Quítalo y vuelve a enviarlo.",
            )


def _check_pii(text: str) -> None:
    for pattern, what in _PII:
        if pattern.search(text):
            raise InputGuardrailViolation(
                "pii",
                f"El texto incluye {what}. Quita los datos personales y vuelve a enviarlo.",
            )


def _check_moderation(text: str, llm) -> None:
    # Import diferido: structured_estimator importa el guardrail de salida y
    # este módulo solo necesita su recorte de JSON.
    from app.services.structured_estimator import _json_slice

    try:
        out = llm.complete(
            [
                {"role": "system", "content": MODERATION_SYSTEM},
                {"role": "user", "content": f"<texto>\n{text}\n</texto>"},
            ],
            max_tokens=MODERATION_MAX_TOKENS,
            json_schema=MODERATION_JSON_SCHEMA,
        )
        verdict = ModerationVerdict.model_validate(json.loads(_json_slice(out["text"] or "")))
    except Exception as exc:  # noqa: BLE001 — falla abierto: moderar no puede tumbar el servicio
        logger.warning("moderation_failed", error=str(exc)[:200])
        return
    if verdict.flagged:
        categories = ", ".join(verdict.categories) or "sin categoría"
        raise InputGuardrailViolation(
            "moderation",
            f"El texto incluye contenido no permitido ({categories}). "
            "Reformúlalo y vuelve a enviarlo.",
        )
