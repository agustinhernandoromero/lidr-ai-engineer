"""Session 11: grounded estimator with a scripted LLM and an in-memory repository."""

import json
from types import SimpleNamespace

import pytest

from app.generation.citations import verify_citations
from app.generation.generator import (
    GroundedOutputError,
    generate_grounded_estimate,
    render_answer_text,
    run_grounded_estimation,
    source_id,
)
from app.generation.schemas import GroundedEstimate
from app.retrieval.types import RetrievedChunk
from tests.retrieval_fakes import FakeBranchesRepository

KYC_TEXT = "Component: KYC verification\nEstimated hours: 90"
SCORING_TEXT = "Component: Credit scoring engine\nEstimated hours: 160"


def chunk(chunk_id: int, budget_id: str, component_id: str, content: str) -> RetrievedChunk:
    return RetrievedChunk(
        id=chunk_id,
        document_id=chunk_id,
        chunk_type="budget_component",
        content=content,
        metadata={"budget_id": budget_id, "component_id": component_id},
    )


def row(chunk_id: int, budget_id: str, component_id: str, content: str, **score) -> SimpleNamespace:
    return SimpleNamespace(
        id=chunk_id,
        document_id=chunk_id,
        chunk_type="budget_component",
        content=content,
        metadata_={"budget_id": budget_id, "component_id": component_id},
        **score,
    )


def line(component, hours, grounded, *chunk_ids, evidence="Estimated hours: 90"):
    return {
        "component": component,
        "hours": hours,
        "rationale": "Taken from the cited budget.",
        "grounded": grounded,
        "sources": [
            {"chunk_id": cid, "document_id": cid.split("::")[0], "evidence": evidence} for cid in chunk_ids
        ],
    }


def payload(*lines) -> str:
    return json.dumps({"summary": "Loan platform with KYC and scoring.", "line_items": list(lines)})


class ScriptedLLM:
    """Returns the queued texts in order and records the messages of each call."""

    def __init__(self, *texts: str):
        self.texts = list(texts)
        self.calls: list[list[dict]] = []

    def complete(self, messages, json_schema=None):
        self.calls.append(list(messages))
        assert json_schema is not None
        return {"text": self.texts.pop(0), "model": "fake-model", "provider": "fake"}


class FakeEmbedder:
    def embed_one(self, text, task="document"):
        assert task == "query"
        return [0.1, 0.2]


CHUNKS = [
    chunk(1, "BUD-2024-002", "KYC-002", KYC_TEXT),
    chunk(2, "BUD-2024-002", "SCORE-003", SCORING_TEXT),
]


def test_source_id_comes_from_budget_and_component():
    assert source_id(CHUNKS[0]) == "BUD-2024-002::KYC-002"


def test_source_id_falls_back_to_database_ids():
    bare = RetrievedChunk(id=7, document_id=3, chunk_type="x", content="c", metadata={})
    assert source_id(bare) == "doc-3::chunk-7"


def test_prompt_tags_every_source_with_its_id():
    llm = ScriptedLLM(payload(line("KYC", 90, True, "BUD-2024-002::KYC-002")))
    generate_grounded_estimate(llm, "Loan platform with KYC", CHUNKS, max_retries=0)
    user = llm.calls[0][1]["content"]
    assert '<source id="BUD-2024-002::KYC-002">' in user
    assert '<source id="BUD-2024-002::SCORE-003">' in user
    assert SCORING_TEXT in user
    assert "Loan platform with KYC" in user


def test_valid_output_is_returned_on_the_first_attempt():
    llm = ScriptedLLM(payload(line("KYC", 90, True, "BUD-2024-002::KYC-002")))
    estimate, report, meta = generate_grounded_estimate(llm, "q", CHUNKS, max_retries=2)
    assert isinstance(estimate, GroundedEstimate)
    assert report.passed is True
    assert meta["attempts"] == 1
    assert meta["prompt_version"] == "v1"


def test_rule_violation_is_sent_back_and_retried():
    broken = payload(line("KYC", 90, True))  # grounded without sources
    fixed = payload(line("KYC", 90, True, "BUD-2024-002::KYC-002"))
    llm = ScriptedLLM(broken, fixed)
    _, _, meta = generate_grounded_estimate(llm, "q", CHUNKS, max_retries=2)
    assert meta["attempts"] == 2
    retry_message = llm.calls[1][-1]["content"]
    assert "at least one source" in retry_message


def test_gives_up_after_the_last_retry():
    broken = payload(line("Chatbot", 40, False))  # invented hours on an ungrounded line
    llm = ScriptedLLM(broken, broken)
    with pytest.raises(GroundedOutputError, match="2 attempts"):
        generate_grounded_estimate(llm, "q", CHUNKS, max_retries=1)


def test_dangling_citation_is_sent_back_and_retried():
    dangling = payload(line("KYC", 90, True, "BUD-2023-099::PAY-001"))  # never retrieved
    fixed = payload(line("KYC", 90, True, "BUD-2024-002::KYC-002"))
    llm = ScriptedLLM(dangling, fixed)
    _, report, meta = generate_grounded_estimate(llm, "q", CHUNKS, max_retries=2)
    assert meta["attempts"] == 2
    assert report.passed is True
    retry_message = llm.calls[1][-1]["content"]
    assert "KYC" in retry_message
    assert "BUD-2023-099::PAY-001" in retry_message


def test_misquoted_evidence_is_sent_back_and_retried():
    misquoted = payload(line("KYC", 90, True, "BUD-2024-002::KYC-002", evidence="Estimated hours: 75"))
    fixed = payload(line("KYC", 90, True, "BUD-2024-002::KYC-002"))
    llm = ScriptedLLM(misquoted, fixed)
    _, report, meta = generate_grounded_estimate(llm, "q", CHUNKS, max_retries=2)
    assert meta["attempts"] == 2
    assert report.passed is True
    assert "BUD-2024-002::KYC-002" in llm.calls[1][-1]["content"]


def test_lines_still_failing_after_the_last_retry_are_rejected_from_the_total():
    still_dangling = payload(
        line("KYC", 90, True, "BUD-2024-002::KYC-002"),
        line("Payments", 60, True, "BUD-2023-099::PAY-001"),
    )
    llm = ScriptedLLM(still_dangling, still_dangling)
    estimate, report, meta = generate_grounded_estimate(llm, "q", CHUNKS, max_retries=1)
    assert len(llm.calls) == 2
    assert meta["attempts"] == 2
    assert report.passed is False
    assert report.dangling == ["Payments"]
    assert estimate.total_hours == 150  # what the model claimed
    assert report.accepted_hours == 90  # what survives the check


@pytest.mark.asyncio
async def test_run_uses_hybrid_search_and_verifies_citations():
    repository = FakeBranchesRepository(
        vector_rows=[row(1, "BUD-2024-002", "KYC-002", KYC_TEXT, distance=0.1)],
        lexical_rows=[row(2, "BUD-2024-002", "SCORE-003", SCORING_TEXT, rank=0.5)],
    )
    llm = ScriptedLLM(
        payload(
            line("KYC", 90, True, "BUD-2024-002::KYC-002"),
            line("Payments", 60, True, "BUD-2023-099::PAY-001"),  # never retrieved
            line("Chatbot", None, False),
        )
    )
    result = await run_grounded_estimation(
        "Loan platform", repository, FakeEmbedder(), llm, top_k=5, max_retries=0
    )

    assert {call[0] for call in repository.calls} == {"vector", "lexical"}
    assert set(result.source_texts) == {"BUD-2024-002::KYC-002", "BUD-2024-002::SCORE-003"}
    assert result.report.grounded == ["KYC"]
    assert result.report.dangling == ["Payments"]
    assert result.report.insufficient == ["Chatbot"]
    assert result.report.evidence_checked is True
    assert result.report.accepted_hours == 90


def answer_text(*lines) -> str:
    estimate = GroundedEstimate.model_validate_json(payload(*lines))
    report = verify_citations(estimate, set(NAMED_TEXTS), NAMED_TEXTS)
    return render_answer_text(estimate, report, NAMED_TEXTS)


NAMED_TEXTS = {
    "BUD-2024-002::KYC-002": "[Project: Digital lending platform]\nComponent: KYC verification\nEstimated hours: 90",
}


def test_answer_text_has_figures_but_no_source_ids():
    text = answer_text(line("KYC", 90, True, "BUD-2024-002::KYC-002"), line("Chatbot", None, False))
    assert "- KYC: 90 hours." in text
    assert "Chatbot: not estimated, insufficient historical data" in text
    assert "Total of the estimated components: 90 hours." in text
    assert "BUD-" not in text


def test_ids_written_in_the_rationale_become_the_project_name():
    """Seen in q02: the model wrote chunk ids in the prose, which no context contains."""
    kyc = line("KYC", 90, True, "BUD-2024-002::KYC-002")
    kyc["rationale"] = "BUD-2024-002::KYC-002 gives 90 hours; BUD-2023-099::PAY-001 is not used."
    text = answer_text(kyc)
    assert 'the "Digital lending platform" budget gives 90 hours' in text
    assert "a past budget is not used" in text
    assert "::" not in text


def test_rejected_lines_are_not_presented_as_estimated():
    text = answer_text(
        line("KYC", 90, True, "BUD-2024-002::KYC-002"),
        line("Payments", 60, True, "BUD-2023-099::PAY-001"),  # dangling
    )
    assert "- Payments: not estimated, its sources failed the citation check." in text
    assert "60 hours" not in text
    assert "Total of the estimated components: 90 hours." in text
