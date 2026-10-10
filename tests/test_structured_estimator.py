"""Estimador estructurado: render a Markdown y bucle de reintento."""

import json

import pytest

from app.schemas import EstimationResult
from app.services.structured_estimator import (
    ESTIMATION_JSON_SCHEMA,
    StructuredOutputError,
    estimate_structured,
    render_markdown,
)
from tests.helpers import FakeLLM, fake_result_json
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


MESSAGES = [{"role": "system", "content": "Eres un estimador"},
            {"role": "user", "content": "Portal Hotelia en React"}]


def test_valid_json_on_first_attempt():
    result, meta = estimate_structured(FakeLLM(), MESSAGES, max_retries=2)
    assert "React" in result.summary
    assert meta["attempts"] == 1


def test_bad_sum_is_retried_with_the_error_and_then_accepted():
    llm = FakeLLM(structured_responses=[
        fake_result_json("Primera versión descuadrada.", total_min=90),
        fake_result_json("Segunda versión correcta."),
    ])
    result, meta = estimate_structured(llm, MESSAGES, max_retries=2)

    assert meta["attempts"] == 2
    assert result.summary == "Segunda versión correcta."
    retry_messages = llm.estimator_calls[1]
    assert retry_messages[-2]["role"] == "assistant"
    assert "suman 100 h" in retry_messages[-1]["content"]


def test_json_wrapped_in_fence_and_prose_is_accepted():
    llm = FakeLLM(structured_responses=["Aquí va:\n```json\n" + fake_result_json("Con valla.") + "\n```"])
    result, _ = estimate_structured(llm, MESSAGES, max_retries=0)
    assert result.summary == "Con valla."


def test_truncated_or_empty_output_exhausts_retries():
    llm = FakeLLM(structured_responses=['{"summary": "cortado', "   ", "nada"])
    with pytest.raises(StructuredOutputError, match="3 intentos"):
        estimate_structured(llm, MESSAGES, max_retries=2)
    assert len(llm.estimator_calls) == 3


def test_schema_sent_to_provider_is_the_transformed_estimation_schema():
    seen = {}

    class Spy(FakeLLM):
        def complete(self, messages, max_tokens=4000, json_schema=None):
            seen["schema"] = json_schema
            return super().complete(messages, max_tokens, json_schema)

    estimate_structured(Spy(), MESSAGES, max_retries=0)
    assert seen["schema"] is ESTIMATION_JSON_SCHEMA
    assert seen["schema"]["additionalProperties"] is False


def test_retry_message_names_the_failing_field():
    long_name = json.loads(fake_result_json("Nombre de fase larguísimo."))
    long_name["phases"][0]["name"] = "x" * 150
    llm = FakeLLM(structured_responses=[json.dumps(long_name), fake_result_json("Corregido.")])
    estimate_structured(llm, MESSAGES, max_retries=2)
    assert "phases.0.name" in llm.estimator_calls[1][-1]["content"]
