"""Post-generation citation check: no estimate line may cite a source the LLM never saw.

The check is structural: it proves that a cited id was in the retrieved context and,
when the chunk texts are given, that the quoted evidence is really in that chunk. It
does not prove that the source supports the figure: that is a semantic check.
"""

from typing import Literal

import structlog
from pydantic import BaseModel, computed_field

from app.generation.schemas import CHUNK_ID_SEPARATOR, GroundedEstimate

logger = structlog.get_logger(__name__)

LineStatus = Literal["grounded", "dangling", "evidence_mismatch", "insufficient"]


class LineCheck(BaseModel):
    """Verdict for one estimate line.

    - grounded: every cited id was retrieved (and its evidence found, if checked).
    - dangling: at least one cited id was never in the retrieved context.
    - evidence_mismatch: every id resolves, but some quoted evidence is not in its
      chunk or the document_id does not match the chunk id.
    - insufficient: the line was marked as lacking source data (no hours, no sources).
    """

    component: str
    status: LineStatus
    hours: float | None
    cited_ids: list[str]
    dangling_ids: list[str]
    mismatched_ids: list[str]


class CitationReport(BaseModel):
    lines: list[LineCheck]
    evidence_checked: bool

    def _components(self, status: LineStatus) -> list[str]:
        return [line.component for line in self.lines if line.status == status]

    @computed_field
    @property
    def grounded(self) -> list[str]:
        return self._components("grounded")

    @computed_field
    @property
    def dangling(self) -> list[str]:
        return self._components("dangling")

    @computed_field
    @property
    def evidence_mismatch(self) -> list[str]:
        return self._components("evidence_mismatch")

    @computed_field
    @property
    def insufficient(self) -> list[str]:
        return self._components("insufficient")

    @computed_field
    @property
    def passed(self) -> bool:
        """False as soon as one line cites an unretrieved source or misquotes one."""
        return not self.dangling and not self.evidence_mismatch


def _normalize(text: str) -> str:
    """Whitespace and case do not make a quote different."""
    return " ".join(text.split()).casefold()


def verify_citations(
    estimate: GroundedEstimate,
    retrieved_chunk_ids: set[str],
    retrieved_texts: dict[str, str] | None = None,
) -> CitationReport:
    """Flag any line whose cited chunk_id was never in the retrieved context.

    With `retrieved_texts` (chunk id -> text passed to the LLM) it also checks that
    each quoted evidence appears verbatim in the cited chunk.
    """
    lines: list[LineCheck] = []
    for line in estimate.line_items:
        cited = [source.chunk_id for source in line.sources]
        dangling = [cid for cid in cited if cid not in retrieved_chunk_ids]
        mismatched = []
        for source in line.sources:
            if source.chunk_id in dangling:
                continue
            wrong_document = source.chunk_id.split(CHUNK_ID_SEPARATOR)[0] != source.document_id
            missing_quote = retrieved_texts is not None and _normalize(source.evidence) not in _normalize(
                retrieved_texts.get(source.chunk_id, "")
            )
            if wrong_document or missing_quote:
                mismatched.append(source.chunk_id)

        if not line.grounded:
            status: LineStatus = "insufficient"
        elif dangling:
            status = "dangling"
        elif mismatched:
            status = "evidence_mismatch"
        else:
            status = "grounded"
        lines.append(
            LineCheck(
                component=line.component,
                status=status,
                hours=line.hours,
                cited_ids=cited,
                dangling_ids=dangling,
                mismatched_ids=mismatched,
            )
        )

    report = CitationReport(lines=lines, evidence_checked=retrieved_texts is not None)
    if report.dangling:
        logger.warning(
            "dangling_citations",
            components=report.dangling,
            ids=[cid for line in lines for cid in line.dangling_ids],
        )
    if report.evidence_mismatch:
        logger.warning(
            "citation_evidence_mismatch",
            components=report.evidence_mismatch,
            ids=[cid for line in lines for cid in line.mismatched_ids],
        )
    logger.info(
        "citation_report",
        lines=len(lines),
        grounded=len(report.grounded),
        dangling=len(report.dangling),
        evidence_mismatch=len(report.evidence_mismatch),
        insufficient=len(report.insufficient),
        passed=report.passed,
    )
    return report
