"""Estimador estructurado: render a Markdown y bucle de reintento."""

from app.schemas import EstimationResult
from app.services.structured_estimator import render_markdown
from tests.test_estimation_result import valid_payload

RESULT = EstimationResult.model_validate(valid_payload())


def test_phases_table_has_rows_totals_and_euros():
    md = render_markdown(RESULT, "phases_table", rate=50)
    assert "| Backend |" in md and "| Frontend |" in md
    assert "**180–270 h**" in md
    assert "9.000–13.500 €" in md
    assert "50 €/h" in md


def test_line_items_and_narrative_have_no_table():
    for fmt in ("line_items", "narrative"):
        md = render_markdown(RESULT, fmt, rate=50)
        assert "| Fase |" not in md
        assert "Backend" in md and "9.000–13.500 €" in md


def test_assumptions_and_out_of_scope_are_listed():
    md = render_markdown(RESULT, "phases_table", rate=50)
    assert "Un único idioma" in md
    assert "Pagos online (fase 2)" in md
