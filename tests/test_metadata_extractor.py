"""Extractor LLM de project_metadata: parseo robusto y degradación segura."""

from app.services.metadata_extractor import EXTRACTION_MAX_TOKENS, extract_metadata
from app.services.sessions import ProjectMetadata
from tests.helpers import FakeLLM

PREVIOUS = ProjectMetadata(project_name="Hotelia", mentioned_technologies=["React"])


def run(llm):
    return extract_metadata(
        llm,
        PREVIOUS,
        transcript="Seremos 4 personas y usaremos FastAPI",
        attachments_text="",
        answer="Estimación: 400 h",
    )


def test_extracted_facts_are_merged_with_previous():
    llm = FakeLLM()
    result = run(llm)

    assert result.project_name == "Hotelia"
    assert result.assumed_team_size == 4
    assert result.mentioned_technologies == ["React", "FastAPI"]
    assert llm.calls[0][0]["role"] == "system"


def test_json_wrapped_in_code_fence_and_prose_is_parsed():
    llm = FakeLLM(
        extractor_text='Aquí tienes:\n```json\n{"project_name": null, "assumed_team_size": 6, '
        '"mentioned_technologies": ["Go"], "agreed_scope": "Solo backend"}\n```'
    )
    result = run(llm)
    assert result.assumed_team_size == 6
    assert result.agreed_scope == "Solo backend"
    assert "Go" in result.mentioned_technologies


def test_invalid_json_keeps_previous_metadata():
    assert run(FakeLLM(extractor_text="no tengo ni idea")) == PREVIOUS


def test_schema_violation_keeps_previous_metadata():
    llm = FakeLLM(extractor_text='{"assumed_team_size": "muchos"}')
    assert run(llm) == PREVIOUS


def test_provider_error_keeps_previous_metadata():
    class Broken:
        def complete(self, messages, max_tokens=4000):
            raise RuntimeError("caído")

    assert run(Broken()) == PREVIOUS


def test_extractor_uses_small_token_budget():
    seen = {}

    class Spy(FakeLLM):
        def complete(self, messages, max_tokens=4000):
            seen["max_tokens"] = max_tokens
            return super().complete(messages, max_tokens)

    run(Spy())
    assert seen["max_tokens"] == EXTRACTION_MAX_TOKENS == 500
