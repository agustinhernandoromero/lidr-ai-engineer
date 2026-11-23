"""Run the estimation agent on one transcript and save its trace (session 12).

Usage (from the repository root, Postgres of docker compose running, course corpus):

    DATABASE_URL=postgresql+asyncpg://estimator:estimator@localhost:5432/estimator_s10 \
        .venv/Scripts/python scripts/run_agent_s12.py \
        data/course/session-12/sample_transcript_complex.txt --model claude-sonnet-5-5

Writes reports/s12_agent_trace_<transcript>_<model>.txt (readable trace) and a .json
with the full result. API calls: one LLM call per step (AGENT_MAX_STEPS at most) and
one query embedding per search_budgets call.
"""

import argparse
import asyncio
import sys
import uuid
from pathlib import Path

# Scripts run from the repository root without installing the package.
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import structlog  # noqa: E402

from app.agent.loop import run_agent  # noqa: E402
from app.agent.schemas import AgentResult  # noqa: E402
from app.agent.tools import AgentTools  # noqa: E402
from app.agent.trace import render_trace  # noqa: E402
from app.config import get_settings  # noqa: E402
from app.db.repository import DocumentRepository  # noqa: E402
from app.db.session import dispose_engine, get_sessionmaker  # noqa: E402
from app.embedding_pipeline.router import get_cached_embedder  # noqa: E402
from app.observability import configure_logging  # noqa: E402

REPORTS_DIR = ROOT / "reports"


async def main_async(transcript: str, model: str | None, effort: str | None, max_steps: int | None) -> AgentResult:
    structlog.contextvars.bind_contextvars(request_id=uuid.uuid4().hex[:8])
    try:
        async with get_sessionmaker()() as session:
            tools = AgentTools(DocumentRepository(session), get_cached_embedder(), get_settings().HOURLY_RATE_EUR)
            return await run_agent(transcript, tools, model=model, effort=effort, max_steps=max_steps)
    finally:
        await dispose_engine()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("transcript", type=Path, help="Text file with the meeting transcript.")
    parser.add_argument("--model", help="Anthropic model id (default: AGENT_MODEL).")
    parser.add_argument("--effort", choices=["low", "medium", "high", "xhigh", "max"], help="Default: AGENT_EFFORT.")
    parser.add_argument("--max-steps", type=int, help="Model calls at most (default: AGENT_MAX_STEPS).")
    args = parser.parse_args()

    configure_logging("development")
    result = asyncio.run(main_async(args.transcript.read_text(encoding="utf-8"), args.model, args.effort, args.max_steps))

    trace = render_trace(result, title=f"on {args.transcript.name}")
    print(trace)
    REPORTS_DIR.mkdir(exist_ok=True)
    stem = f"s12_agent_trace_{args.transcript.stem}_{result.model}"
    (REPORTS_DIR / f"{stem}.txt").write_text(trace, encoding="utf-8")
    (REPORTS_DIR / f"{stem}.json").write_text(result.model_dump_json(indent=2), encoding="utf-8")
    print(f"Saved reports/{stem}.txt and .json")


if __name__ == "__main__":
    main()
