"""Detección de anclas: turnos que deben sobrevivir literales a la ventana.

Un turno es ancla cuando contiene un compromiso duradero que la conversación
no puede permitirse olvidar: contratos firmados, confidencialidad, alcance o
presupuesto cerrados, normativa, fechas inamovibles. El detector es
conservador a propósito: un falso negativo solo manda el turno al resumen; un
falso positivo infla el prompt para siempre, porque las anclas no se expulsan.

Heurístico (regex, sin LLM), en español e inglés.
"""

from __future__ import annotations

import re

_FLAGS = re.IGNORECASE

_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("nda", re.compile(
        r"\b(nda|non[- ]?disclosure|acuerdo de confidencialidad|bajo embargo|under embargo|legal hold)\b",
        _FLAGS)),
    ("signed_contract", re.compile(
        r"\b(hemos firmado|firmamos|ha firmado|han firmado)\s+(el|la|un|una)?\s*(contrato|sow|msa|acuerdo|propuesta)\b"
        r"|\b(contrato|sow|msa)\s+(ya\s+)?firmado\b"
        r"|\b(signed|countersigned)\s+(the\s+)?(contract|sow|msa|agreement)\b",
        _FLAGS)),
    ("scope_frozen", re.compile(
        r"\b(alcance|backlog)\s+(est[áa]\s+|queda\s+)?(cerrado|congelado|bloqueado|fijado|definitivo)\b"
        r"|\b(scope|backlog)\s+(is\s+)?(frozen|locked|final|fixed)\b",
        _FLAGS)),
    ("budget_locked", re.compile(
        r"\bpresupuesto\s+(est[áa]\s+|queda\s+)?(cerrado|aprobado|bloqueado|fijado|congelado)\b"
        r"|\btope\s+de\s+presupuesto\b|\bpresupuesto\s+m[áa]ximo\b"
        r"|\b(budget|cap|ceiling)\s+(is\s+)?(locked|fixed|approved|capped)\s+at\b",
        _FLAGS)),
    ("compliance", re.compile(
        r"\b(rgpd|gdpr|lopdgdd|hipaa|sox|pci[- ]?dss|iso[- ]?27001|ens)\b",
        _FLAGS)),
    ("deadline_hard", re.compile(
        r"\bfecha\s+l[íi]mite\s+(es\s+)?(inamovible|innegociable|fija)\b"
        r"|\b(tiene|tienen|debe|deben)\s+(que\s+)?estar\s+en\s+producci[óo]n\s+antes\s+de\b"
        r"|\bhard\s+deadline\b|\bmust\s+go\s+live\s+by\b",
        _FLAGS)),
    ("explicit_commitment", re.compile(
        r"\b(el\s+cliente|la\s+empresa)\s+se\s+compromete\b|\bnos\s+comprometemos\b|\bhemos\s+acordado\b"
        r"|\b(we|the\s+(client|customer))\s+(agreed|committed)\s+to\b",
        _FLAGS)),
)


def detect_anchor(text: str) -> str | None:
    """Nombre de la primera regla que encaja, o ``None`` si no es un ancla."""
    for name, pattern in _PATTERNS:
        if pattern.search(text or ""):
            return name
    return None
