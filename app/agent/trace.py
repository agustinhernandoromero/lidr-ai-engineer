"""Plain-text rendering of an agent run: one block per step, then the estimate."""

from __future__ import annotations

import json
import textwrap

from app.agent.schemas import AgentResult

WIDTH = 100


def _wrapped(label: str, text: str, wrap: bool = True) -> list[str]:
    """`label: text`, continuation lines aligned under the text; markdown answers keep their lines."""
    prefix = f"  {label}: "
    indent = " " * len(prefix)
    body = text.strip() or "(none returned)"
    lines: list[str] = []
    for paragraph in body.splitlines():
        if wrap:
            lines += textwrap.wrap(paragraph, WIDTH, initial_indent=indent, subsequent_indent=indent) or [""]
        else:
            lines.append(indent + paragraph if paragraph else "")
    lines[0] = prefix + lines[0].lstrip()
    return lines


def format_action(tool: str, arguments: dict) -> str:
    args = ", ".join(f"{key}={json.dumps(value, ensure_ascii=False)}" for key, value in arguments.items())
    return f"{tool}({args})"


def render_trace(result: AgentResult, title: str = "") -> str:
    usage = result.usage
    out = [
        f"AGENT RUN {title}".rstrip(),
        f"model={result.model} effort={result.effort} prompt={result.prompt_version} status={result.status}",
        f"llm_calls={usage.llm_calls} input_tokens={usage.input_tokens} "
        f"output_tokens={usage.output_tokens} cost_usd={usage.cost_usd:.4f}",
        "",
    ]
    for step in result.trace:
        out.append(f"STEP {step.step}")
        out += _wrapped("reasoning", step.reasoning)
        for call in step.tool_calls:
            out += _wrapped("action", format_action(call.tool, call.arguments))
            out += _wrapped("observation" + (" (error)" if call.is_error else ""), call.observation)
        if not step.tool_calls:
            out += _wrapped(f"answer (stop_reason={step.stop_reason})", step.answer, wrap=False)
        out.append("")

    out.append("ESTIMATE")
    if result.estimate is None:
        out.append("  (no calculate_estimate result)")
    else:
        for item in result.estimate["components"]:
            flag = "  UNBUDGETED" if item["unbudgeted"] else ""
            refs = item["reference_count"]
            out.append(
                f"  {item['name']}: {item['estimated_hours']}h = {item['estimated_eur']:,} EUR "
                f"(median {item['reference_median_hours']}h of {refs} reference{'' if refs == 1 else 's'}){flag}"
            )
        out.append(
            f"  TOTAL: {result.estimate['total_hours']}h = {result.estimate['total_eur']:,} EUR "
            f"at {result.estimate['hourly_rate_eur']} EUR/h, contingency {result.estimate['contingency_factor']:.0%}"
        )
    return "\n".join(out) + "\n"
