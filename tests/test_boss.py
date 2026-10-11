"""Jefe del Actor-Critic-Boss: código puro, sin LLM."""

import pytest

from app.schemas import (
    LOW_CONFIDENCE_THRESHOLD,
    OUT_OF_SCOPE_PREFIX,
    SUMMARY_MAX_CHARS,
    CriticFeedback,
    EstimationResult,
)
from app.services.boss import CAVEATS_HEADER, Boss, synthesize
from tests.helpers import ACCEPT_JSON, critic_json, fake_result_json

ACCEPT = CriticFeedback.model_validate_json(ACCEPT_JSON)
REHACER = CriticFeedback.model_validate_json(critic_json("rehacer", "mayor"))
RECHAZAR = CriticFeedback.model_validate_json(critic_json("rechazar", "critica"))


def draft(n: int, confidence: int = 70) -> EstimationResult:
    summary = f"Borrador {n} de la estimación."
    if confidence < LOW_CONFIDENCE_THRESHOLD:
        summary = f"{OUT_OF_SCOPE_PREFIX} {summary}"
    data = EstimationResult.model_validate_json(fake_result_json(summary)).model_dump()
    return EstimationResult.model_validate({**data, "confidence_pct": confidence})


class Script:
    """Actor y crítico guionizados; graban lo que reciben."""

    def __init__(self, reviews):
        self.reviews = list(reviews)
        self.feedback_seen = []
        self.drafts = 0

    def actor(self, feedback):
        self.feedback_seen.append(feedback)
        self.drafts += 1
        return draft(self.drafts)

    def critic(self, result):
        return self.reviews.pop(0)


def test_accepts_first_draft():
    s = Script([ACCEPT])
    result, trace = Boss(max_iterations=2).run(s.actor, s.critic)
    assert result.summary == "Borrador 1 de la estimación."
    assert (trace.final_decision, trace.iterations_run) == ("aceptar", 1)
    assert s.feedback_seen == [None]


def test_iterates_with_feedback_then_accepts():
    s = Script([REHACER, ACCEPT])
    result, trace = Boss(max_iterations=2).run(s.actor, s.critic)
    assert result.summary == "Borrador 2 de la estimación."
    assert [i.decision for i in trace.iterations] == ["rehacer", "aceptar"]
    assert s.feedback_seen == [None, REHACER]
    assert trace.iterations[0].issues == [
        "[mayor] fase_desproporcionada @ phases[0].hours_max: "
        "La fase de desarrollo concentra todo el esfuerzo."
    ]


def test_reject_synthesizes_without_another_round():
    s = Script([RECHAZAR])
    result, trace = Boss(max_iterations=2).run(s.actor, s.critic)
    assert (trace.final_decision, trace.iterations_run, s.drafts) == ("sintetizar", 1, 1)
    assert result.summary.startswith(CAVEATS_HEADER)


def test_critic_that_never_accepts_is_capped():
    s = Script([REHACER] * 5)
    result, trace = Boss(max_iterations=2).run(s.actor, s.critic)
    assert (s.drafts, trace.iterations_run, trace.final_decision) == (2, 2, "sintetizar")
    assert [i.decision for i in trace.iterations] == ["rehacer", "sintetizar"]
    assert result.confidence_pct == 35  # 70 // 2


def test_needs_at_least_one_iteration():
    with pytest.raises(ValueError):
        Boss(max_iterations=0)


def test_synthesis_keeps_out_of_scope_prefix_and_low_confidence():
    low = draft(1, confidence=20)
    out = synthesize(low, REHACER)
    assert out.summary.startswith(f"{OUT_OF_SCOPE_PREFIX} {CAVEATS_HEADER}")
    assert out.confidence_pct == 20  # nunca sube hasta el umbral
    EstimationResult.model_validate(out.model_dump())  # sigue cumpliendo el esquema


def test_synthesis_respects_summary_limit_and_floor():
    long = draft(1, confidence=40).model_copy(update={"summary": "y" * SUMMARY_MAX_CHARS})
    out = synthesize(long, REHACER)
    assert len(out.summary) <= SUMMARY_MAX_CHARS
    assert out.confidence_pct == LOW_CONFIDENCE_THRESHOLD  # 40 // 2 = 20 → suelo 30
    EstimationResult.model_validate(out.model_dump())
