"""Métricas del golden dataset sobre un resultado y un caso esperado ($0)."""

import json

from app.schemas import EstimationResult
from evals.dataset import GoldenCase
from evals.metrics import GOLDEN_METRIC_NAMES, Outcome, run_golden_metrics
from tests.helpers import fake_result_json

CASE = GoldenCase.model_validate({
    "id": "caso-crm", "project_type": "web_saas",
    "transcript": "CRM B2B con React y PostgreSQL para el equipo comercial.",
    "expected_in_summary": ["CRM"], "expected_technologies_any_of": ["React", "Vue"],
    "expected_phase_count_range": [1, 3], "expected_hours_range": [50, 200],
    "expected_duration_weeks_range": [2, 8], "expected_tier": "default",
})
OUT_OF_SCOPE = GoldenCase.model_validate({
    "id": "caso-vago", "project_type": "web_saas",
    "transcript": "Algo con IA que ayude a la gente, no sabemos qué.",
    "expected_out_of_scope": True,
})


def result(summary="CRM comercial. Stack: React.", hours=(100, 150), weeks=4, confidence=70):
    data = json.loads(fake_result_json(summary, total_min=hours[0], total_max=hours[1]))
    data["phases"][0].update(hours_min=hours[0], hours_max=hours[1])
    data.update(total_duration_weeks=weeks, confidence_pct=confidence)
    return EstimationResult.model_validate(data)


def verdicts(case, outcome):
    return {m.name: m.passed for m in run_golden_metrics(case, outcome)}


def test_good_answer_passes_all_four_in_order():
    metrics = run_golden_metrics(CASE, Outcome("ok", result=result(), tier="default"))
    assert [m.name for m in metrics] == list(GOLDEN_METRIC_NAMES)
    assert all(m.passed for m in metrics)


def test_hours_outside_range_fail_with_detail():
    metrics = run_golden_metrics(CASE, Outcome("ok", result=result(hours=(100, 900)), tier="default"))
    hours = next(m for m in metrics if m.name == "hours_bounds")
    assert not hours.passed and "100–900 h fuera de [50, 200]" in hours.details


def test_weeks_and_phase_count_are_checked():
    assert not verdicts(CASE, Outcome("ok", result=result(weeks=20), tier="default"))["hours_bounds"]


def test_content_recall_is_case_insensitive_and_needs_one_technology():
    ok = Outcome("ok", result=result(summary="crm comercial con vue"), tier="default")
    assert verdicts(CASE, ok)["content_recall"]
    missing = Outcome("ok", result=result(summary="Portal genérico sin stack."), tier="default")
    assert not verdicts(CASE, missing)["content_recall"]


def test_wrong_tier_fails():
    assert not verdicts(CASE, Outcome("ok", result=result(), tier="executive"))["tier"]


def test_out_of_scope_case_passes_when_answer_declares_it():
    answer = result(summary="Fuera de alcance: falta información.", confidence=10)
    assert all(verdicts(OUT_OF_SCOPE, Outcome("ok", result=answer, tier="default")).values())
    plain = result(summary="Estimación normal de un proyecto.")
    assert not verdicts(OUT_OF_SCOPE, Outcome("ok", result=plain, tier="default"))["hours_bounds"]


def test_guardrail_block_passes_only_when_out_of_scope_was_expected():
    blocked = Outcome("bloqueado", guardrail_reason="prompt_injection")
    assert all(verdicts(OUT_OF_SCOPE, blocked).values())
    unexpected = verdicts(CASE, blocked)  # falso positivo del guardrail
    assert unexpected == {"schema_adherence": True, "hours_bounds": False,
                          "content_recall": False, "tier": False}


def test_error_fails_everything():
    assert not any(verdicts(CASE, Outcome("error")).values())


def recall_case(in_summary, techs=()):
    return GoldenCase.model_validate({
        "id": "caso-recall", "project_type": "internal_tool",
        "transcript": "Portal interno de incorporación de empleados con Okta.",
        "expected_in_summary": in_summary, "expected_technologies_any_of": list(techs),
    })


def test_recall_accepts_alternatives_for_a_term():
    case = recall_case([["incorporación", "onboarding"], ["RGPD", "GDPR"]])
    answer = result(summary="Portal de onboarding que cumple el GDPR.")
    assert verdicts(case, Outcome("ok", result=answer, tier="default"))["content_recall"]


def test_recall_ignores_accents():
    answer = result(summary="Portal de incorporacion de empleados.")
    assert verdicts(recall_case(["incorporación"]), Outcome("ok", result=answer))["content_recall"]


def test_recall_matches_whole_words_only():
    answer = result(summary="Plan de reactivación de clientes inactivos.")
    assert not verdicts(recall_case([], ["React"]), Outcome("ok", result=answer))["content_recall"]
