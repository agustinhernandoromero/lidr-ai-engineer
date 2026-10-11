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


def test_wall_clock_is_measured_from_the_client(tmp_path):
    """wall_clock_ms incluye red y extracción del PDF: nunca menor que la latencia del servicio."""
    _, rows = run_fake(tmp_path, "--scenarios", "growing", "--turns", "2",
                       "--attachment-sizes", "0,5", "--repeats", "1")
    for row in rows:
        assert float(row["wall_clock_ms"]) > 0
        if row["cache_hit_kind"] == "none":
            assert float(row["wall_clock_ms"]) >= float(row["latency_ms"])


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


def test_scenario_turn_stays_aligned_after_a_failed_turn(tmp_path, monkeypatch):
    from tests import helpers

    original = helpers.FakeLLM.complete
    state = {"n": 0}

    def flaky(self, messages, max_tokens=4000, json_schema=None):
        if json_schema is not None:
            state["n"] += 1
            if state["n"] in (2, 3, 4):
                return {"text": "no json", "model": "f", "provider": "fake", "fallback_used": False}
        return original(self, messages, max_tokens, json_schema)

    monkeypatch.setattr(helpers.FakeLLM, "complete", flaky)
    _, rows = run_fake(tmp_path, "--scenarios", "growing", "--attachment-sizes", "0", "--repeats", "1")
    multiturn = [r for r in rows if r["block"] == "multiturn"]
    assert [r["scenario_turn"] for r in multiturn] == [str(i) for i in range(1, 11)]
    assert multiturn[-1]["turn_index"] == "9"  # el servidor no contó el turno fallido


def test_turn_one_has_no_facts_due_and_no_free_recall(tmp_path):
    _, rows = run_fake(tmp_path, "--scenarios", "growing", "--turns", "2",
                       "--attachment-sizes", "0", "--repeats", "1")
    first = rows[0]
    assert first["facts_due"] == "" and first["memory_recall"] == ""


def test_provider_and_fallback_are_recorded(tmp_path):
    _, rows = run_fake(tmp_path, "--scenarios", "growing", "--turns", "1",
                       "--attachment-sizes", "0", "--repeats", "1")
    assert rows[0]["provider"] == "fake" and rows[0]["fallback_used"] == "False"


def test_rows_are_saved_even_if_the_run_crashes(tmp_path, monkeypatch):
    import httpx
    import pytest
    from evals.stress import run as run_module

    original = run_module._turn
    calls = {"n": 0}

    async def boom(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 2:
            raise httpx.ReadTimeout("servidor colgado")
        if calls["n"] == 4:
            raise KeyError("observation")
        return await original(*args, **kwargs)

    monkeypatch.setattr(run_module, "_turn", boom)
    out = tmp_path / "results.csv"
    with pytest.raises(KeyError):
        main(["--in-process", "--fake-llm", "--output", str(out), "--pdf-dir", str(tmp_path / "p"),
              "--scenarios", "growing", "--attachment-sizes", "0", "--repeats", "1"])
    rows = list(csv.DictReader(out.open(encoding="utf-8")))
    assert [r["status"] for r in rows] == ["ok", "error", "ok"]  # el timeout es fila de error


def test_real_runs_flush_the_turn_one_cache_first(tmp_path, monkeypatch):
    import fakeredis
    import redis

    server = fakeredis.FakeServer()
    stale = fakeredis.FakeRedis(server=server, decode_responses=True)
    stale.set("session_turn1:exact:viejo", "{}")
    stale.set("otra:clave", "x")
    monkeypatch.setattr(redis.Redis, "from_url",
                        lambda *a, **k: fakeredis.FakeRedis(server=server, decode_responses=True))

    from evals.stress.run import _flush_turn1
    assert _flush_turn1("redis://falso") == 1
    assert stale.get("session_turn1:exact:viejo") is None and stale.get("otra:clave") == "x"


def test_unreachable_redis_stops_before_spending(tmp_path, monkeypatch):
    import redis

    class Down:
        def scan_iter(self, *a, **k):
            raise redis.ConnectionError("Redis caído")

    monkeypatch.setattr(redis.Redis, "from_url", lambda *a, **k: Down())
    out = tmp_path / "r.csv"
    assert main(["--http", "http://127.0.0.1:9", "--output", str(out)]) == 3
    assert not out.exists()  # no se hizo ninguna petición ni se escribió nada


def test_keep_flag_skips_the_flush(monkeypatch):
    from evals.stress import run as run_module

    called = []
    monkeypatch.setattr(run_module, "_flush_turn1", lambda url: called.append(url) or 0)
    args = run_module._parse(["--http", "http://x", "--keep-turn1-cache"])
    assert args.keep_turn1_cache and not called


def test_warns_when_a_scenario_turn_one_is_served_from_cache(tmp_path, monkeypatch):
    from evals.stress import run as run_module

    original = run_module._turn

    async def cached_first(*args, **kwargs):
        data = await original(*args, **kwargs)
        if data["observation"]["turn_index"] == 1:
            data["observation"]["cache_hit_kind"] = "exact"
        return data

    monkeypatch.setattr(run_module, "_turn", cached_first)
    _, rows = run_fake(tmp_path, "--scenarios", "growing", "--turns", "2",
                       "--attachment-sizes", "0", "--repeats", "1")
    assert "caché" in rows[0]["error"] and rows[0]["status"] == "ok"
    assert rows[1]["error"] == ""


def test_default_brake_covers_the_measured_cost_of_a_full_run():
    """La ejecución real completa costó $1,11: el freno por defecto debe dejarla terminar."""
    from evals.stress.run import _parse

    assert _parse(["--http", "http://x"]).max_cost == 1.5
