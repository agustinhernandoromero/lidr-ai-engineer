"""RAGAS evaluation of the grounded estimator over the golden set (session 11, part 2).

For each golden-set query the real pipeline runs (hybrid retrieval + grounded
generation), and RAGAS scores four metrics with Gemini as the judge:

    faithfulness, answer_relevancy  -> generation (no reference needed)
    context_precision, context_recall -> retrieval (need the ground_truth)

Usage (from the repository root, Postgres of docker compose running, course corpus):

    DATABASE_URL=postgresql+asyncpg://estimator:estimator@localhost:5432/estimator_s10 \
        .venv/Scripts/python scripts/evaluate_ragas.py

Two stages, so the judge can be re-run without paying the generation again:
  1. generation: 5 query embeddings + 5 LLM calls (Anthropic), saved to --samples;
  2. scoring: around 11 judge calls and 4 embedding calls per query (Gemini).
`--skip-generation` reuses the saved samples and runs only stage 2.

The judge is Gemini through its OpenAI-compatible endpoint (the workaround the RAGAS
docs give for an instructor bug with the google-genai SDK); embeddings use google-genai.
The free tier allows 20 requests per day per model, fewer than one full run needs, so
scoring can be split: `--metrics` and `--queries` score a subset, and the result is
merged into the saved scores with the judge of every cell. `--render-only` rewrites the
report from the saved scores without calling anything.

    # e.g. context_precision for four queries with another judge, merged into the rest
    .venv/Scripts/python scripts/evaluate_ragas.py --skip-generation \
        --metrics context_precision --queries q02 q03 q04 q05 --judge-model gemini-3.5-flash
"""

import os

# RAGAS sends usage analytics unless this is set; it ignores the generic DO_NOT_TRACK.
os.environ.setdefault("RAGAS_DO_NOT_TRACK", "true")

import argparse  # noqa: E402
import asyncio  # noqa: E402
import json  # noqa: E402
import sys  # noqa: E402
import uuid  # noqa: E402
from datetime import date  # noqa: E402
from pathlib import Path  # noqa: E402
from statistics import mean  # noqa: E402
from typing import Any  # noqa: E402

# Scripts run from the repository root without installing the package.
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import structlog  # noqa: E402

GOLDEN_SET_PATH = Path(__file__).parent / "golden_set_course.json"
REPORTS_DIR = ROOT / "reports"
SAMPLES_PATH = REPORTS_DIR / "s11_ragas_samples.json"
OUTPUT_PATH = REPORTS_DIR / "s11_ragas.md"

JUDGE_MODEL = "gemini-3.5-flash"  # dated stable release (3.5-flash-05-2026), not the moving alias
EMBEDDING_MODEL = "gemini-embedding-001"
GEMINI_OPENAI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai/"
JUDGE_MAX_TOKENS = 8192  # RAGAS default is 1024; statement lists of a long answer do not fit
METRICS = ("faithfulness", "answer_relevancy", "context_precision", "context_recall")

logger = structlog.get_logger("evaluate_ragas")


# --- stage 1: generation ------------------------------------------------------


async def generate_samples(golden: dict) -> list[dict[str, Any]]:
    """Run the real pipeline on every golden query and keep what RAGAS needs."""
    from app.db.repository import DocumentRepository
    from app.db.session import dispose_engine, get_sessionmaker
    from app.embedding_pipeline.router import get_cached_embedder
    from app.generation.generator import render_answer_text, run_grounded_estimation
    from app.services.llm_service import LLMWrapper

    samples = []
    try:
        async with get_sessionmaker()() as session:
            repository = DocumentRepository(session)
            embedder, llm = get_cached_embedder(), LLMWrapper()
            for entry in golden["queries"]:
                request_id = uuid.uuid4().hex[:8]
                structlog.contextvars.bind_contextvars(request_id=request_id, query_id=entry["id"])
                result = await run_grounded_estimation(entry["query"], repository, embedder, llm)
                samples.append(
                    {
                        "id": entry["id"],
                        "request_id": request_id,
                        "user_input": entry["query"],
                        "response": render_answer_text(result.estimate, result.report, result.source_texts),
                        "retrieved_contexts": [chunk.content for chunk in result.chunks],
                        "retrieved_ids": list(result.source_texts),
                        "reference": entry["ground_truth"],
                        "total_hours": result.report.accepted_hours,
                        "citations": {
                            "passed": result.report.passed,
                            "grounded": len(result.report.grounded),
                            "dangling": len(result.report.dangling),
                            "evidence_mismatch": len(result.report.evidence_mismatch),
                            "insufficient": len(result.report.insufficient),
                        },
                        "generation": result.meta,
                    }
                )
                structlog.contextvars.clear_contextvars()
    finally:
        await dispose_engine()
    return samples


# --- stage 2: scoring -----------------------------------------------------------


def build_metrics(judge_model: str, names: list[str]) -> dict[str, Any]:
    """The requested RAGAS metrics, judged by a Gemini model."""
    from google import genai
    from openai import AsyncOpenAI
    from ragas.embeddings import GoogleEmbeddings
    from ragas.llms import llm_factory
    from ragas.metrics.collections import (
        AnswerRelevancy,
        ContextPrecisionWithReference,
        ContextRecall,
        Faithfulness,
    )

    from app.config import get_settings

    api_key = get_settings().GEMINI_API_KEY
    if not api_key:
        raise SystemExit("GEMINI_API_KEY is missing: the judge and the embeddings need it.")
    # The client retries 429/5xx with backoff, which the free tier rate limit needs.
    client = AsyncOpenAI(api_key=api_key, base_url=GEMINI_OPENAI_BASE_URL, max_retries=8, timeout=180)
    llm = llm_factory(judge_model, provider="openai", client=client, max_tokens=JUDGE_MAX_TOKENS)
    embeddings = GoogleEmbeddings(client=genai.Client(api_key=api_key), model=EMBEDDING_MODEL)
    factories = {
        "faithfulness": lambda: Faithfulness(llm=llm),
        "answer_relevancy": lambda: AnswerRelevancy(llm=llm, embeddings=embeddings),
        "context_precision": lambda: ContextPrecisionWithReference(llm=llm),
        "context_recall": lambda: ContextRecall(llm=llm),
    }
    return {name: factories[name]() for name in METRICS if name in names}


def metric_inputs(name: str, sample: dict) -> dict[str, Any]:
    """Each metric takes only the fields it uses."""
    question, contexts = sample["user_input"], sample["retrieved_contexts"]
    if name == "faithfulness":
        return {"user_input": question, "response": sample["response"], "retrieved_contexts": contexts}
    if name == "answer_relevancy":
        return {"user_input": question, "response": sample["response"]}
    if name == "context_precision":
        return {"user_input": question, "reference": sample["reference"], "retrieved_contexts": contexts}
    if name == "context_recall":
        return {"user_input": question, "retrieved_contexts": contexts, "reference": sample["reference"]}
    raise ValueError(f"unknown metric {name!r}")


async def score_samples(samples: list[dict], metrics: dict[str, Any]) -> dict[str, dict[str, float | None]]:
    """query id -> metric -> score. One call at a time: the free tier allows few per minute.

    A metric that fails is recorded as None and logged, so one judge error does not
    lose the other scores.
    """
    scores: dict[str, dict[str, float | None]] = {}
    for sample in samples:
        scores[sample["id"]] = {}
        for name, metric in metrics.items():
            try:
                result = await metric.ascore(**metric_inputs(name, sample))
                value = float(result.value)
            except Exception as exc:  # noqa: BLE001
                logger.error("ragas_metric_failed", query_id=sample["id"], metric=name, error=str(exc)[:300])
                value = None
            scores[sample["id"]][name] = value
            logger.info("ragas_metric_scored", query_id=sample["id"], metric=name, value=value)
    return scores


# --- saved results ----------------------------------------------------------------
# {"scores": {query: {metric: value}}, "judges": {query: {metric: judge model}}}
# A cell with a judge and no value failed; a cell without a judge is still pending.


def load_results(path: Path) -> dict[str, dict]:
    if path.exists():
        saved = json.loads(path.read_text(encoding="utf-8"))
        return {"scores": saved.get("scores", {}), "judges": saved.get("judges", {})}
    return {"scores": {}, "judges": {}}


def merge_scores(results: dict[str, dict], new_scores: dict[str, dict], judge_model: str) -> dict[str, dict]:
    """Overwrite only the cells just scored, and record who judged them."""
    for query_id, row in new_scores.items():
        for metric, value in row.items():
            results["scores"].setdefault(query_id, {})[metric] = value
            results["judges"].setdefault(query_id, {})[metric] = judge_model
    return results


# --- report -------------------------------------------------------------------


def averages(scores: dict[str, dict[str, float | None]]) -> dict[str, float | None]:
    """Mean per metric over the queries that got a score (None if none did)."""
    out = {}
    for name in METRICS:
        values = [row[name] for row in scores.values() if row.get(name) is not None]
        out[name] = mean(values) if values else None
    return out


def _cell(value: float | None, judged: bool = True) -> str:
    if value is not None:
        return f"{value:.2f}"
    return "error" if judged else "pending"


def render(samples: list[dict], results: dict[str, dict]) -> str:
    scores, judges = results["scores"], results["judges"]
    ids = [sample["id"] for sample in samples]
    avg = averages({qid: scores.get(qid, {}) for qid in ids})

    def judged(qid: str, name: str) -> bool:
        return name in judges.get(qid, {})

    failed = sum(1 for qid in ids for name in METRICS if judged(qid, name) and scores[qid].get(name) is None)
    pending = sum(1 for qid in ids for name in METRICS if not judged(qid, name))
    judge_lines = []
    for name in METRICS:
        used = sorted({judges[qid][name] for qid in ids if judged(qid, name)})
        judge_lines.append(f"  - {name}: {' + '.join(used) if used else 'pending'}" + (" (mixed)" if len(used) > 1 else ""))
    generation = samples[0]["generation"] if samples else {}
    out = [
        "# RAGAS: grounded estimator over the course golden set",
        "",
        f"- Date: {date.today().isoformat()}",
        f"- Generation: {generation.get('model', '?')} ({generation.get('provider', '?')}), "
        f"prompt grounded_estimation/{generation.get('prompt_version', '?')}, hybrid retrieval without "
        "reranking, top 5 chunks",
        f"- ragas 0.4.3, Gemini judges through the OpenAI-compatible endpoint, embeddings {EMBEDDING_MODEL}",
        "- Judge per metric:",
        *judge_lines,
        f"- Metric calls that failed: {failed}" + (" (shown as `error`, left out of the average)" if failed else ""),
        f"- Cells still pending: {pending}",
        "",
        "| Query | Faithfulness | Answer relevancy | Context precision | Context recall |",
        "|---|---|---|---|---|",
    ]
    for qid in ids:
        row = scores.get(qid, {})
        out.append(f"| {qid} | " + " | ".join(_cell(row.get(name), judged(qid, name)) for name in METRICS) + " |")
    # An average over part of the queries would read as the full one: wait for every cell.
    out.append(
        "| **Average** | "
        + " | ".join(
            f"**{_cell(avg[name]) if all(judged(qid, name) for qid in ids) else 'pending'}**" for name in METRICS
        )
        + " |"
    )
    out += [
        "",
        "## Citations and totals per query",
        "",
        "| Query | Total hours | Grounded lines | Dangling | Evidence mismatch | Insufficient | Check passed |",
        "|---|---|---|---|---|---|---|",
    ]
    for sample in samples:
        c = sample["citations"]
        out.append(
            f"| {sample['id']} | {sample['total_hours']:g} | {c['grounded']} | {c['dangling']} "
            f"| {c['evidence_mismatch']} | {c['insufficient']} | {c['passed']} |"
        )
    out.append("")
    return "\n".join(out)


# --- entry point ----------------------------------------------------------------


async def main_async(args: argparse.Namespace) -> str:
    golden = json.loads(args.golden.read_text(encoding="utf-8"))
    missing = [q["id"] for q in golden["queries"] if not q.get("ground_truth")]
    if missing:
        raise SystemExit(f"Queries without ground_truth: {missing}")

    results_path = args.output.with_suffix(".json")
    if args.skip_generation or args.render_only:
        samples = json.loads(args.samples.read_text(encoding="utf-8"))
        results = load_results(results_path)
    else:
        samples = await generate_samples(golden)
        args.samples.parent.mkdir(parents=True, exist_ok=True)
        args.samples.write_text(json.dumps(samples, indent=2, ensure_ascii=False), encoding="utf-8")
        results = {"scores": {}, "judges": {}}  # new answers: scores of the old ones no longer apply

    if not args.render_only:
        selected = [s for s in samples if not args.queries or s["id"] in args.queries]
        unknown = set(args.queries or []) - {s["id"] for s in samples}
        if unknown:
            raise SystemExit(f"Unknown query ids: {sorted(unknown)}")
        new_scores = await score_samples(selected, build_metrics(args.judge_model, args.metrics))
        merge_scores(results, new_scores, args.judge_model)

    report = render(samples, results)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(report, encoding="utf-8")
    average = averages({s["id"]: results["scores"].get(s["id"], {}) for s in samples})
    results_path.write_text(json.dumps({**results, "average": average}, indent=2), encoding="utf-8")
    return report


def main() -> None:
    from app.observability import configure_logging

    parser = argparse.ArgumentParser(description="RAGAS evaluation over the golden set.")
    parser.add_argument("--golden", type=Path, default=GOLDEN_SET_PATH)
    parser.add_argument("--samples", type=Path, default=SAMPLES_PATH, help="generated samples (JSON)")
    parser.add_argument("--output", type=Path, default=OUTPUT_PATH, help="markdown report to write")
    parser.add_argument("--judge-model", default=JUDGE_MODEL)
    parser.add_argument("--metrics", nargs="+", choices=METRICS, default=list(METRICS), help="metrics to score")
    parser.add_argument("--queries", nargs="+", default=None, help="query ids to score (default: all)")
    parser.add_argument("--skip-generation", action="store_true", help="reuse --samples, score only")
    parser.add_argument("--render-only", action="store_true", help="rewrite the report from saved scores")
    args = parser.parse_args()

    configure_logging("development")
    report = asyncio.run(main_async(args))
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    print(report)
    print(f"Saved to {args.output} and {args.samples}")


if __name__ == "__main__":
    main()
