"""Session 12: estimation agent with a scripted Anthropic client and an in-memory repository."""

import json
from types import SimpleNamespace

import anthropic
import httpx
import pytest
import pytest_asyncio

from app.agent import loop as loop_module
from app.agent.loop import SYSTEM_PROMPT, cost_usd, run_agent
from app.agent.schemas import AgentResult, AgentUsage, ToolCallRecord, TraceStep
from app.agent.tools import (
    CALCULATE_ESTIMATE,
    MAX_RESULTS,
    SEARCH_BUDGETS,
    TOOL_DEFINITIONS,
    AgentTools,
    ComponentReferences,
    ToolOutcome,
    calculate_estimate,
)
from app.agent.trace import render_trace
from app.main import app
from app.routers import agent as agent_router
from tests.retrieval_fakes import FakeBranchesRepository

RATE = 50


def budget_row(chunk_id, component, hours, *, sector="finance", year=2024, stack=("python",), distance=0.2):
    return SimpleNamespace(
        id=chunk_id,
        document_id=chunk_id,
        chunk_type="budget_component",
        content=f"[Project: P{chunk_id}]\n\nComponent: {component}\nDescription: {component} built for a client.\nEstimated hours: {hours}",
        metadata_={
            "budget_id": f"BUD-2024-{chunk_id:03d}",
            "component_id": f"C-{chunk_id:03d}",
            "estimated_hours": hours,
            "client_sector": sector,
            "year": year,
            "tech_stack": list(stack),
            "main_technology": stack[0],
            "complexity": "medium",
        },
        distance=distance,
    )


class FakeEmbedder:
    def __init__(self):
        self.queries = []

    def embed_one(self, text, task="document"):
        assert task == "query"
        self.queries.append(text)
        return [0.1, 0.2]


def tools_over(*rows) -> AgentTools:
    return AgentTools(FakeBranchesRepository(vector_rows=rows), FakeEmbedder(), RATE)


# --- calculate_estimate -------------------------------------------------------------


def test_calculate_estimate_uses_median_plus_contingency_and_totals_in_hours_and_euros():
    result = calculate_estimate(
        [
            ComponentReferences(name="Backend", reference_amounts=[100, 200, 900]),  # outlier: median 200
            ComponentReferences(name="Mobile app", reference_amounts=[80, 120]),  # even count: median 100
        ],
        RATE,
    )

    backend, mobile = result["components"]
    assert backend["reference_median_hours"] == 200
    assert backend["estimated_hours"] == 230.0
    assert mobile["estimated_hours"] == 115.0
    assert (backend["estimated_eur"], mobile["estimated_eur"]) == (11500, 5750)  # the model never multiplies
    assert result["total_hours"] == 345.0
    assert result["total_eur"] == 17250
    assert result["summary"] == "total=345.0h (17,250 EUR) across 2 components"


def test_component_without_references_is_costed_at_zero_and_flagged():
    result = calculate_estimate([ComponentReferences(name="SAP integration", reference_amounts=[])], RATE)

    item = result["components"][0]
    assert item["estimated_hours"] == 0.0
    assert item["unbudgeted"] is True
    assert result["summary"] == "total=0.0h (0 EUR) across 1 component; unbudgeted: SAP integration"


# --- tool schemas and execution --------------------------------------------------------


def _object_schemas(schema):
    if isinstance(schema, dict):
        if schema.get("type") == "object":
            yield schema
        for value in schema.values():
            yield from _object_schemas(value)
    elif isinstance(schema, list):
        for value in schema:
            yield from _object_schemas(value)


def test_tool_schemas_follow_strict_mode_rules():
    assert [tool["name"] for tool in TOOL_DEFINITIONS] == [SEARCH_BUDGETS, CALCULATE_ESTIMATE]
    for tool in TOOL_DEFINITIONS:
        assert tool["strict"] is True
        assert "type" not in tool and "function" not in tool  # Anthropic shape: input_schema at top level
        for obj in _object_schemas(tool["input_schema"]):
            assert obj["additionalProperties"] is False
            assert sorted(obj["required"]) == sorted(obj["properties"])


@pytest.mark.asyncio
async def test_search_budgets_returns_items_with_hours_and_source_ids():
    rows = [budget_row(i, f"Component {i}", 100 + i) for i in range(1, 8)]
    tools = tools_over(*rows)

    outcome = await tools.execute(SEARCH_BUDGETS, {"query": "ERP integration", "filters": None})

    assert outcome.is_error is False
    items = json.loads(outcome.content)["items"]
    assert len(items) == MAX_RESULTS
    assert items[0]["source_id"] == "BUD-2024-001::C-001"
    assert items[0]["component"] == "Component 1"
    assert items[0]["estimated_hours"] == 101
    assert items[0]["distance"] == 0.2
    assert outcome.summary.startswith("5 items: Component 1 (BUD-2024-001::C-001, 101h, d=0.2)")


@pytest.mark.asyncio
async def test_search_budgets_filters_on_metadata_before_cutting_the_list():
    rows = [
        budget_row(1, "Old finance", 100, year=2021),
        budget_row(2, "Health backend", 120, sector="healthcare", stack=("django", "react")),
        budget_row(3, "New finance", 140, year=2024, stack=("react",)),
    ]
    tools = tools_over(*rows)

    outcome = await tools.execute(
        SEARCH_BUDGETS,
        {"query": "backend", "filters": {"client_sector": "Finance", "min_year": 2022, "max_year": None, "technology": None}},
    )
    react = await tools.execute(
        SEARCH_BUDGETS,
        {"query": "front", "filters": {"client_sector": None, "min_year": None, "max_year": None, "technology": "React"}},
    )

    assert [item["component"] for item in json.loads(outcome.content)["items"]] == ["New finance"]
    assert [item["component"] for item in json.loads(react.content)["items"]] == ["Health backend", "New finance"]


@pytest.mark.asyncio
async def test_filters_that_remove_everything_return_a_note_to_search_again():
    tools = tools_over(budget_row(1, "Payments", 100))

    outcome = await tools.execute(
        SEARCH_BUDGETS,
        {"query": "payments", "filters": {"client_sector": "logistics", "min_year": None, "max_year": None, "technology": None}},
    )

    payload = json.loads(outcome.content)
    assert payload["items"] == []
    assert "fewer filters" in payload["note"]
    assert outcome.is_error is False


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("name", "arguments", "message"),
    [
        (SEARCH_BUDGETS, {"query": ""}, "Invalid arguments for search_budgets"),
        (CALCULATE_ESTIMATE, {"components": []}, "Invalid arguments for calculate_estimate"),
        (CALCULATE_ESTIMATE, {"components": [{"name": "X", "reference_amounts": [-5]}]}, "cannot be negative"),
        ("delete_budgets", {}, "Unknown tool 'delete_budgets'"),
    ],
)
async def test_bad_calls_come_back_as_error_results(name, arguments, message):
    outcome = await tools_over().execute(name, arguments)

    assert outcome.is_error is True
    assert message in json.loads(outcome.content)["error"]


@pytest.mark.asyncio
async def test_a_failing_search_becomes_an_error_result_instead_of_breaking_the_run():
    class BrokenEmbedder:
        def embed_one(self, text, task="document"):
            raise RuntimeError("quota exceeded")

    tools = AgentTools(FakeBranchesRepository(), BrokenEmbedder(), RATE)

    outcome = await tools.execute(SEARCH_BUDGETS, {"query": "backend", "filters": None})

    assert outcome.is_error is True
    assert "RuntimeError: quota exceeded" in outcome.summary


# --- the loop ------------------------------------------------------------------------------


def thinking(text):
    return SimpleNamespace(type="thinking", thinking=text)


def text(value):
    return SimpleNamespace(type="text", text=value)


def tool_use(call_id, name, arguments):
    return SimpleNamespace(type="tool_use", id=call_id, name=name, input=arguments)


def response(stop_reason, *blocks, tokens=(1000, 200)):
    return SimpleNamespace(
        content=list(blocks),
        stop_reason=stop_reason,
        usage=SimpleNamespace(input_tokens=tokens[0], output_tokens=tokens[1]),
    )


class ScriptedClient:
    """Stands in for AsyncAnthropic: returns queued responses and records each request."""

    def __init__(self, *responses):
        self.responses = list(responses)
        self.requests = []
        self.messages = self

    async def create(self, **kwargs):
        self.requests.append({**kwargs, "messages": list(kwargs["messages"])})
        return self.responses.pop(0)


class RecordingTools:
    """Scripted tool results keyed by tool name; records every call."""

    def __init__(self, outcomes):
        self.outcomes = outcomes
        self.calls = []

    async def execute(self, name, arguments):
        self.calls.append((name, arguments))
        return self.outcomes[name]


SEARCH = ToolOutcome(content='{"items": []}', summary="2 items: ...")
ESTIMATE = {
    "components": [
        {"name": "Backend", "reference_count": 2, "reference_median_hours": 150, "estimated_hours": 172.5, "estimated_eur": 8625, "unbudgeted": False},
        {"name": "SAP integration", "reference_count": 0, "reference_median_hours": 0.0, "estimated_hours": 0.0, "estimated_eur": 0, "unbudgeted": True},
    ],
    "total_hours": 172.5,
    "hourly_rate_eur": 50,
    "total_eur": 8625,
    "contingency_factor": 0.15,
    "summary": "total=172.5h (8,625 EUR) across 2 components; unbudgeted: SAP integration",
}
CALC = ToolOutcome(content=json.dumps(ESTIMATE), summary=ESTIMATE["summary"], data=ESTIMATE)


@pytest.mark.asyncio
async def test_loop_runs_tools_returns_results_by_call_id_and_stops_on_the_final_answer():
    first = response(
        "tool_use",
        thinking("Two components: a backend and an SAP integration."),
        tool_use("tu_1", SEARCH_BUDGETS, {"query": "logistics backend", "filters": None}),
        tool_use("tu_2", SEARCH_BUDGETS, {"query": "SAP integration", "filters": None}),
    )
    client = ScriptedClient(
        first,
        response(
            "tool_use",
            thinking("Backend has two references; SAP has none."),
            tool_use("tu_3", CALCULATE_ESTIMATE, {"components": [{"name": "Backend", "reference_amounts": [140, 160]}]}),
        ),
        response("end_turn", thinking("Done."), text("Total 172.5 h."), tokens=(3000, 100)),
    )
    tools = RecordingTools({SEARCH_BUDGETS: SEARCH, CALCULATE_ESTIMATE: CALC})

    result = await run_agent("A long enough transcript.", tools, client=client, model="claude-sonnet-5-5", effort="medium", max_steps=5)

    assert result.status == "completed"
    assert result.estimate == ESTIMATE
    assert result.answer == "Total 172.5 h."
    assert [name for name, _ in tools.calls] == [SEARCH_BUDGETS, SEARCH_BUDGETS, CALCULATE_ESTIMATE]
    assert [step.step for step in result.trace] == [1, 2, 3]
    assert result.trace[0].reasoning == "Two components: a backend and an SAP integration."
    assert [call.arguments["query"] for call in result.trace[0].tool_calls] == ["logistics backend", "SAP integration"]
    assert result.trace[2].answer == "Total 172.5 h."

    # Second request: the assistant turn replayed as received, then one user message with both results.
    history = client.requests[1]["messages"]
    assert [m["role"] for m in history] == ["user", "assistant", "user"]
    assert history[1]["content"] is first.content  # thinking blocks included, untouched
    assert [r["tool_use_id"] for r in history[2]["content"]] == ["tu_1", "tu_2"]
    assert all(r["type"] == "tool_result" and "is_error" not in r for r in history[2]["content"])

    assert result.usage == AgentUsage(llm_calls=3, input_tokens=5000, output_tokens=500, cost_usd=cost_usd("claude-sonnet-5-5", 5000, 500))
    assert result.usage.cost_usd == pytest.approx(0.015)  # 5000 x 2 $/M + 500 x 10 $/M


@pytest.mark.asyncio
async def test_every_request_carries_system_tools_reasoning_summaries_and_effort_without_forcing_a_tool():
    client = ScriptedClient(response("end_turn", text("No components.")))

    await run_agent("A long enough transcript.", RecordingTools({}), client=client, model="claude-haiku-5-5", effort="low", max_steps=3)

    request = client.requests[0]
    assert request["model"] == "claude-haiku-5-5"
    assert request["system"] == SYSTEM_PROMPT
    assert request["tools"] == TOOL_DEFINITIONS
    assert request["thinking"] == {"type": "adaptive", "display": "summarized"}
    assert request["output_config"] == {"effort": "low"}
    assert "tool_choice" not in request
    assert request["messages"][0]["content"].endswith("A long enough transcript.")


@pytest.mark.asyncio
async def test_answer_without_calculate_estimate_is_reported_as_no_estimate():
    client = ScriptedClient(response("end_turn", text("I cannot estimate this.")))

    result = await run_agent("A long enough transcript.", RecordingTools({}), client=client, model="claude-sonnet-5-5", max_steps=3)

    assert result.status == "no_estimate"
    assert result.estimate is None


@pytest.mark.asyncio
async def test_loop_stops_at_max_steps_when_the_model_keeps_calling_tools():
    search = response("tool_use", tool_use("tu", SEARCH_BUDGETS, {"query": "x", "filters": None}))
    client = ScriptedClient(*[search] * 3)

    result = await run_agent("A long enough transcript.", RecordingTools({SEARCH_BUDGETS: SEARCH}), client=client, model="claude-sonnet-5-5", max_steps=3)

    assert result.status == "max_steps_exceeded"
    assert result.usage.llm_calls == 3
    assert len(result.trace) == 3


@pytest.mark.asyncio
async def test_tool_errors_go_back_flagged_so_the_model_can_correct_itself():
    error = ToolOutcome(content='{"error": "bad"}', summary="bad", is_error=True)
    client = ScriptedClient(
        response("tool_use", tool_use("tu_1", CALCULATE_ESTIMATE, {"components": []})),
        response("end_turn", text("Gave up.")),
    )

    result = await run_agent("A long enough transcript.", RecordingTools({CALCULATE_ESTIMATE: error}), client=client, model="claude-sonnet-5-5", max_steps=3)

    tool_result = client.requests[1]["messages"][2]["content"][0]
    assert tool_result == {"type": "tool_result", "tool_use_id": "tu_1", "content": '{"error": "bad"}', "is_error": True}
    assert result.trace[0].tool_calls[0].is_error is True
    assert result.status == "no_estimate"


@pytest.mark.asyncio
async def test_a_refusal_ends_the_run_and_the_trace_keeps_its_category():
    refused = response("refusal", tokens=(3000, 0))
    refused.stop_details = SimpleNamespace(type="refusal", category="reasoning_extraction", explanation="Declined.")
    client = ScriptedClient(refused)

    result = await run_agent("A long enough transcript.", RecordingTools({}), client=client, model="claude-sonnet-5-5", max_steps=3)

    assert result.status == "refused"
    assert result.answer == "Refused by the model (category=reasoning_extraction): Declined."
    assert result.trace[0].answer == result.answer


@pytest.mark.asyncio
async def test_a_turn_cut_by_max_tokens_does_not_run_its_tool_call():
    client = ScriptedClient(response("max_tokens", tool_use("tu_1", SEARCH_BUDGETS, {"query": "half"})))
    tools = RecordingTools({SEARCH_BUDGETS: SEARCH})

    result = await run_agent("A long enough transcript.", tools, client=client, model="claude-sonnet-5-5", max_steps=3)

    assert result.status == "truncated"
    assert tools.calls == []


# --- trace rendering ---------------------------------------------------------------------


def sample_result() -> AgentResult:
    return AgentResult(
        status="completed",
        model="claude-sonnet-5-5",
        effort="medium",
        prompt_version="agent-v1",
        estimate=ESTIMATE,
        answer="Total 172.5 h.",
        trace=[
            TraceStep(
                step=1,
                stop_reason="tool_use",
                reasoning="Search the backend first.",
                tool_calls=[ToolCallRecord(tool=SEARCH_BUDGETS, arguments={"query": "logistics backend", "filters": None}, observation="2 items: ...")],
            ),
            TraceStep(step=2, stop_reason="end_turn", reasoning="", answer="Total 172.5 h."),
        ],
        usage=AgentUsage(llm_calls=2, input_tokens=2000, output_tokens=300, cost_usd=0.007),
    )


def test_trace_shows_reasoning_action_and_observation_per_step_and_the_estimate():
    rendered = render_trace(sample_result(), title="on sample.txt")

    assert "STEP 1\n  reasoning: Search the backend first.\n" in rendered
    assert '  action: search_budgets(query="logistics backend", filters=null)\n' in rendered
    assert "  observation: 2 items: ...\n" in rendered
    assert "STEP 2\n  reasoning: (none returned)\n  answer (stop_reason=end_turn): Total 172.5 h." in rendered


def test_final_answer_keeps_its_markdown_lines_instead_of_rewrapping_them():
    result = sample_result()
    long_row = "| Backend | 150 | 172.5 | " + "x" * 120 + " |"
    result.trace[1].answer = f"**Estimate**\n\n{long_row}"

    rendered = render_trace(result)

    assert "  answer (stop_reason=end_turn): **Estimate**\n\n" in rendered
    assert long_row in rendered  # one line, not wrapped at 100 characters
    assert "  Backend: 172.5h = 8,625 EUR (median 150h of 2 references)\n" in rendered
    assert "  SAP integration: 0.0h = 0 EUR (median 0.0h of 0 references)  UNBUDGETED" in rendered
    assert "  TOTAL: 172.5h = 8,625 EUR at 50 EUR/h, contingency 15%" in rendered


# --- endpoint ----------------------------------------------------------------------------


@pytest_asyncio.fixture
async def api_client():
    app.dependency_overrides[agent_router.get_agent_tools] = lambda: RecordingTools({})
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        yield client
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_endpoint_returns_the_estimate_and_its_trace(api_client, monkeypatch):
    received = {}

    async def fake_run_agent(transcript, tools):
        received["transcript"] = transcript
        return sample_result()

    monkeypatch.setattr(agent_router, "run_agent", fake_run_agent)

    response_ = await api_client.post("/api/v1/estimate/agent", json={"transcript": "Reunión: backend y app móvil."})

    assert response_.status_code == 200
    data = response_.json()
    assert received["transcript"] == "Reunión: backend y app móvil."
    assert data["status"] == "completed"
    assert data["estimate"]["total_eur"] == 8625
    assert data["trace"][0]["tool_calls"][0]["tool"] == SEARCH_BUDGETS


@pytest.mark.asyncio
async def test_endpoint_rejects_a_transcript_too_short_to_estimate(api_client):
    response_ = await api_client.post("/api/v1/estimate/agent", json={"transcript": "hola"})

    assert response_.status_code == 422


@pytest.mark.asyncio
async def test_endpoint_maps_a_model_failure_to_502(api_client, monkeypatch):
    async def failing_run_agent(transcript, tools):
        raise anthropic.APIConnectionError(request=httpx.Request("POST", "https://api.anthropic.com/v1/messages"))

    monkeypatch.setattr(agent_router, "run_agent", failing_run_agent)

    response_ = await api_client.post("/api/v1/estimate/agent", json={"transcript": "Reunión: backend y app móvil."})

    assert response_.status_code == 502
    assert "APIConnectionError" in response_.json()["detail"]


def test_unknown_model_costs_zero_instead_of_failing():
    assert loop_module.cost_usd("some-future-model", 1000, 1000) == 0.0
