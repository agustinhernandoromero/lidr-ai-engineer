"""Framework de evals mínimo: MetricResult + SchemaAdherenceMetric."""

from app.schemas import EstimationResult, Phase
from evals.metrics import MetricResult, SchemaAdherenceMetric, run_all_metrics
from tests.test_estimation_result import valid_payload


def test_valid_result_scores_one():
    result = EstimationResult.model_validate(valid_payload())
    metric = SchemaAdherenceMetric().evaluate(result)
    assert metric == MetricResult("schema_adherence", 1.0, True, "ok")


def test_regression_without_validators_is_caught():
    # model_construct salta los validadores: simula que un cambio futuro los quitó.
    phase = Phase.model_construct(
        name="A", hours_min=10, hours_max=5, confidence_pct=50, summary="xxxxxxxxxx"
    )
    broken = EstimationResult.model_construct(
        summary="Sin prefijo", confidence_pct=10, phases=[phase],
        total_hours_min=99, total_hours_max=5, total_duration_weeks=1,
        assumptions=[], out_of_scope=[],
    )
    metric = SchemaAdherenceMetric().evaluate(broken)
    assert metric.score == 0.0 and not metric.passed
    assert "suman" in metric.details and "Fuera de alcance:" in metric.details
    assert "hours_min > hours_max" in metric.details


def test_run_all_metrics_returns_one_result_per_metric():
    result = EstimationResult.model_validate(valid_payload())
    results = run_all_metrics([SchemaAdherenceMetric(), SchemaAdherenceMetric()], result)
    assert len(results) == 2 and all(r.passed for r in results)
