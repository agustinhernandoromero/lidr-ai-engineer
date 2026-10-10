"""Compresión: lo que sale de la ventana va a anclas (literal) o al resumen."""

from app.prompts.loader import render_summary_prompt
from app.services.compression.policy import compress
from app.services.compression.summarizer import summarize
from app.services.sessions import ConversationHistory
from tests.helpers import FakeLLM


def filled_history(n: int, max_turns: int = 2) -> ConversationHistory:
    history = ConversationHistory(max_turns=max_turns)
    for i in range(1, n + 1):
        history.add_turn(f"Turno {i}: requisito {i}", f"Respuesta {i}")
    return history


def test_no_overflow_means_no_llm_call():
    history = filled_history(2)
    llm = FakeLLM()
    report = compress(history, llm, summary_max_tokens=600)
    assert report.evicted == 0 and llm.calls == []


def test_overflow_goes_to_summary_and_window_is_restored():
    history = filled_history(4)
    llm = FakeLLM()
    report = compress(history, llm, summary_max_tokens=600)

    assert report.evicted == 2 and report.summary_updated
    assert len(history) == 2
    assert history.summary.startswith("Resumen acumulado")
    assert "Turno 1: requisito 1" in llm.summarizer_calls[0][-1]["content"]


def test_anchor_survives_verbatim_and_is_not_summarized():
    history = ConversationHistory(max_turns=1)
    history.add_turn("El presupuesto está cerrado en 30.000 euros", "Entendido")
    history.add_turn("Añadimos login", "Ok")
    llm = FakeLLM()

    report = compress(history, llm, summary_max_tokens=600)

    assert report.anchors_promoted == ["budget_locked"]
    assert history.anchors[0].user == "El presupuesto está cerrado en 30.000 euros"
    assert llm.summarizer_calls == []


def test_summarizer_failure_keeps_previous_summary():
    history = filled_history(3)
    history.summary = "Resumen previo"
    report = compress(history, FakeLLM(fail_summarizer=True), summary_max_tokens=600)
    assert history.summary == "Resumen previo"
    assert not report.summary_updated
    assert len(history) == 2


def test_summarizer_returns_none_on_empty_text():
    class Empty(FakeLLM):
        def complete(self, messages, max_tokens=4000, json_schema=None):
            return {"text": "  ", "model": "m", "provider": "p", "fallback_used": False}

    assert summarize(Empty(), None, [("a", "b")], max_tokens=600) is None


def test_summary_prompt_truncates_long_assistant_answers():
    _, user = render_summary_prompt(previous_summary=None, evicted=[("u", "x" * 5000)])
    assert "x" * 1500 in user and "x" * 1600 not in user


def test_history_add_turn_no_longer_drops_and_pop_overflow_returns_oldest():
    history = filled_history(3)
    assert len(history) == 3
    assert history.pop_overflow() == [("Turno 1: requisito 1", "Respuesta 1")]
    assert len(history) == 2
