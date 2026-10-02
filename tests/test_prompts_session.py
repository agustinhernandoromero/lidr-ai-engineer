"""Render de los prompts de sesión (memoria) y del extractor de metadata."""

import pytest

from app.prompts.loader import available_versions, render_extraction_prompt, render_session_prompt

EMPTY = {
    "project_name": None,
    "assumed_team_size": None,
    "mentioned_technologies": [],
    "agreed_scope": None,
}
KNOWN = {
    "project_name": "Hotelia",
    "assumed_team_size": 4,
    "mentioned_technologies": ["React", "FastAPI"],
    "agreed_scope": "MVP sin pagos online",
}


def render(metadata, attachments_text="", version="v1"):
    return render_session_prompt(
        transcript="Queremos un portal de reservas para hoteles pequeños.",
        project_type="web_saas",
        detail_level="medium",
        output_format="phases_table",
        metadata=metadata,
        attachments_text=attachments_text,
        version=version,
    )


def test_empty_metadata_renders_empty_block():
    system, _ = render(EMPTY)
    assert "<project_metadata>\n</project_metadata>" in system


def test_known_metadata_is_injected_in_system():
    system, _ = render(KNOWN)
    block = system.split("<project_metadata>")[1].split("</project_metadata>")[0]
    assert "Proyecto: Hotelia" in block
    assert "Equipo asumido: 4 personas" in block
    assert "Tecnologías: React, FastAPI" in block
    assert "Alcance acordado: MVP sin pagos online" in block


def test_user_prompt_carries_transcript_and_attachments():
    _, user = render(EMPTY, attachments_text="--- attachment: a.pdf ---\nKubernetes")
    assert "portal de reservas" in user
    assert "--- attachment: a.pdf ---\nKubernetes" in user


def test_user_prompt_without_attachments_has_no_attachments_block():
    _, user = render(EMPTY)
    assert "<attachments>" not in user


def test_unknown_session_version_raises_value_error():
    with pytest.raises(ValueError):
        render(EMPTY, version="v99")


def test_session_prompts_do_not_leak_into_estimate_versions():
    """El selector de /estimate no debe ofrecer plantillas de sesión."""
    assert set(available_versions()) == {"v1", "v2"}


def test_extraction_prompt_contains_contract_and_inputs():
    system, user = render_extraction_prompt(
        previous=KNOWN,
        transcript="Seremos cinco personas",
        attachments_text="",
        answer="Estimación: 400 h",
    )
    assert "extractor de hechos" in system
    for key in ("project_name", "assumed_team_size", "mentioned_technologies", "agreed_scope"):
        assert key in system
    assert "Hotelia" in user
    assert "Seremos cinco personas" in user
    assert "Estimación: 400 h" in user
