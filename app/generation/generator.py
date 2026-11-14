"""Grounded estimator: retrieved chunks in, an estimate cited line by line out.

    query -> embed -> retrieve (hybrid, no rerank: the session 10 winner)
          -> sources tagged with their chunk id -> LLM forced to the JSON schema
          -> validate (retry with the error) -> verify_citations

The LLM is the same wrapper as the rest of the service (Anthropic, Gemini fallback).
"""

import asyncio
import json
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


def generate_grounded_estimate(
    llm, query: str, chunks: list[RetrievedChunk], max_retries: int | None = None
) -> tuple[GroundedEstimate, dict[str, Any]]:
    """Ask for the estimate, validate it and, if it breaks a rule, retry showing the error."""
    max_retries = get_settings().STRUCTURED_MAX_RETRIES if max_retries is None else max_retries
    sources = [{"id": source_id(chunk), "content": chunk.content} for chunk in chunks]
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
            messages = messages + [
                {"role": "assistant", "content": text.strip() or "{}"},
                {
                    "role": "user",
                    "content": (
                        f"Your JSON breaks the rules: {last_error}. "
                        "Return the full corrected JSON, with no text around it."
                    ),
                },
            ]
            continue
        return estimate, {
            "model": out["model"],
            "provider": out["provider"],
            "fallback_used": out.get("fallback_used", False),
            "attempts": attempt,
            "prompt_version": PROMPT_VERSION,
        }
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
    estimate, meta = await asyncio.to_thread(generate_grounded_estimate, llm, query, chunks, max_retries)

    source_texts = {source_id(chunk): chunk.content for chunk in chunks}
    report = verify_citations(estimate, set(source_texts), source_texts)
    logger.info(
        "grounded_estimation_completed",
        chunks=len(chunks),
        lines=len(estimate.line_items),
        total_hours=estimate.total_hours,
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


def render_answer_text(estimate: GroundedEstimate) -> str:
    """Plain-text estimate for RAGAS and for reading.

    Source ids are left out on purpose: the chunk texts do not contain them, so a judge
    would count "comes from BUD-..." as a claim the context cannot support.
    """
    lines = [estimate.summary, ""]
    for line in estimate.line_items:
        if line.grounded:
            lines.append(f"- {line.component}: {line.hours:g} hours. {line.rationale}")
        else:
            lines.append(f"- {line.component}: not estimated, insufficient historical data. {line.rationale}")
    lines += ["", f"Total of the estimated components: {estimate.total_hours:g} hours."]
    return "\n".join(lines)
