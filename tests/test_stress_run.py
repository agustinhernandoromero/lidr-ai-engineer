"""Runner de estrés: ensayo completo con LLM falso (coste $0)."""

import csv

from evals.stress.run import COLUMNS, main


def run_fake(tmp_path, *extra):
    out = tmp_path / "results.csv"
    code = main(["--in-process", "--fake-llm", "--output", str(out),
                 "--pdf-dir", str(tmp_path / "pdfs"), *extra])
    rows = list(csv.DictReader(out.open(encoding="utf-8")))
    return code, rows


def test_full_fake_run_writes_50_rows_with_all_columns(tmp_path):
    code, rows = run_fake(tmp_path)
    assert code == 0
    assert len(rows) == 3 * 10 + 5 * 4
    assert list(rows[0]) == COLUMNS
    multiturn = [r for r in rows if r["block"] == "multiturn"]
    assert {r["scenario"] for r in multiturn} == {"growing", "pivot", "contradiction"}
    assert all(r["status"] == "ok" for r in rows)


def test_repeated_attachment_turns_hit_the_exact_cache(tmp_path):
    _, rows = run_fake(tmp_path)
    att20 = [r for r in rows if r["block"] == "attachment" and r["attachment_kb"] == "20"]
    assert [r["cache_hit_kind"] for r in att20] == ["none", "exact", "exact", "exact"]


def test_memory_columns_are_filled_for_later_turns(tmp_path):
    _, rows = run_fake(tmp_path)
    turn10 = [r for r in rows if r["block"] == "multiturn" and r["turn_index"] == "10"]
    assert len(turn10) == 3
    for row in turn10:
        assert 0.0 <= float(row["memory_recall"]) <= 1.0
        assert float(row["memory_recall_with_window"]) >= float(row["memory_recall"])


def test_budget_brake_stops_and_keeps_rows(tmp_path):
    code, rows = run_fake(tmp_path, "--max-cost", "-1")
    assert code == 2
    assert len(rows) == 1  # para tras el primer turno, pero lo guarda


def test_failed_turn_is_recorded_and_the_run_continues(tmp_path, monkeypatch):
    from tests import helpers

    original = helpers.FakeLLM.complete
    state = {"n": 0}

    def flaky(self, messages, max_tokens=4000, json_schema=None):
        if json_schema is not None:
            state["n"] += 1
            if state["n"] in (2, 3, 4):  # turno 2 de growing: 3 intentos inválidos
                return {"text": "no json", "model": "f", "provider": "fake", "fallback_used": False}
        return original(self, messages, max_tokens, json_schema)

    monkeypatch.setattr(helpers.FakeLLM, "complete", flaky)
    code, rows = run_fake(tmp_path, "--scenarios", "growing", "--attachment-sizes", "0",
                          "--repeats", "1")
    assert code == 0
    statuses = [r["status"] for r in rows if r["block"] == "multiturn"]
    assert statuses[1] == "error" and statuses.count("ok") == 9
