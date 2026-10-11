"""Crítico del Actor-Critic-Boss: esquema, prompt y degradación (LLM falso, $0)."""

import pytest
from pydantic import ValidationError

from app.schemas import CriticFeedback, EstimationResult
from app.services.critic import REVISION_INTRO, review, revision_messages
from tests.helpers import ACCEPT_JSON, FakeLLM, critic_json, fake_result_json

DRAFT = EstimationResult.model_validate_json(fake_result_json("Estimación de Atlas. Stack: React."))
CONTEXT = dict(
    transcript="Recuérdame el presupuesto vigente de Atlas.",
    metadata={"project_name": "Atlas", "mentioned_technologies": ["React"]},
    anchors=[{"user": "El presupuesto está cerrado en 30.000 euros.", "rule": "presupuesto"}],
    summary="Atlas: portal B2B. Presupuesto corregido a 80.000 euros en el turno 8.",
    tier="pm",
)


def test_rehacer_requires_a_blocking_issue():
    with pytest.raises(ValidationError):
        CriticFeedback.model_validate_json(critic_json("rehacer", "menor"))
    CriticFeedback.model_validate_json(critic_json("rehacer", "menor", "mayor"))


def test_rechazar_requires_at_least_one_issue():
    with pytest.raises(ValidationError):
        CriticFeedback.model_validate_json(critic_json("rechazar"))


def test_aceptar_allows_minor_issues():
    CriticFeedback.model_validate_json(critic_json("aceptar", "menor"))


def test_review_sends_turn_memory_and_draft_to_the_critic():
    llm = FakeLLM(critic_responses=[critic_json("rehacer", "mayor")])
    feedback = review(llm, result=DRAFT, **CONTEXT)
    assert feedback.verdict == "rehacer" and feedback.issues[0].severity == "mayor"
    system, user = llm.critic_calls[0][0]["content"], llm.critic_calls[0][1]["content"]
    assert "auditor independiente" in system and "dato_superado" in system
    assert "Recuérdame el presupuesto vigente" in user
    assert "30.000" in user and "80.000" in user  # ancla vieja y resumen nuevo
    assert '"total_hours_min":100' in user.replace(" ", "")


def test_review_retries_invalid_json_then_accepts():
    llm = FakeLLM(critic_responses=["esto no es json", ACCEPT_JSON])
    assert review(llm, result=DRAFT, **CONTEXT).verdict == "aceptar"
    assert len(llm.critic_calls) == 2
    assert llm.critic_calls[1][-1]["content"].startswith("Tu JSON no cumple")


@pytest.mark.parametrize("llm", [
    FakeLLM(fail_critic=True),
    FakeLLM(critic_responses=["mal"] * 3),
])
def test_review_degrades_to_accept_with_zero_confidence(llm):
    feedback = review(llm, result=DRAFT, **CONTEXT)
    assert (feedback.verdict, feedback.issues, feedback.confidence_in_review) == ("aceptar", [], 0)


def test_revision_messages_carry_draft_and_issues():
    feedback = CriticFeedback.model_validate_json(critic_json("rehacer", "mayor"))
    assistant, user = revision_messages(DRAFT, feedback)
    assert assistant["role"] == "assistant" and '"phases"' in assistant["content"]
    assert user["role"] == "user" and user["content"].startswith(REVISION_INTRO)
    assert "[mayor] fase_desproporcionada (phases[0].hours_max)" in user["content"]
    assert "Separa backend y frontend." in user["content"]
