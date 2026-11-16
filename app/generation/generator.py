"""Grounded estimator: retrieved chunks in, an estimate cited line by line out.

    query -> embed -> retrieve (hybrid, no rerank: the session 10 winner)
          -> sources tagged with their chunk id -> LLM forced to the JSON schema
          -> validate and verify_citations (retry with the error)
          -> lines whose citations still fail are rejected from the total

The LLM is the same wrapper as the rest of the service (Anthropic, Gemini fallback).
"""

import asyncio
import json
import re
from dataclasses import dataclass
from typing import Any

import anthropic
import structlog
from pydantic import ValidationError

from app.config import get_settings
from app.generation.citations import CitationReport, verify_citations
from app.generation.schemas import CHUNK_ID_SEPARATOR, GroundedEstimate
from app.prompts.loader import render_grounded_estimation_prompt
from app.retrieval.pipeline import retrieve
from app.retrieval.types import RetrievedChunk
from app.services.structured_estimator import _describe, _json_slice

logger = structlog.get_logger(__name__)

PROMPT_VERSION = "v1"
SEARCH_MODE = "hybrid"
RERANK = False
GROUNDED_JSON_SCHEMA = anthropic.transform_schema(GroundedEstimate.model_json_schema())


class GroundedOutputError(RuntimeError):
    """The model did not produce a valid GroundedEstimate after every attempt."""


@dataclass(frozen=True)
class GroundedGeneration:
    """Everything one grounded estimation produced, kept together for evaluation."""

    query: str
    chunks: list[RetrievedChunk]
    source_texts: dict[str, str]  # citable id -> exact text the LLM received
    estimate: GroundedEstimate
    report: CitationReport
    meta: dict[str, Any]


def source_id(chunk: RetrievedChunk) -> str:
    """Citable id of a chunk: "<budget_id>::<component_id>", as a reader would look it up."""
    budget_id = chunk.metadata.get("budget_id")
    component_id = chunk.metadata.get("component_id")
    if budget_id and component_id:
        return f"{budget_id}{CHUNK_ID_SEPARATOR}{component_id}"
    return f"doc-{chunk.document_id}{CHUNK_ID_SEPARATOR}chunk-{chunk.id}"


def _correction(text: str, problem: str) -> list[dict[str, str]]:
    """The rejected answer and what to fix in it, appended to the conversation."""
    return [
        {"role": "assistant", "content": text.strip() or "{}"},
        {"role": "user", "content": f"{problem} Return the full corrected JSON, with no text around it."},
    ]


def _citation_feedback(report: CitationReport) -> str:
    """Every failing citation by line, so the retry can fix exactly those."""
    problems = []
    for check in report.lines:
        if check.dangling_ids:
            problems.append(f"{check.component!r} cites {', '.join(check.dangling_ids)}, which you were never given")
        if check.mismatched_ids:
            problems.append(
                f"{check.component!r} quotes evidence that is not verbatim in {', '.join(check.mismatched_ids)}"
                " (or its document_id does not match the chunk id)"
            )
    return "; ".join(problems)


def generate_grounded_estimate(
    llm, query: str, chunks: list[RetrievedChunk], max_retries: int | None = None
) -> tuple[GroundedEstimate, CitationReport, dict[str, Any]]:
    """Ask for the estimate, validate it and verify its citations; retry showing what failed.

    Schema errors and failing citations share the retry budget. A schema error on the
    last attempt raises; failing citations on the last attempt are returned in the
    report, and those lines do not count in `report.accepted_hours`.
    """
    max_retries = get_settings().STRUCTURED_MAX_RETRIES if max_retries is None else max_retries
    sources = [{"id": source_id(chunk), "content": chunk.content} for chunk in chunks]
    source_texts = {source["id"]: source["content"] for source in sources}
    system, user = render_grounded_estimation_prompt(query=query, sources=sources, version=PROMPT_VERSION)
    messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]

    last_error = ""
    for attempt in range(1, max_retries + 2):
        out = llm.complete(messages, json_schema=GROUNDED_JSON_SCHEMA)
        text = out["text"] or ""
        try:
            estimate = GroundedEstimate.model_validate(json.loads(_json_slice(text)))
        except (ValidationError, ValueError) as exc:
            last_error = _describe(exc)
            logger.warning("grounded_output_invalid", attempt=attempt, error=last_error)
            messages = messages + _correction(text, f"Your JSON breaks the rules: {last_error}.")
            continue
        report = verify_citations(estimate, set(source_texts), source_texts)
        if report.passed or attempt == max_retries + 1:
            return estimate, report, {
                "model": out["model"],
                "provider": out["provider"],
                "fallback_used": out.get("fallback_used", False),
                "attempts": attempt,
                "prompt_version": PROMPT_VERSION,
            }
        feedback = _citation_feedback(report)
        logger.warning("grounded_citations_failed", attempt=attempt, error=feedback)
        messages = messages + _correction(
            text,
            f"Some citations fail the check: {feedback}. Cite only ids of the <source> tags you were given "
            "and copy the evidence verbatim from that source; if no source supports a line, set grounded "
            "to false, hours to null and sources to [].",
        )
    raise GroundedOutputError(
        f"No valid grounded estimate after {max_retries + 1} attempts: {last_error}"
    )


async def run_grounded_estimation(
    query: str,
    repository,
    embedder,
    llm,
    *,
    top_k: int | None = None,
    max_retries: int | None = None,
) -> GroundedGeneration:
    """Retrieve, generate and verify one estimate. Blocking calls run in worker threads."""
    query_vector = await asyncio.to_thread(embedder.embed_one, query, "query")
    chunks = await retrieve(repository, query, query_vector, mode=SEARCH_MODE, rerank=RERANK, top_k=top_k)
    estimate, report, meta = await asyncio.to_thread(generate_grounded_estimate, llm, query, chunks, max_retries)

    source_texts = {source_id(chunk): chunk.content for chunk in chunks}
    logger.info(
        "grounded_estimation_completed",
        chunks=len(chunks),
        lines=len(estimate.line_items),
        total_hours=report.accepted_hours,
        rejected_lines=len(report.dangling) + len(report.evidence_mismatch),
        citations_passed=report.passed,
        model=meta["model"],
        attempts=meta["attempts"],
    )
    return GroundedGeneration(
        query=query,
        chunks=chunks,
        source_texts=source_texts,
        estimate=estimate,
        report=report,
        meta=meta,
    )


_CHUNK_ID_IN_TEXT = re.compile(r"[\w-]+::[\w-]+")
_PROJECT_NAME = re.compile(r"\[Project: ([^\]\n]+)\]")


def name_sources(text: str, source_texts: dict[str, str]) -> str:
    """Write the project name where the model wrote a chunk id in free text.

    The chunk texts a judge reads carry the project name, not the id, so "BUD-...::...
    gives 40 hours" cannot be checked and 'the "<project>" budget gives 40 hours' can.
    An id that was never retrieved has no project and becomes "a past budget".
    """

    def label(match: re.Match[str]) -> str:
        project = _PROJECT_NAME.search(source_texts.get(match.group(0), ""))
        return f'the "{project.group(1)}" budget' if project else "a past budget"

    return _CHUNK_ID_IN_TEXT.sub(label, text)


def render_answer_text(estimate: GroundedEstimate, report: CitationReport, source_texts: dict[str, str]) -> str:
    """Plain-text estimate for RAGAS and for reading.

    Source ids are left out on purpose: the chunk texts do not contain them, so a judge
    would count "comes from BUD-..." as a claim the context cannot support. A line whose
    citations failed the check is shown as not estimated and left out of the total.
    """
    lines = [estimate.summary, ""]
    for item, check in zip(estimate.line_items, report.lines, strict=True):
        if check.status == "grounded":
            lines.append(f"- {item.component}: {item.hours:g} hours. {item.rationale}")
        elif check.status == "insufficient":
            lines.append(f"- {item.component}: not estimated, insufficient historical data. {item.rationale}")
        else:
            lines.append(f"- {item.component}: not estimated, its sources failed the citation check.")
    lines += ["", f"Total of the estimated components: {report.accepted_hours:g} hours."]
    return name_sources("\n".join(lines), source_texts)
