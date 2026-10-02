"""Unitarios del estado de sesión: ventana deslizante y fusión de metadata."""

import pytest

from app.services.sessions import ConversationHistory, ProjectMetadata, SessionStore


def test_history_keeps_only_last_max_turns_pairs():
    history = ConversationHistory(max_turns=2)
    for i in range(1, 5):
        history.add_turn(f"user {i}", f"assistant {i}")

    assert len(history) == 2
    assert history.as_dicts() == [
        {"user": "user 3", "assistant": "assistant 3"},
        {"user": "user 4", "assistant": "assistant 4"},
    ]


def test_to_messages_list_always_starts_with_fresh_system_prompt():
    history = ConversationHistory(max_turns=6)
    history.add_turn("hola", "respuesta")

    first = history.to_messages_list("system A")
    second = history.to_messages_list("system B")

    assert first[0] == {"role": "system", "content": "system A"}
    assert second[0] == {"role": "system", "content": "system B"}
    assert [m["role"] for m in second] == ["system", "user", "assistant"]


def test_history_rejects_non_positive_window():
    with pytest.raises(ValueError):
        ConversationHistory(max_turns=0)


def test_metadata_merge_keeps_known_facts_and_unions_technologies():
    previous = ProjectMetadata(
        project_name="Hotelia",
        mentioned_technologies=["React", "PostgreSQL"],
        agreed_scope="MVP de reservas",
    )
    new = ProjectMetadata(
        project_name=None,
        assumed_team_size=4,
        mentioned_technologies=["react", "FastAPI"],
        agreed_scope="MVP de reservas sin pagos online",
    )

    merged = previous.merge(new)

    assert merged.project_name == "Hotelia"
    assert merged.assumed_team_size == 4
    assert merged.mentioned_technologies == ["React", "PostgreSQL", "FastAPI"]
    assert merged.agreed_scope == "MVP de reservas sin pagos online"


def test_metadata_is_empty():
    assert ProjectMetadata().is_empty()
    assert not ProjectMetadata(mentioned_technologies=["Go"]).is_empty()


def test_store_creates_unique_sessions_and_returns_none_for_unknown():
    store = SessionStore(max_turns=6)
    a, b = store.create(), store.create()

    assert a.session_id != b.session_id
    assert store.get(a.session_id) is a
    assert store.get("no-existe") is None
    assert a.history.max_turns == 6
