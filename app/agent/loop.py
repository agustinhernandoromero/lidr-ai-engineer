"""Estimation agent: a hand-written tool-use loop on the Anthropic Messages API.

    transcript -> model decides -> tools run here -> results go back -> ... -> final answer

No framework and no SDK tool runner: every turn passes through this loop, which is
what lets the trace keep the reasoning, the action and the observation of each step.
The model chooses how many searches to run and in which order; AGENT_MAX_STEPS caps
the number of model calls so a run that does not converge still ends.
"""

from __future__ import annotations

from typing import Any

import anthropic
import structlog

from app.agent.schemas import AgentResult, AgentStatus, AgentUsage, ToolCallRecord, TraceStep
from app.agent.tools import CALCULATE_ESTIMATE, TOOL_DEFINITIONS, AgentTools
from app.config import get_settings

logger = structlog.get_logger(__name__)

PROMPT_VERSION = "agent-v3"  # v3: a short progress note to the user before each round of tool calls
MAX_TOKENS = 16_000  # per model call; thinking counts against it

# USD per million tokens (input, output), Anthropic list prices.
PRICES_USD_PER_MTOK: dict[str, tuple[float, float]] = {
    "claude-sonnet-5-5": (2.00, 10.00),
    "claude-haiku-5-5": (0.10, 0.50),
    "claude-opus-5-5": (4.00, 20.00),
}

SYSTEM_PROMPT = """\
You are a software estimation agent for a consultancy. You receive the transcript of a \
client meeting, usually in Spanish, and produce an effort estimate grounded in the \
consultancy's historical budgets.

Method:
1. Read the transcript and decompose the project into the components that need their own \
estimate: pieces with their own scope and their own kind of comparable past work (for \
example a business backend, an ERP integration, a mobile app). Do not split a component \
into small tasks, and do not merge unrelated pieces into one.
2. For each component, call search_budgets with a short English description of that \
component. Judge what comes back: keep only the items that are genuinely comparable, and \
search again with different wording when the matches are weak.
3. When every component has references, or you have searched twice without finding any, \
call calculate_estimate with all the components and the estimated_hours of the items you kept.
4. If calculate_estimate flags an unbudgeted component, decide whether one more search can \
fix it; otherwise accept the flag.
5. Finish with a short answer in English: each component with its hours and euros, the total, \
and for each component the historical items (source_id) that backed it and why they are \
comparable. Take every number from calculate_estimate; do not compute figures yourself.

Before each round of tool calls, tell the user in one or two sentences, in English, what \
you are about to do next and why.

Never invent historical budgets or hours.\
"""

_STATUS_BY_STOP_REASON: dict[str, AgentStatus] = {
    "end_turn": "completed",
    "stop_sequence": "completed",
    "refusal": "refused",
    "max_tokens": "truncated",
}


def cost_usd(model: str, input_tokens: int, output_tokens: int) -> float:
    prices = PRICES_USD_PER_MTOK.get(model)
    if prices is None:
        logger.warning("agent_unknown_model_price", model=model)
        return 0.0
    return (input_tokens * prices[0] + output_tokens * prices[1]) / 1_000_000


def _reasoning(content: list[Any]) -> str:
    """Thinking summaries plus any text the model wrote before its tool calls."""
    parts = [block.thinking.strip() for block in content if block.type == "thinking" and block.thinking.strip()]
    if any(block.type == "tool_use" for block in content):
        parts += [block.text.strip() for block in content if block.type == "text" and block.text.strip()]
    return "\n".join(parts)


def _answer(content: list[Any]) -> str:
    return "\n".join(block.text.strip() for block in content if block.type == "text" and block.text.strip())


def _refusal_note(response: Any) -> str:
    """Category and explanation of a refusal, so the trace says why the run stopped."""
    details = getattr(response, "stop_details", None)
    category = getattr(details, "category", None)
    explanation = getattr(details, "explanation", None)
    logger.warning("agent_refused", category=category, explanation=explanation)
    return f"Refused by the model (category={category}): {explanation or 'no explanation given'}"


async def run_agent(
    transcript: str,
    tools: AgentTools,
    *,
    client: anthropic.AsyncAnthropic | None = None,
    model: str | None = None,
    effort: str | None = None,
    max_steps: int | None = None,
) -> AgentResult:
    """Run the loop until the model answers without tool calls, or until max_steps model calls."""
    settings = get_settings()
    model = model or settings.AGENT_MODEL
    effort = effort or settings.AGENT_EFFORT
    max_steps = max_steps or settings.AGENT_MAX_STEPS
    client = client or anthropic.AsyncAnthropic(api_key=settings.ANTHROPIC_API_KEY)

    messages: list[dict[str, Any]] = [{"role": "user", "content": f"Meeting transcript:\n\n{transcript}"}]
    trace: list[TraceStep] = []
    usage = AgentUsage()
    estimate: dict[str, Any] | None = None

    def result(status: AgentStatus, answer: str = "") -> AgentResult:
        if status == "completed" and estimate is None:
            status = "no_estimate"
        logger.info("agent_finished", status=status, steps=len(trace), **usage.model_dump())
        return AgentResult(
            status=status,
            model=model,
            effort=effort,
            prompt_version=PROMPT_VERSION,
            estimate=estimate,
            answer=answer,
            trace=trace,
            usage=usage,
        )

    for step in range(1, max_steps + 1):
        response = await client.messages.create(
            model=model,
            max_tokens=MAX_TOKENS,
            system=SYSTEM_PROMPT,
            tools=TOOL_DEFINITIONS,
            messages=messages,
            thinking={"type": "adaptive", "display": "summarized"},
            output_config={"effort": effort},
        )
        input_tokens = response.usage.input_tokens
        output_tokens = response.usage.output_tokens
        usage.llm_calls += 1
        usage.input_tokens += input_tokens
        usage.output_tokens += output_tokens
        usage.cost_usd = round(usage.cost_usd + cost_usd(model, input_tokens, output_tokens), 6)

        tool_uses = [block for block in response.content if block.type == "tool_use"]
        logger.info(
            "agent_step",
            step=step,
            stop_reason=response.stop_reason,
            tools=[block.name for block in tool_uses],
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        )

        if response.stop_reason != "tool_use" or not tool_uses:
            # No action requested (or the turn was cut short): this step ends the run.
            answer = _answer(response.content)
            if response.stop_reason == "refusal":
                answer = "\n".join(filter(None, [answer, _refusal_note(response)]))
            trace.append(
                TraceStep(
                    step=step,
                    stop_reason=response.stop_reason,
                    reasoning=_reasoning(response.content),
                    answer=answer,
                )
            )
            return result(_STATUS_BY_STOP_REASON.get(response.stop_reason or "", "stopped"), answer)

        # The assistant turn goes back unchanged: thinking blocks must be replayed as received.
        messages.append({"role": "assistant", "content": response.content})
        records: list[ToolCallRecord] = []
        tool_results: list[dict[str, Any]] = []
        # One after another, not gathered: the searches share the request's database session.
        for block in tool_uses:
            outcome = await tools.execute(block.name, block.input)
            if block.name == CALCULATE_ESTIMATE and not outcome.is_error:
                estimate = outcome.data
            tool_result: dict[str, Any] = {"type": "tool_result", "tool_use_id": block.id, "content": outcome.content}
            if outcome.is_error:
                tool_result["is_error"] = True
            tool_results.append(tool_result)
            records.append(
                ToolCallRecord(
                    tool=block.name,
                    arguments=dict(block.input),
                    observation=outcome.summary,
                    is_error=outcome.is_error,
                )
            )
        # Every result of the turn in a single user message, each tied to its call by tool_use_id.
        messages.append({"role": "user", "content": tool_results})
        trace.append(
            TraceStep(
                step=step,
                stop_reason=response.stop_reason,
                reasoning=_reasoning(response.content),
                tool_calls=records,
            )
        )

    return result("max_steps_exceeded")
