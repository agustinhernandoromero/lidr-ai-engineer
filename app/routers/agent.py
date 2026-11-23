"""POST /api/v1/estimate/agent: transcript in, structured estimate and its trace out.

The caller sends the transcript and gets the estimate back, as with the fixed
pipeline; the loop, its tool calls and its model calls stay inside the service.
"""

import anthropic
import structlog
from fastapi import APIRouter, Depends, HTTPException, status

from app.agent.loop import run_agent
from app.agent.schemas import AgentRequest, AgentResult
from app.agent.tools import AgentTools
from app.config import get_settings
from app.db.repository import DocumentRepository, get_repository
from app.embedding_pipeline.router import get_cached_embedder

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="", tags=["Agent"])


def get_agent_tools(repository: DocumentRepository = Depends(get_repository)) -> AgentTools:
    """Tools over the request's database session and the same embedder as ingestion."""
    return AgentTools(repository, get_cached_embedder(), get_settings().HOURLY_RATE_EUR)


@router.post(
    "/estimate/agent",
    response_model=AgentResult,
    summary="Estimate a meeting transcript with the agent",
    description=(
        "The agent breaks the transcript into components, searches historical budgets for each "
        "one (search_budgets), computes the estimate deterministically (calculate_estimate) and "
        "returns it with the step-by-step trace: reasoning, action and observation per step."
    ),
)
async def estimate_with_agent(
    payload: AgentRequest,
    tools: AgentTools = Depends(get_agent_tools),
) -> AgentResult:
    try:
        return await run_agent(payload.transcript, tools)
    except anthropic.APIError as exc:
        logger.exception("agent_llm_failed")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"The language model call failed: {type(exc).__name__}. See the logs for the X-Request-ID.",
        )
