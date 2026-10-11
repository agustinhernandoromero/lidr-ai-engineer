"""Jefe del Actor-Critic-Boss (sesión 05): decide, no llama al LLM.

    actor → crítico → decisión
                       ├── aceptar                    → devolver el borrador
                       ├── rehacer y quedan rondas    → el actor rehace con la revisión
                       └── rechazar, o sin rondas     → sintetizar

Al no hacer llamadas propias, cada decisión se puede probar y reproducir a
partir de las entradas, y queda en ``BossTrace``.
"""

from __future__ import annotations

from typing import Callable

import structlog

from app.schemas import (
    LOW_CONFIDENCE_THRESHOLD,
    OUT_OF_SCOPE_PREFIX,
    SUMMARY_MAX_CHARS,
    ACBIteration,
    BossDecision,
    BossTrace,
    CriticFeedback,
    CriticVerdict,
    EstimationResult,
)

logger = structlog.get_logger()

Actor = Callable[[CriticFeedback | None], EstimationResult]
Critic = Callable[[EstimationResult], CriticFeedback]
CAVEATS_HEADER = "⚠ Revisión independiente con fallos pendientes:"


class Boss:
    def __init__(self, max_iterations: int = 2) -> None:
        if max_iterations < 1:
            raise ValueError("max_iterations debe ser al menos 1")
        self.max_iterations = max_iterations

    def run(self, actor: Actor, critic: Critic) -> tuple[EstimationResult, BossTrace]:
        iterations: list[ACBIteration] = []
        feedback: CriticFeedback | None = None
        previous: EstimationResult | None = None
        for index in range(self.max_iterations):
            try:
                current = actor(feedback)
            except Exception as exc:
                # En la ronda 1 no hay nada que salvar: el error sube como siempre.
                # Al rehacer, el borrador anterior es válido y ya está pagado.
                if previous is None or feedback is None:
                    raise
                logger.warning("boss_actor_failed_keeping_previous",
                               iteration=index + 1, error=str(exc)[:200])
                return synthesize(previous, feedback), BossTrace(
                    iterations=iterations, final_decision="sintetizar", iterations_run=index
                )
            previous = current
            review = critic(current)
            rounds_left = self.max_iterations - index - 1
            decision = self._decide(review.verdict, rounds_left)
            iterations.append(ACBIteration(
                iteration=index + 1,
                critic_verdict=review.verdict,
                critic_confidence=review.confidence_in_review,
                issues=[f"[{i.severity}] {i.category} @ {i.field_path}: {i.description}"
                        for i in review.issues],
                decision=decision,
            ))
            logger.info("boss_iteration", iteration=index + 1, verdict=review.verdict,
                        decision=decision, issues=len(review.issues))
            if decision == "rehacer":
                feedback = review
                continue
            final = current if decision == "aceptar" else synthesize(current, review)
            return final, BossTrace(
                iterations=iterations, final_decision=decision, iterations_run=index + 1
            )
        # La última ronda nunca decide "rehacer" (no quedan rondas), así que el
        # bucle siempre devuelve antes de llegar aquí.
        raise AssertionError("el jefe terminó sin decidir")

    @staticmethod
    def _decide(verdict: CriticVerdict, rounds_left: int) -> BossDecision:
        if verdict == "aceptar":
            return "aceptar"
        if verdict == "rehacer" and rounds_left > 0:
            return "rehacer"
        return "sintetizar"


def synthesize(draft: EstimationResult, feedback: CriticFeedback) -> EstimationResult:
    """Último borrador con los fallos pendientes delante y la confianza rebajada.

    Nunca una respuesta vacía: el aviso viaja en el resumen y en
    ``BossTrace.final_decision``. La confianza baja a la mitad con suelo en
    el umbral, pero nunca SUBE: un borrador que ya era "Fuera de alcance:"
    conserva su confianza y su prefijo, o el validador lo rechazaría.
    """
    lines = [f"- [{i.severity}] {i.category} ({i.field_path}): {i.description}"
             for i in feedback.issues] or ["- (sin detalle)"]
    block = f"{CAVEATS_HEADER}\n" + "\n".join(lines) + "\n\n"
    if draft.summary.startswith(OUT_OF_SCOPE_PREFIX):
        prefix = f"{OUT_OF_SCOPE_PREFIX} "
        body = draft.summary[len(OUT_OF_SCOPE_PREFIX):].lstrip()
    else:
        prefix, body = "", draft.summary
    confidence = min(draft.confidence_pct,
                     max(LOW_CONFIDENCE_THRESHOLD, draft.confidence_pct // 2))
    return draft.model_copy(update={
        "summary": (prefix + block + body)[:SUMMARY_MAX_CHARS],
        "confidence_pct": confidence,
    })
