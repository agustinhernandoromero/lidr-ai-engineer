"""Request, result and trace of an agent run, shared by the loop, the endpoint and the script."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

AgentStatus = Literal["completed", "no_estimate", "max_steps_exceeded", "refused", "truncated", "stopped"]


class AgentRequest(BaseModel):
    transcript: str = Field(min_length=20, max_length=50_000, description="Meeting transcript to estimate.")


class ToolCallRecord(BaseModel):
    """One action of a step and what came back from it."""

    tool: str
    arguments: dict[str, Any]
    observation: str  # one-line summary; the model received the full JSON
    is_error: bool = False


class TraceStep(BaseModel):
    """One model call: what it reasoned, what it did and what it observed."""

    step: int
    stop_reason: str | None
    reasoning: str
    tool_calls: list[ToolCallRecord] = []
    answer: str = ""  # only on the step that ends the run


class AgentUsage(BaseModel):
    llm_calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0


class AgentResult(BaseModel):
    status: AgentStatus
    model: str
    effort: str
    prompt_version: str
    estimate: dict[str, Any] | None  # output of the last successful calculate_estimate
    answer: str  # the model's closing explanation
    trace: list[TraceStep]
    usage: AgentUsage
