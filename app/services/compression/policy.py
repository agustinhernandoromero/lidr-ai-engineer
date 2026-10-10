"""Qué hacer con los turnos que salen de la ventana deslizante.

Para cada par expulsado (del más antiguo al más reciente):
1. Si el mensaje del cliente es un ancla, el par pasa literal a ``history.anchors``.
2. Si no, se acumula para el resumen.
Al final, si hay pares para resumir, una llamada al resumidor sustituye
``history.summary``. Idempotente: sin desbordamiento no hace nada.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import structlog

from app.services.compression.anchors import detect_anchor
from app.services.compression.summarizer import summarize
from app.services.sessions import Anchor, ConversationHistory

logger = structlog.get_logger(__name__)


@dataclass
class CompressionReport:
    evicted: int = 0
    anchors_promoted: list[str] = field(default_factory=list)
    summary_updated: bool = False


def compress(history: ConversationHistory, llm, *, summary_max_tokens: int) -> CompressionReport:
    overflow = history.pop_overflow()
    report = CompressionReport(evicted=len(overflow))
    if not overflow:
        return report

    to_summarize: list[tuple[str, str]] = []
    for user, assistant in overflow:
        rule = detect_anchor(user)
        if rule:
            history.anchors.append(Anchor(user=user, assistant=assistant, rule=rule))
            report.anchors_promoted.append(rule)
        else:
            to_summarize.append((user, assistant))

    if to_summarize:
        new_summary = summarize(llm, history.summary, to_summarize, summary_max_tokens)
        if new_summary:
            history.summary = new_summary
            report.summary_updated = True

    logger.info(
        "history_compressed",
        evicted=report.evicted,
        anchors_promoted=report.anchors_promoted,
        anchors_total=len(history.anchors),
        summary_updated=report.summary_updated,
        summary_chars=len(history.summary or ""),
    )
    return report
