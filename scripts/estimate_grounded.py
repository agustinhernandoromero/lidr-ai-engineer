"""One real grounded estimate and its citation report (session 11, part 1).

Runs the grounded estimator on one golden-set query (or a free query), then checks
the citations, and finally plants a citation to a chunk that was never retrieved to
show that the check catches it (offline, no extra API call).

Usage (from the repository root, Postgres of docker compose running, course corpus):

    DATABASE_URL=postgresql+asyncpg://estimator:estimator@localhost:5432/estimator_s10 \
        .venv/Scripts/python scripts/estimate_grounded.py --query-id q01

API calls: 1 query embedding (embeddings provider) and 1 LLM call, plus 1 per retry
if the JSON breaks a schema rule (STRUCTURED_MAX_RETRIES, 2 by default).
"""

import argparse
import asyncio
import json
import sys
import uuid
from pathlib import Path

# Scripts run from the repository root without installing the package.
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import structlog  # noqa: E402

from app.db.repository import DocumentRepository  # noqa: E402
from app.db.session import dispose_engine, get_sessionmaker  # noqa: E402
from app.embedding_pipeline.router import get_cached_embedder  # noqa: E402
from app.generation.citations import CitationReport, verify_citations  # noqa: E402
from app.generation.generator import GroundedGeneration, run_grounded_estimation  # noqa: E402
from app.generation.schemas import SourceReference  # noqa: E402
from app.observability import configure_logging  # noqa: E402
from app.services.llm_service import LLMWrapper  # noqa: E402

GOLDEN_SET_PATH = Path(__file__).parent / "golden_set_course.json"
REPORTS_DIR = ROOT / "reports"
PLANTED_ID = "BUD-2023-099::PAY-001"  # not in the corpus: can never be retrieved


def planted_check(result: GroundedGeneration) -> CitationReport:
    """Re-verify the real estimate after adding a citation to a chunk never retrieved."""
    tampered = result.estimate.model_copy(deep=True)
    target = next((line for line in tampered.line_items if line.grounded), None)
    if target is None:
        raise SystemExit("The estimate has no grounded line to plant a citation in.")
    target.sources.append(
        SourceReference(chunk_id=PLANTED_ID, document_id=PLANTED_ID.split("::")[0], evidence="Estimated hours: 75")
    )
    return verify_citations(tampered, set(result.source_texts), result.source_texts)


def render(query_id: str, result: GroundedGeneration, planted: CitationReport, request_id: str) -> str:
    report = result.report
    out = [
        f"# Citation report: {query_id}",
        "",
        f"- Query: {result.query}",
        f"- request_id: `{request_id}`",
        f"- Model: {result.meta['model']} ({result.meta['provider']}), "
        f"attempts: {result.meta['attempts']}, prompt {result.meta['prompt_version']}",
        f"- Retrieved chunks passed to the LLM: {len(result.chunks)}",
        "",
        "## Retrieved context",
        "",
        "| Chunk id | Component | Hours |",
        "|---|---|---|",
    ]
    for chunk_id, chunk in zip(result.source_texts, result.chunks):
        name = next((ln.removeprefix("Component: ") for ln in chunk.content.splitlines() if ln.startswith("Component: ")), "")
        out.append(f"| `{chunk_id}` | {name} | {chunk.metadata.get('estimated_hours', '')} |")
    out += [
        "",
        "## Estimate lines and citation check",
        "",
        "| Component | Hours | Status | Cited ids | Evidence |",
        "|---|---|---|---|---|",
    ]
    for line, check in zip(result.estimate.line_items, report.lines):
        hours = f"{line.hours:g}" if line.hours is not None else "n/a"
        cited = ", ".join(f"`{cid}`" for cid in check.cited_ids) or "none"
        evidence = "; ".join(source.evidence.replace("\n", " ") for source in line.sources) or "none"
        out.append(f"| {line.component} | {hours} | {check.status} | {cited} | {evidence} |")
    out += [
        "",
        f"Total of the lines that pass the check: {report.accepted_hours:g} h",
        "",
        "## Summary",
        "",
        f"- Grounded: {len(report.grounded)}",
        f"- Dangling citation: {len(report.dangling)}",
        f"- Evidence mismatch: {len(report.evidence_mismatch)}",
        f"- Insufficient data: {len(report.insufficient)}",
        f"- Check passed: {report.passed}",
        "",
        "## Planted dangling citation",
        "",
        f"`{PLANTED_ID}` added to the first grounded line, then the same check run again:",
        f"dangling lines {planted.dangling}, check passed: {planted.passed}. The tainted line is rejected:",
        f"the accepted total drops from {report.accepted_hours:g} h to {planted.accepted_hours:g} h.",
        "",
        "## Generated summary",
        "",
        result.estimate.summary,
        "",
    ]
    return "\n".join(out)


async def main_async(query_id: str, query: str) -> str:
    request_id = uuid.uuid4().hex[:8]
    structlog.contextvars.bind_contextvars(request_id=request_id, query_id=query_id)
    try:
        async with get_sessionmaker()() as session:
            result = await run_grounded_estimation(
                query, DocumentRepository(session), get_cached_embedder(), LLMWrapper()
            )
    finally:
        await dispose_engine()
    planted = planted_check(result)

    REPORTS_DIR.mkdir(exist_ok=True)
    stem = REPORTS_DIR / f"s11_citations_{query_id}"
    stem.with_suffix(".json").write_text(
        json.dumps(
            {
                "query_id": query_id,
                "query": query,
                "request_id": request_id,
                "meta": result.meta,
                "retrieved": result.source_texts,
                "estimate": result.estimate.model_dump(),
                "report": result.report.model_dump(),
                "planted_check": planted.model_dump(),
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    markdown = render(query_id, result, planted, request_id)
    stem.with_suffix(".md").write_text(markdown, encoding="utf-8")
    structlog.contextvars.clear_contextvars()
    return markdown


def main() -> None:
    parser = argparse.ArgumentParser(description="One grounded estimate and its citation report.")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--query-id", help="id of a golden-set query, e.g. q01")
    group.add_argument("--query", help="free query text (saved as 'custom')")
    parser.add_argument("--golden", type=Path, default=GOLDEN_SET_PATH)
    args = parser.parse_args()

    if args.query_id:
        queries = {q["id"]: q["query"] for q in json.loads(args.golden.read_text(encoding="utf-8"))["queries"]}
        if args.query_id not in queries:
            raise SystemExit(f"Unknown query id {args.query_id!r}. Known: {', '.join(queries)}")
        query_id, query = args.query_id, queries[args.query_id]
    else:
        query_id, query = "custom", args.query

    configure_logging("development")
    markdown = asyncio.run(main_async(query_id, query))
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    print(markdown)
    print(f"Saved to {REPORTS_DIR / f's11_citations_{query_id}'}.md / .json")


if __name__ == "__main__":
    main()
