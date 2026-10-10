"""Métricas de estrés sobre la observación de un turno y el snapshot de la sesión.

Viven aparte de ``evals/metrics.py`` porque no evalúan un ``EstimationResult``
sino la forma de ``turn_observed`` y de ``GET /sessions/{id}``. Reutilizan el
mismo ``MetricResult``. Deterministas: coincidencia exacta sin mayúsculas, sin
embeddings ni LLM-as-judge. Los presupuestos convierten el SLA en un test.
"""

from __future__ import annotations

import json

from evals.metrics import MetricResult

DEFAULT_WHERE = ["summary", "anchors", "metadata"]


def snapshot_text(snapshot: dict, where: list[str]) -> dict[str, str]:
    parts: dict[str, str] = {}
    if "summary" in where:
        parts["summary"] = snapshot.get("summary") or ""
    if "anchors" in where:
        parts["anchors"] = "\n".join(a.get("user", "") for a in snapshot.get("anchors") or [])
    if "metadata" in where:
        parts["metadata"] = json.dumps(snapshot.get("project_metadata") or {}, ensure_ascii=False)
    if "window" in where:
        parts["window"] = "\n".join(
            f"{t.get('user', '')}\n{t.get('assistant', '')}" for t in snapshot.get("history") or []
        )
    return parts


class LatencyBudgetMetric:
    """1.0 si ``latency_ms`` ≤ presupuesto; 0.0 si no."""

    name = "latency_budget"

    def __init__(self, budget_ms: int) -> None:
        self.budget_ms = budget_ms

    def evaluate(self, observation: dict) -> MetricResult:
        latency = float(observation.get("latency_ms") or 0)
        passed = latency <= self.budget_ms
        return MetricResult(
            self.name, 1.0 if passed else 0.0, passed,
            f"{latency:.0f} ms (presupuesto {self.budget_ms} ms)",
        )


class CostBudgetMetric:
    """1.0 si ``cost_usd`` ≤ presupuesto; 0.0 si no."""

    name = "cost_budget"

    def __init__(self, budget_usd: float) -> None:
        self.budget_usd = budget_usd

    def evaluate(self, observation: dict) -> MetricResult:
        cost = float(observation.get("cost_usd") or 0)
        passed = cost <= self.budget_usd
        return MetricResult(
            self.name, 1.0 if passed else 0.0, passed,
            f"${cost:.4f} (presupuesto ${self.budget_usd:.4f})",
        )


class MemoryDriftMetric:
    """1.0 si el hecho declarado en el turno k aparece en el snapshot del turno N > k."""

    name = "memory_drift"

    def __init__(self, fact: str, where: list[str] | None = None) -> None:
        self.fact = fact
        self.where = where or list(DEFAULT_WHERE)

    def evaluate(self, snapshot: dict) -> MetricResult:
        needle = self.fact.lower()
        found = [
            place for place, text in snapshot_text(snapshot, self.where).items()
            if needle in text.lower()
        ]
        passed = bool(found)
        detail = f"'{self.fact}' en {', '.join(found)}" if found else f"'{self.fact}' no aparece"
        return MetricResult(self.name, 1.0 if passed else 0.0, passed, detail)
