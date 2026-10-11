"""Golden dataset: carga, validación y coherencia con guardrails y tier ($0)."""

import json

import pytest
from pydantic import ValidationError

from app.guardrails.input import InputGuardrailViolation, check_input
from app.services.sessions import ProjectMetadata
from app.services.tier_resolver import resolve_tier
from evals.dataset import GoldenCase, load_dataset

CASES = load_dataset()
BY_ID = {c.id: c for c in CASES}
BASE = {"id": "caso-x", "transcript": "Portal de reservas para hoteles pequeños.",
        "project_type": "web_saas"}


def test_sixteen_valid_cases_with_unique_ids():
    assert len(CASES) == 16
    assert len(BY_ID) == 16


def test_two_cases_are_out_of_scope():
    assert sorted(c.id for c in CASES if c.expected_out_of_scope) == [
        "caso-05-fuera-vago", "caso-06-fuera-inyeccion"]


def test_range_with_min_above_max_is_rejected():
    with pytest.raises(ValidationError):
        GoldenCase.model_validate({**BASE, "expected_hours_range": [500, 100]})


def test_out_of_scope_case_cannot_carry_expectations():
    with pytest.raises(ValidationError):
        GoldenCase.model_validate({**BASE, "expected_out_of_scope": True,
                                   "expected_hours_range": [1, 2]})


def test_duplicate_ids_are_rejected(tmp_path):
    path = tmp_path / "d.json"
    path.write_text(json.dumps([BASE, BASE]), encoding="utf-8")
    with pytest.raises(ValueError, match="repetidos"):
        load_dataset(path)


def test_injection_case_is_blocked_and_the_rest_pass_the_guardrails():
    with pytest.raises(InputGuardrailViolation) as exc:
        check_input(BY_ID["caso-06-fuera-inyeccion"].transcript)
    assert exc.value.reason == "prompt_injection"
    for case in CASES:
        if case.id != "caso-06-fuera-inyeccion":
            check_input(case.transcript)  # sin falsos positivos (sin moderación: $0)


def test_expected_tier_matches_the_resolver_on_turn_one():
    for case in CASES:
        if case.expected_tier is None:
            continue
        tier, _ = resolve_tier(case.transcript, ProjectMetadata())
        if case.id == "caso-10-equipo-pequeno":
            # Limitación documentada: small_team_pm lee la memoria, vacía en el turno 1.
            assert tier.value == "default"
        else:
            assert tier.value == case.expected_tier, case.id


def test_medium_cases_accept_the_six_phases_the_prompt_allows():
    """El prompt session5/v2 pide entre 3 y 6 fases en medium: una respuesta obediente no puede fallar."""
    for case in CASES:
        if case.detail_level == "medium" and case.expected_phase_count_range:
            assert case.expected_phase_count_range[1] >= 6, case.id
