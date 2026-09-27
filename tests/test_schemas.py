"""Tests de validación de EstimationRequest."""

import pytest
from pydantic import ValidationError

from app.schemas import DetailLevel, EstimationRequest, OutputFormat, ProjectType

BASE = dict(
    project_type=ProjectType.WEB_SAAS,
    detail_level=DetailLevel.MEDIUM,
    output_format=OutputFormat.PHASES_TABLE,
)


def test_description_rejects_too_short():
    with pytest.raises(ValidationError):
        EstimationRequest(description="muy corta", **BASE)


def test_description_accepts_long_meeting_transcript():
    """Una transcripción real de reunión (más larga que los 2000 caracteres
    del límite anterior) debe caber en el contrato."""
    transcript = "Notas de la reunión de requerimientos. " * 400  # ~16.000 chars
    request = EstimationRequest(description=transcript, **BASE)
    assert request.description == transcript


def test_description_rejects_over_20000_chars():
    with pytest.raises(ValidationError):
        EstimationRequest(description="a" * 20_001, **BASE)
