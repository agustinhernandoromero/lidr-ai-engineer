"""Métricas deterministas sobre resultados del estimador (y sobre el golden dataset).

Patrón común: cada métrica tiene ``name`` y ``evaluate(obj) -> MetricResult``.
Añadir una métrica nueva es escribir una clase con esas dos cosas; la sesión 6
añadirá LatencyBudget, CostBudget y MemoryDrift sobre este mismo patrón. Las
del golden dataset reciben además el caso esperado: ``evaluate(case, outcome)``.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

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


# --------------------------------------------------------------------------- #
# Golden dataset: la métrica compara la respuesta con lo que se esperaba
# --------------------------------------------------------------------------- #

if TYPE_CHECKING:
    from evals.dataset import GoldenCase

GOLDEN_METRIC_NAMES = ("schema_adherence", "hours_bounds", "content_recall", "tier")


@dataclass
class Outcome:
    """Lo que devolvió el servicio para un caso: respuesta, bloqueo de guardrail o error."""

    status: Literal["ok", "bloqueado", "error"]
    result: EstimationResult | None = None
    tier: str | None = None
    guardrail_reason: str | None = None


def _verdict(name: str, passed: bool, details: str) -> MetricResult:
    return MetricResult(name, 1.0 if passed else 0.0, passed, details)


def _not_answered(name: str, case: GoldenCase, outcome: Outcome) -> MetricResult | None:
    """Bloqueo o error: solo cuenta como acierto un bloqueo de un caso fuera de alcance."""
    if outcome.status == "error":
        return _verdict(name, False, "la petición falló")
    if outcome.status == "bloqueado":
        expected = case.expected_out_of_scope
        return _verdict(name, expected, f"bloqueado por el guardrail ({outcome.guardrail_reason})"
                        + ("" if expected else " y no se esperaba"))
    return None


class _GoldenSchemaMetric:
    name = "schema_adherence"

    def evaluate(self, case: GoldenCase, outcome: Outcome) -> MetricResult:
        if outcome.status == "bloqueado":
            return _verdict(self.name, True, "sin respuesta del LLM que validar")
        if outcome.status == "error" or outcome.result is None:
            return _verdict(self.name, False, "la petición falló")
        return SchemaAdherenceMetric().evaluate(outcome.result)


class HoursBoundsMetric:
    """Horas, semanas y número de fases dentro de los rangos del caso."""

    name = "hours_bounds"

    def evaluate(self, case: GoldenCase, outcome: Outcome) -> MetricResult:
        early = _not_answered(self.name, case, outcome)
        if early is not None or outcome.result is None:
            return early or _verdict(self.name, False, "sin resultado")
        r = outcome.result
        if case.expected_out_of_scope:
            declared = r.summary.startswith(OUT_OF_SCOPE_PREFIX)
            return _verdict(self.name, declared, "declarada fuera de alcance" if declared
                            else f"se esperaba '{OUT_OF_SCOPE_PREFIX}'")
        problems: list[str] = []
        if case.expected_phase_count_range:
            lo, hi = case.expected_phase_count_range
            if not lo <= len(r.phases) <= hi:
                problems.append(f"{len(r.phases)} fases fuera de [{lo}, {hi}]")
        if case.expected_hours_range:
            lo, hi = case.expected_hours_range
            if r.total_hours_min < lo or r.total_hours_max > hi:
                problems.append(f"{r.total_hours_min}–{r.total_hours_max} h fuera de [{lo}, {hi}]")
        if case.expected_duration_weeks_range:
            lo, hi = case.expected_duration_weeks_range
            if not lo <= r.total_duration_weeks <= hi:
                problems.append(f"{r.total_duration_weeks} semanas fuera de [{lo}, {hi}]")
        return _verdict(self.name, not problems, "; ".join(problems) or "dentro de rango")


class ContentRecallMetric:
    """La respuesta menciona lo que le importaba al cliente (sin mayúsculas)."""

    name = "content_recall"

    def evaluate(self, case: GoldenCase, outcome: Outcome) -> MetricResult:
        early = _not_answered(self.name, case, outcome)
        if early is not None or outcome.result is None:
            return early or _verdict(self.name, False, "sin resultado")
        if case.expected_out_of_scope:
            return _verdict(self.name, True, "no aplica: caso fuera de alcance")
        r = outcome.result
        haystack = _fold(" ".join(
            [r.summary, *r.assumptions, *(f"{p.name} {p.summary}" for p in r.phases)]
        ))
        problems: list[str] = []
        for term in case.expected_in_summary:
            options = [term] if isinstance(term, str) else term
            if not any(_mentions(haystack, o) for o in options):
                problems.append(f"falta '{' / '.join(options)}'")
        techs = case.expected_technologies_any_of
        if techs and not any(_mentions(haystack, t) for t in techs):
            problems.append(f"no menciona ninguna de {techs}")
        return _verdict(self.name, not problems, "; ".join(problems) or "contenido presente")


def _fold(text: str) -> str:
    """Minúsculas y sin acentos: "Incorporación" e "incorporacion" cuentan igual."""
    decomposed = unicodedata.normalize("NFKD", text.lower())
    return "".join(c for c in decomposed if not unicodedata.combining(c))


def _mentions(haystack: str, term: str) -> bool:
    # Palabra completa: "React" no debe contar dentro de "reactivación".
    return re.search(rf"(?<!\w){re.escape(_fold(term))}(?!\w)", haystack) is not None


class TierMetric:
    name = "tier"

    def evaluate(self, case: GoldenCase, outcome: Outcome) -> MetricResult:
        early = _not_answered(self.name, case, outcome)
        if early is not None:
            return early
        if case.expected_out_of_scope or case.expected_tier is None:
            return _verdict(self.name, True, "no aplica")
        ok = outcome.tier == case.expected_tier
        return _verdict(self.name, ok, f"tier {outcome.tier}"
                        + ("" if ok else f", se esperaba {case.expected_tier}"))


_GOLDEN_METRICS = (_GoldenSchemaMetric(), HoursBoundsMetric(), ContentRecallMetric(), TierMetric())


def run_golden_metrics(case: GoldenCase, outcome: Outcome) -> list[MetricResult]:
    return [metric.evaluate(case, outcome) for metric in _GOLDEN_METRICS]
