"""Contrato estructurado de la estimación: reglas de negocio y euros."""

import pytest
from pydantic import ValidationError

from app.schemas import EstimationResult, cost_range_eur


def valid_payload(**overrides) -> dict:
    payload = {
        "summary": "Portal de reservas para hoteles pequeños.",
        "confidence_pct": 70,
        "phases": [
            {"name": "Backend", "hours_min": 100, "hours_max": 150,
             "confidence_pct": 70, "summary": "API de reservas y disponibilidad."},
            {"name": "Frontend", "hours_min": 80, "hours_max": 120,
             "confidence_pct": 65, "summary": "Buscador, ficha y checkout."},
        ],
        "total_hours_min": 180,
        "total_hours_max": 270,
        "total_duration_weeks": 8,
        "assumptions": ["Un único idioma"],
        "out_of_scope": ["Pagos online (fase 2)"],
    }
    payload.update(overrides)
    return payload


def test_valid_result_is_accepted():
    result = EstimationResult.model_validate(valid_payload())
    assert result.total_hours_max == 270


def test_phase_sum_must_match_total_min():
    with pytest.raises(ValidationError, match="suman 180 h"):
        EstimationResult.model_validate(valid_payload(total_hours_min=200))


def test_phase_sum_must_match_total_max():
    with pytest.raises(ValidationError, match="suman 270 h"):
        EstimationResult.model_validate(valid_payload(total_hours_max=300))


def test_phase_min_cannot_exceed_max():
    payload = valid_payload()
    payload["phases"][0]["hours_min"] = 200
    with pytest.raises(ValidationError, match="hours_min"):
        EstimationResult.model_validate(payload)


def test_low_confidence_requires_out_of_scope_prefix():
    with pytest.raises(ValidationError, match="Fuera de alcance:"):
        EstimationResult.model_validate(valid_payload(confidence_pct=20))
    ok = EstimationResult.model_validate(
        valid_payload(confidence_pct=20, summary="Fuera de alcance: descripción demasiado vaga.")
    )
    assert ok.confidence_pct == 20


def test_cost_is_computed_from_hours_and_rate():
    result = EstimationResult.model_validate(valid_payload())
    assert cost_range_eur(result, rate=50) == (9000, 13500)


def test_developer_style_phase_texts_fit_the_limits():
    """Con el tier developer el modelo escribe más: 100 y 900 caracteres caben."""
    payload = valid_payload()
    payload["phases"][0]["name"] = "n" * 100
    payload["phases"][0]["summary"] = "s" * 900
    assert EstimationResult.model_validate(payload).phases[0].name == "n" * 100
