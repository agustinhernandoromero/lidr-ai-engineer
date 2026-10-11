"""Guardrail de salida: añade "Fuera de alcance:" en vez de gastar un reintento."""

import json

from app.guardrails.output import enforce_scope
from app.schemas import OUT_OF_SCOPE_PREFIX, SUMMARY_MAX_CHARS
from app.services.structured_estimator import estimate_structured
from tests.helpers import FakeLLM, fake_result_json


def test_adds_prefix_when_confidence_is_low_and_undeclared():
    out = enforce_scope({"summary": "No hay datos suficientes.", "confidence_pct": 20})
    assert out["summary"] == f"{OUT_OF_SCOPE_PREFIX} No hay datos suficientes."


def test_leaves_confident_and_already_marked_answers_alone():
    confident = {"summary": "Estimación clara.", "confidence_pct": 30}
    marked = {"summary": f"{OUT_OF_SCOPE_PREFIX} falta alcance.", "confidence_pct": 10}
    assert enforce_scope(confident) is confident
    assert enforce_scope(marked) is marked


def test_never_exceeds_summary_limit():
    out = enforce_scope({"summary": "x" * SUMMARY_MAX_CHARS, "confidence_pct": 5})
    assert len(out["summary"]) == SUMMARY_MAX_CHARS
    assert out["summary"].startswith(OUT_OF_SCOPE_PREFIX)


def test_malformed_input_passes_through_for_the_validator():
    for data in ({"x": 1}, {"summary": 3, "confidence_pct": 5},
                 {"summary": "s", "confidence_pct": "bajo"}, ["no", "dict"]):
        assert enforce_scope(data) is data


def test_low_confidence_answer_needs_no_retry():
    low = json.loads(fake_result_json("Sin datos suficientes para estimar el alcance."))
    low["confidence_pct"] = 20
    llm = FakeLLM(structured_responses=[json.dumps(low)])
    result, meta = estimate_structured(
        llm, [{"role": "system", "content": "s"}, {"role": "user", "content": "u"}], max_retries=2
    )
    assert meta["attempts"] == 1
    assert result.summary.startswith(OUT_OF_SCOPE_PREFIX)
