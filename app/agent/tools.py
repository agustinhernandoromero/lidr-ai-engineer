"""Tools of the estimation agent: the JSON schemas the model reads and the Python that runs them.

    search_budgets      -> wraps the session 10 retrieval (hybrid search, no rerank)
    calculate_estimate  -> deterministic Python, no LLM call

The model only ever sees the schemas below, so their descriptions are what steer
its choices. Every input is validated with pydantic before a tool runs: a bad
input comes back to the model as an error result it can correct.
"""

from __future__ import annotations

import asyncio
import json
import statistics
from dataclasses import dataclass, field
from typing import Any

import structlog
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from app.retrieval.pipeline import retrieve
from app.retrieval.types import RetrievedChunk

logger = structlog.get_logger(__name__)

SEARCH_MODE = "hybrid"  # session 10 winner, also used by the session 11 generator
RERANK = False
MAX_RESULTS = 5  # items returned per search: enough to compare, few tokens
PREVIEW_CHARS = 160
CONTINGENCY_FACTOR = 0.15  # flat buffer on every component, visible in the output

SEARCH_BUDGETS = "search_budgets"
CALCULATE_ESTIMATE = "calculate_estimate"

TOOL_DEFINITIONS: list[dict[str, Any]] = [
    {
        "name": SEARCH_BUDGETS,
        "description": (
            "Search the consultancy's historical budgets for components similar to ONE component "
            "of the project being estimated. Call it once per component, with a short query that "
            "describes that component's functionality (for example 'ERP integration that syncs "
            "invoices and customers with retries'), never with the whole transcript. The corpus is "
            "in English; English queries match best. Returns up to 5 past components, most similar "
            "first, each with its recorded estimated_hours, sector, year, tech stack and cosine "
            "distance: below about 0.30 is a close match, 0.30-0.36 is related work, above about "
            "0.36 the match is weak. If every match is weak, search again with different wording "
            "before deciding the component has no comparable past work. An empty list means the "
            "filters were too narrow: search again with fewer filters."
        ),
        "strict": True,
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Description of a single component to find comparable past work for.",
                },
                "filters": {
                    "anyOf": [
                        {
                            "type": "object",
                            "properties": {
                                "client_sector": {
                                    "type": ["string", "null"],
                                    "description": "Keep only budgets of this client sector, e.g. 'finance'.",
                                },
                                "min_year": {
                                    "type": ["integer", "null"],
                                    "description": "Keep only budgets from this year or later.",
                                },
                                "max_year": {
                                    "type": ["integer", "null"],
                                    "description": "Keep only budgets from this year or earlier.",
                                },
                                "technology": {
                                    "type": ["string", "null"],
                                    "description": "Keep only components whose stack includes this technology, e.g. 'react'.",
                                },
                            },
                            "required": ["client_sector", "min_year", "max_year", "technology"],
                            "additionalProperties": False,
                        },
                        {"type": "null"},
                    ],
                    "description": "Optional metadata filters; null to search the whole corpus (the usual case).",
                },
            },
            "required": ["query", "filters"],
            "additionalProperties": False,
        },
    },
    {
        "name": CALCULATE_ESTIMATE,
        "description": (
            "Compute the effort estimate from the reference hours you collected with search_budgets. "
            "Pass every component of the project in one call, each with the estimated_hours of the "
            "historical items that are genuinely comparable to it (leave out weak matches). The "
            "calculation is deterministic: median of the references plus a 15% contingency per "
            "component, which gets its hours and euros, then the project total in hours and euros. "
            "A component with no references is costed "
            "at 0 hours and flagged unbudgeted: search again for it rather than inventing a number. "
            "Call it again if you change the components or their references."
        ),
        "strict": True,
        "input_schema": {
            "type": "object",
            "properties": {
                "components": {
                    "type": "array",
                    "description": "All components of the project being estimated.",
                    "items": {
                        "type": "object",
                        "properties": {
                            "name": {
                                "type": "string",
                                "description": "Component name as it will appear in the estimate.",
                            },
                            "reference_amounts": {
                                "type": "array",
                                "items": {"type": "number"},
                                "description": "estimated_hours of the comparable historical items; empty if none.",
                            },
                        },
                        "required": ["name", "reference_amounts"],
                        "additionalProperties": False,
                    },
                },
            },
            "required": ["components"],
            "additionalProperties": False,
        },
    },
]


class BudgetFilters(BaseModel):
    model_config = ConfigDict(extra="forbid")

    client_sector: str | None = None
    min_year: int | None = None
    max_year: int | None = None
    technology: str | None = None

    def is_empty(self) -> bool:
        return all(value is None for value in self.model_dump().values())


class SearchBudgetsInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str = Field(min_length=1)
    filters: BudgetFilters | None = None


class ComponentReferences(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1)
    reference_amounts: list[float]

    @field_validator("reference_amounts")
    @classmethod
    def _non_negative(cls, amounts: list[float]) -> list[float]:
        if any(amount < 0 for amount in amounts):
            raise ValueError("reference amounts are hours and cannot be negative")
        return amounts


class CalculateEstimateInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    components: list[ComponentReferences] = Field(min_length=1)


@dataclass(frozen=True)
class ToolOutcome:
    """What a tool call produced: the text the model reads and what the trace keeps."""

    content: str  # JSON string sent back as the tool_result
    summary: str  # one line for the trace observation
    is_error: bool = False
    data: dict[str, Any] = field(default_factory=dict)


def calculate_estimate(components: list[ComponentReferences], hourly_rate_eur: float) -> dict[str, Any]:
    """Cost each component from its reference hours, then total. No LLM involved.

    The median keeps one outlier budget from dragging a component; an empty
    reference list is costed at 0 and flagged instead of inventing a number.
    """
    breakdown: list[dict[str, Any]] = []
    for component in components:
        refs = component.reference_amounts
        if refs:
            central = statistics.median(refs)
            hours = round(central * (1 + CONTINGENCY_FACTOR), 1)
        else:
            central, hours = 0.0, 0.0
        breakdown.append(
            {
                "name": component.name,
                "reference_count": len(refs),
                "reference_median_hours": central,
                "estimated_hours": hours,
                "estimated_eur": round(hours * hourly_rate_eur),
                "unbudgeted": not refs,
            }
        )

    total_hours = round(sum(item["estimated_hours"] for item in breakdown), 1)
    unbudgeted = [item["name"] for item in breakdown if item["unbudgeted"]]
    count = f"{len(breakdown)} component" + ("s" if len(breakdown) != 1 else "")
    summary = f"total={total_hours}h ({round(total_hours * hourly_rate_eur):,} EUR) across {count}"
    if unbudgeted:
        summary += f"; unbudgeted: {', '.join(unbudgeted)}"
    return {
        "components": breakdown,
        "total_hours": total_hours,
        "hourly_rate_eur": hourly_rate_eur,
        "total_eur": round(total_hours * hourly_rate_eur),
        "contingency_factor": CONTINGENCY_FACTOR,
        "summary": summary,
    }


def component_name(chunk: RetrievedChunk) -> str:
    for text_line in chunk.content.splitlines():
        if text_line.startswith("Component: "):
            return text_line.removeprefix("Component: ").strip()
    return chunk.metadata.get("component_id", f"chunk-{chunk.id}")


def matches_filters(chunk: RetrievedChunk, filters: BudgetFilters) -> bool:
    meta = chunk.metadata
    if filters.client_sector and str(meta.get("client_sector", "")).lower() != filters.client_sector.lower():
        return False
    year = meta.get("year")
    if filters.min_year is not None and (year is None or int(year) < filters.min_year):
        return False
    if filters.max_year is not None and (year is None or int(year) > filters.max_year):
        return False
    if filters.technology:
        wanted = filters.technology.lower()
        stack = [str(tech).lower() for tech in meta.get("tech_stack") or []]
        stack.append(str(meta.get("main_technology", "")).lower())
        if not any(wanted in tech for tech in stack):
            return False
    return True


def budget_item(chunk: RetrievedChunk) -> dict[str, Any]:
    """The fields of a retrieved chunk the model needs to judge and use it."""
    meta = chunk.metadata
    description = next(
        (ln.removeprefix("Description: ") for ln in chunk.content.splitlines() if ln.startswith("Description: ")),
        "",
    )
    return {
        "source_id": f"{meta.get('budget_id')}::{meta.get('component_id')}",
        "component": component_name(chunk),
        "estimated_hours": meta.get("estimated_hours"),
        "client_sector": meta.get("client_sector"),
        "year": meta.get("year"),
        "tech_stack": meta.get("tech_stack"),
        "complexity": meta.get("complexity"),
        "distance": None if chunk.distance is None else round(chunk.distance, 3),
        "description": description[:PREVIEW_CHARS],
    }


class AgentTools:
    """Runs the agent's tool calls against the real infrastructure of the service."""

    def __init__(self, repository, embedder, hourly_rate_eur: float):
        self._repository = repository
        self._embedder = embedder
        self._hourly_rate_eur = hourly_rate_eur

    async def execute(self, name: str, arguments: dict[str, Any]) -> ToolOutcome:
        """Validate the arguments and run the tool; any failure becomes an error result."""
        try:
            if name == SEARCH_BUDGETS:
                return await self._search_budgets(SearchBudgetsInput.model_validate(arguments))
            if name == CALCULATE_ESTIMATE:
                return self._calculate_estimate(CalculateEstimateInput.model_validate(arguments))
            return _error(f"Unknown tool '{name}'. Available tools: {SEARCH_BUDGETS}, {CALCULATE_ESTIMATE}.")
        except ValidationError as exc:
            return _error(f"Invalid arguments for {name}: {exc.errors(include_url=False)}")
        except Exception as exc:  # noqa: BLE001 - the model gets the failure and can react to it
            logger.exception("agent_tool_failed", tool=name)
            return _error(f"{name} failed: {type(exc).__name__}: {exc}")

    async def _search_budgets(self, args: SearchBudgetsInput) -> ToolOutcome:
        query_vector = await asyncio.to_thread(self._embedder.embed_one, args.query, "query")
        # Whole fused candidate list, so filters act before the cut to MAX_RESULTS.
        candidates = await retrieve(
            self._repository, args.query, query_vector, mode=SEARCH_MODE, rerank=RERANK, top_k=10_000
        )
        filters = args.filters if args.filters and not args.filters.is_empty() else None
        kept = [chunk for chunk in candidates if filters is None or matches_filters(chunk, filters)]
        items = [budget_item(chunk) for chunk in kept[:MAX_RESULTS]]

        payload: dict[str, Any] = {"query": args.query, "items": items}
        if filters is not None:
            payload["filters"] = filters.model_dump(exclude_none=True)
            if not items:
                payload["note"] = (
                    f"No item matched the filters; {len(candidates)} items match the query without them. "
                    "Search again with fewer filters."
                )
        logger.info("agent_search_budgets", query=args.query, candidates=len(candidates), returned=len(items))
        summary = (
            "; ".join(
                f"{item['component']} ({item['source_id']}, {item['estimated_hours']}h, d={item['distance']})"
                for item in items
            )
            or payload.get("note", "no items")
        )
        return ToolOutcome(
            content=json.dumps(payload, ensure_ascii=False),
            summary=f"{len(items)} items: {summary}",
            data=payload,
        )

    def _calculate_estimate(self, args: CalculateEstimateInput) -> ToolOutcome:
        result = calculate_estimate(args.components, self._hourly_rate_eur)
        return ToolOutcome(content=json.dumps(result, ensure_ascii=False), summary=result["summary"], data=result)


def _error(message: str) -> ToolOutcome:
    return ToolOutcome(content=json.dumps({"error": message}, ensure_ascii=False), summary=message, is_error=True)
