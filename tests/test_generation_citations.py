"""Session 11: line-level citation schema and post-generation citation check."""

import pytest
from pydantic import ValidationError

from app.generation.citations import verify_citations
from app.generation.schemas import EstimateLineItem, GroundedEstimate, SourceReference

KYC = "BUD-2024-002::KYC-002"
SCORING = "BUD-2024-002::SCORE-003"
RETRIEVED_TEXTS = {
    KYC: "Component: KYC verification\nEstimated hours: 90",
    SCORING: "Component: Credit scoring engine\nEstimated hours: 160",
}


def source(chunk_id: str, evidence: str = "Estimated hours: 90") -> SourceReference:
    return SourceReference(chunk_id=chunk_id, document_id=chunk_id.split("::")[0], evidence=evidence)


def grounded_line(component: str, *sources: SourceReference, hours: float = 90) -> EstimateLineItem:
    return EstimateLineItem(
        component=component, hours=hours, rationale="Taken from the cited budget.", grounded=True, sources=list(sources)
    )


def insufficient_line(component: str) -> EstimateLineItem:
    return EstimateLineItem(
        component=component, hours=None, rationale="No comparable historical data.", grounded=False, sources=[]
    )


def estimate(*lines: EstimateLineItem) -> GroundedEstimate:
    return GroundedEstimate(summary="Loan platform estimate.", line_items=list(lines))


# --- schema integrity rule ---------------------------------------------------


def test_grounded_line_without_sources_is_rejected():
    with pytest.raises(ValidationError, match="at least one source"):
        EstimateLineItem(component="KYC", hours=90, rationale="Looks similar.", grounded=True, sources=[])


def test_grounded_line_without_hours_is_rejected():
    with pytest.raises(ValidationError, match="must carry hours"):
        EstimateLineItem(component="KYC", hours=None, rationale="From source.", grounded=True, sources=[source(KYC)])


def test_ungrounded_line_cannot_carry_invented_hours():
    with pytest.raises(ValidationError, match="hours = null"):
        EstimateLineItem(component="Chatbot", hours=40, rationale="Gut feeling.", grounded=False, sources=[])


def test_ungrounded_line_cannot_carry_sources():
    with pytest.raises(ValidationError, match="no sources"):
        EstimateLineItem(component="Chatbot", hours=None, rationale="Weak match.", grounded=False, sources=[source(KYC)])


def test_total_hours_counts_only_grounded_lines():
    result = estimate(
        grounded_line("KYC", source(KYC), hours=90),
        grounded_line("Scoring", source(SCORING, "Estimated hours: 160"), hours=150),
        insufficient_line("Chatbot"),
    )
    assert result.total_hours == 240
    assert result.cited_chunk_ids == [KYC, SCORING]


# --- verify_citations --------------------------------------------------------


def test_lines_citing_retrieved_chunks_are_grounded():
    report = verify_citations(estimate(grounded_line("KYC", source(KYC))), {KYC, SCORING}, RETRIEVED_TEXTS)
    assert report.grounded == ["KYC"]
    assert report.passed is True
    assert report.evidence_checked is True


def test_planted_dangling_citation_is_detected():
    """Acceptance criterion: a citation to an id never retrieved is caught."""
    planted = "BUD-2023-099::PAY-001"
    report = verify_citations(
        estimate(grounded_line("KYC", source(KYC)), grounded_line("Payments", source(planted))),
        {KYC, SCORING},
    )
    assert report.dangling == ["Payments"]
    assert report.lines[1].dangling_ids == [planted]
    assert report.grounded == ["KYC"]
    assert report.passed is False


def test_one_dangling_source_taints_the_line_even_with_a_valid_one():
    report = verify_citations(
        estimate(grounded_line("KYC", source(KYC), source("BUD-2022-001::X-1"))), {KYC}
    )
    assert report.dangling == ["KYC"]


def test_insufficient_lines_are_reported_apart():
    report = verify_citations(estimate(grounded_line("KYC", source(KYC)), insufficient_line("Chatbot")), {KYC})
    assert report.insufficient == ["Chatbot"]
    assert report.passed is True


def test_evidence_not_in_the_cited_chunk_is_a_mismatch():
    misquoted = source(KYC, "Estimated hours: 40")
    report = verify_citations(estimate(grounded_line("KYC", misquoted)), {KYC}, RETRIEVED_TEXTS)
    assert report.evidence_mismatch == ["KYC"]
    assert report.passed is False


def test_evidence_match_ignores_whitespace_and_case():
    report = verify_citations(
        estimate(grounded_line("KYC", source(KYC, "estimated  HOURS:\n90"))), {KYC}, RETRIEVED_TEXTS
    )
    assert report.grounded == ["KYC"]


LONG_CHUNK = (
    "Component: Loan origination workflow\n"
    "Description: Configurable application workflow with KYC checks.\n"
    "Tech stack: python_django\n"
    "Complexity: medium\n"
    "Estimated hours: 180"
)


def test_evidence_joining_verbatim_fragments_of_the_chunk_is_accepted():
    """Seen in a real run: description and hours quoted together, lines between them skipped."""
    joined = source(KYC, "Configurable application workflow with KYC checks. Estimated hours: 180")
    report = verify_citations(estimate(grounded_line("KYC", joined)), {KYC}, {KYC: LONG_CHUNK})
    assert report.grounded == ["KYC"]


def test_real_fragment_joined_to_an_invented_figure_is_a_mismatch():
    forged = source(KYC, "Configurable application workflow with KYC checks. Estimated hours: 75")
    report = verify_citations(estimate(grounded_line("KYC", forged)), {KYC}, {KYC: LONG_CHUNK})
    assert report.evidence_mismatch == ["KYC"]


def test_fragments_split_by_ellipsis_are_checked_one_by_one():
    elided = source(KYC, "Component: Loan origination workflow ... Estimated hours: 180")
    report = verify_citations(estimate(grounded_line("KYC", elided)), {KYC}, {KYC: LONG_CHUNK})
    assert report.grounded == ["KYC"]


def test_document_id_must_match_the_chunk_id():
    wrong_document = SourceReference(chunk_id=KYC, document_id="BUD-2023-004", evidence="Estimated hours: 90")
    report = verify_citations(estimate(grounded_line("KYC", wrong_document)), {KYC})
    assert report.evidence_mismatch == ["KYC"]


def test_without_texts_only_ids_are_checked():
    report = verify_citations(estimate(grounded_line("KYC", source(KYC, "anything"))), {KYC})
    assert report.grounded == ["KYC"]
    assert report.evidence_checked is False


def test_lines_that_fail_the_check_are_left_out_of_the_accepted_hours():
    report = verify_citations(
        estimate(
            grounded_line("KYC", source(KYC), hours=90),
            grounded_line("Payments", source("BUD-2023-099::PAY-001"), hours=60),  # dangling
            grounded_line("Scoring", source(SCORING, "Estimated hours: 75"), hours=150),  # misquoted
            insufficient_line("Chatbot"),
        ),
        {KYC, SCORING},
        RETRIEVED_TEXTS,
    )
    assert report.accepted_hours == 90


def test_report_serializes_the_summary_lists():
    report = verify_citations(estimate(insufficient_line("Chatbot")), set())
    dumped = report.model_dump()
    assert dumped["insufficient"] == ["Chatbot"]
    assert dumped["passed"] is True
