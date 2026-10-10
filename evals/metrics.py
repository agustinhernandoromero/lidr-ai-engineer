"""Métricas deterministas sobre resultados del estimador.

Patrón común: cada métrica tiene ``name`` y ``evaluate(obj) -> MetricResult``.
Añadir una métrica nueva es escribir una clase con esas dos cosas; la sesión 6
añadirá LatencyBudget, CostBudget y MemoryDrift sobre este mismo patrón.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.schemas import LOW_CONFIDENCE_THRESHOLD, OUT_OF_SCOPE_PREFIX, EstimationResult


@dataclass
class MetricResult:
    name: str
    score: float
    passed: bool
    details: str


class SchemaAdherenceMetric:
    """Vuelve a comprobar las reglas de negocio de ``EstimationResult``.

    Los validadores de Pydantic ya las imponen; esta métrica existe para detectar
    si un cambio futuro los quita o los relaja (regresión silenciosa).
    """

    name = "schema_adherence"

    def evaluate(self, result: EstimationResult) -> MetricResult:
        problems: list[str] = []
        sum_min = sum(p.hours_min for p in result.phases)
        sum_max = sum(p.hours_max for p in result.phases)
        if sum_min != result.total_hours_min or sum_max != result.total_hours_max:
            problems.append(
                f"las fases suman {sum_min}–{sum_max} h y los totales dicen "
                f"{result.total_hours_min}–{result.total_hours_max} h"
            )
        for phase in result.phases:
            if phase.hours_min > phase.hours_max:
                problems.append(f"fase '{phase.name}': hours_min > hours_max")
        if (
            result.confidence_pct < LOW_CONFIDENCE_THRESHOLD
            and not result.summary.startswith(OUT_OF_SCOPE_PREFIX)
        ):
            problems.append(f"confianza {result.confidence_pct}% sin prefijo '{OUT_OF_SCOPE_PREFIX}'")

        passed = not problems
        return MetricResult(self.name, 1.0 if passed else 0.0, passed, "; ".join(problems) or "ok")


def run_all_metrics(metrics, obj) -> list[MetricResult]:
    return [metric.evaluate(obj) for metric in metrics]
