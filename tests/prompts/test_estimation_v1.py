"""Tests de la plantilla de estimación v1.

Son tests del template, no del modelo: no tocan ninguna API externa y deben
ejecutarse en milisegundos.
"""

import pytest

from app.prompts.loader import render_estimation_prompt
from app.schemas import (
    DetailLevel,
    EstimationRequest,
    OutputFormat,
    ProjectType,
    ReferenceProject,
)

DESCRIPTION = (
    "Plataforma web para que una red de gimnasios gestione altas de socios, "
    "reservas de clases y cobros mensuales por domiciliación bancaria."
)


def build_request(**overrides) -> EstimationRequest:
    """Petición base; cada test sobrescribe solo lo que le interesa."""
    defaults = dict(
        description=DESCRIPTION,
        project_type=ProjectType.WEB_SAAS,
        detail_level=DetailLevel.MEDIUM,
        output_format=OutputFormat.PHASES_TABLE,
    )
    defaults.update(overrides)
    return EstimationRequest(**defaults)


# --------------------------------------------------------------------------- #
# 1. La descripción llega literal al bloque <project_description>
# --------------------------------------------------------------------------- #

def test_description_is_wrapped_in_project_description_block():
    _, user = render_estimation_prompt(build_request())

    assert "<project_description>" in user
    assert "</project_description>" in user
    assert DESCRIPTION in user

    start = user.index("<project_description>")
    end = user.index("</project_description>")
    assert start < user.index(DESCRIPTION) < end


# --------------------------------------------------------------------------- #
# 2. El bloque condicional de output_format
# --------------------------------------------------------------------------- #

def test_phases_table_format_includes_its_keywords():
    system, _ = render_estimation_prompt(
        build_request(output_format=OutputFormat.PHASES_TABLE)
    )
    assert "phases_table" in system
    assert "confidence_pct" in system


def test_narrative_format_excludes_phases_table_keywords():
    system, _ = render_estimation_prompt(
        build_request(output_format=OutputFormat.NARRATIVE)
    )
    assert "phases_table" not in system
    assert "confidence_pct" not in system
    assert "sin tablas" in system


def test_line_items_format_lists_technical_categories():
    system, _ = render_estimation_prompt(
        build_request(output_format=OutputFormat.LINE_ITEMS)
    )
    assert "line_items" in system
    assert "phases_table" not in system


# --------------------------------------------------------------------------- #
# 3. El bloque condicional de detail_level
# --------------------------------------------------------------------------- #

def test_detailed_level_asks_for_assumptions_per_phase():
    system, _ = render_estimation_prompt(
        build_request(detail_level=DetailLevel.DETAILED)
    )
    assert "asunciones por fase" in system


def test_summary_level_omits_assumptions_instruction():
    system, _ = render_estimation_prompt(
        build_request(detail_level=DetailLevel.SUMMARY)
    )
    assert "asunciones por fase" not in system
    assert "No desgloses subtareas" in system


# --------------------------------------------------------------------------- #
# Extras: include de ejemplos, project_type, referencias y versionado
# --------------------------------------------------------------------------- #

def test_examples_are_included_in_system():
    system, _ = render_estimation_prompt(build_request())
    assert "Ejemplos de estimaciones bien formadas" in system
    assert "Portal de reservas" in system


def test_project_type_block_is_conditional():
    saas, _ = render_estimation_prompt(build_request(project_type=ProjectType.WEB_SAAS))
    pipeline, _ = render_estimation_prompt(
        build_request(project_type=ProjectType.DATA_PIPELINE)
    )
    assert "multi-tenancy" in saas
    assert "multi-tenancy" not in pipeline
    assert "idempotencia" in pipeline


def test_reference_projects_are_absent_when_not_provided():
    system, _ = render_estimation_prompt(build_request())
    assert "Proyectos de referencia" not in system


def test_reference_projects_are_rendered_when_provided():
    system, _ = render_estimation_prompt(
        build_request(
            reference_projects=[
                ReferenceProject(
                    name="Portal socios Club Norte",
                    summary="Altas, reservas y cobros para un club deportivo.",
                    total_hours=310,
                )
            ]
        )
    )
    assert "Proyectos de referencia" in system
    assert "Portal socios Club Norte" in system
    assert "310 h" in system


def test_v2_renders_and_differs_from_v1():
    request = build_request()
    v1_system, _ = render_estimation_prompt(request, version="v1")
    v2_system, _ = render_estimation_prompt(request, version="v2")

    assert v1_system != v2_system
    # El contrato de formato se mantiene entre versiones
    assert "phases_table" in v2_system
    # Los ejemplos sí cambian deliberadamente
    assert "Referencias de calibración" in v2_system


def test_unknown_version_raises_value_error():
    with pytest.raises(ValueError, match="Versión de prompt desconocida"):
        render_estimation_prompt(build_request(), version="v99")
