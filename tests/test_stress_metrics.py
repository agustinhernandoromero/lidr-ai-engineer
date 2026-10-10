"""Métricas de estrés: presupuestos como contrato y deriva de memoria."""

from evals.stress.metrics import CostBudgetMetric, LatencyBudgetMetric, MemoryDriftMetric

SNAPSHOT = {
    "summary": "El cliente pidió un portal B2B; el presupuesto pasó a 80.000 €.",
    "anchors": [{"user": "El presupuesto está cerrado en 30.000 euros.", "rule": "budget_locked"}],
    "project_metadata": {"project_name": "Atlas", "assumed_team_size": None,
                         "mentioned_technologies": ["Odoo"], "agreed_scope": None},
    "history": [{"user": "Queremos una API", "assistant": "Estimación…"}],
}


def test_latency_budget_pass_fail_and_boundary():
    metric = LatencyBudgetMetric(budget_ms=20_000)
    assert metric.evaluate({"latency_ms": 15_000}).passed
    assert not metric.evaluate({"latency_ms": 25_000}).passed
    boundary = metric.evaluate({"latency_ms": 20_000})
    assert boundary.passed and boundary.score == 1.0


def test_cost_budget_pass_fail_and_boundary():
    metric = CostBudgetMetric(budget_usd=0.02)
    assert metric.evaluate({"cost_usd": 0.01}).passed
    failed = metric.evaluate({"cost_usd": 0.03})
    assert not failed.passed and failed.score == 0.0
    assert metric.evaluate({"cost_usd": 0.02}).passed


def test_memory_drift_finds_fact_case_insensitive_in_each_place():
    assert MemoryDriftMetric("atlas").evaluate(SNAPSHOT).passed       # metadata
    assert MemoryDriftMetric("30.000").evaluate(SNAPSHOT).passed      # anchors
    assert MemoryDriftMetric("80.000").evaluate(SNAPSHOT).passed      # summary
    result = MemoryDriftMetric("Flutter").evaluate(SNAPSHOT)
    assert not result.passed and "Flutter" in result.details


def test_memory_drift_window_only_counts_when_requested():
    assert not MemoryDriftMetric("API").evaluate(SNAPSHOT).passed
    assert MemoryDriftMetric("API", where=["window"]).evaluate(SNAPSHOT).passed


def test_memory_drift_with_empty_snapshot_fails_cleanly():
    assert not MemoryDriftMetric("Atlas").evaluate({}).passed
