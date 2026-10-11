"""Runner del golden: ensayo completo con LLM falso ($0) y casos límite."""

import json

from evals.run import main


def run_fake(tmp_path, *extra):
    out = tmp_path / "results.json"
    code = main(["--in-process", "--fake-llm", "--output", str(out), *extra])
    return code, json.loads(out.read_text(encoding="utf-8"))


def test_both_modes_run_every_case(tmp_path):
    code, data = run_fake(tmp_path, "--mode", "ambos")
    assert code == 0 and data["dataset_size"] == 16
    assert [r["mode"] for r in data["runs"]].count("actor") == 16
    assert [r["mode"] for r in data["runs"]].count("acb") == 16
    injection = [r for r in data["runs"] if r["case_id"] == "caso-06-fuera-inyeccion"]
    assert [r["status"] for r in injection] == ["bloqueado", "bloqueado"]
    assert all(r["guardrail_reason"] == "prompt_injection" for r in injection)
    first = data["runs"][0]
    assert [m["name"] for m in first["metrics"]] == [
        "schema_adherence", "hours_bounds", "content_recall", "tier"]
    assert 0.0 <= first["score"] <= 1.0


def test_acb_runs_record_the_boss_decision(tmp_path):
    _, data = run_fake(tmp_path, "--mode", "acb", "--limit", "2")
    assert all(r["acb_final_decision"] == "aceptar" and r["acb_iterations"] == 1
               for r in data["runs"] if r["status"] == "ok")


def test_server_error_is_recorded_and_the_run_continues(tmp_path, monkeypatch):
    from tests import helpers

    original = helpers.FakeLLM.complete
    state = {"n": 0}

    def flaky(self, messages, max_tokens=4000, json_schema=None):
        if self._kind(messages) == "estimator":
            state["n"] += 1
            if state["n"] <= 3:  # caso 1: los 3 intentos estructurados fallan → 502
                return {"text": "no json", "model": "f", "provider": "fake", "fallback_used": False}
        return original(self, messages, max_tokens, json_schema)

    monkeypatch.setattr(helpers.FakeLLM, "complete", flaky)
    code, data = run_fake(tmp_path, "--mode", "actor", "--limit", "3")
    assert code == 0
    assert [r["status"] for r in data["runs"]] == ["error", "ok", "ok"]
    assert "502" in data["runs"][0]["error"]
    assert data["runs"][0]["score"] == 0.0


def test_non_guardrail_400_is_an_error_not_a_block():
    import httpx

    from evals.run import _outcome

    record: dict = {}
    response = httpx.Response(400, json={"detail": "Versión de prompt desconocida"})
    outcome = _outcome(response, record)
    assert outcome.status == "error" and "400" in record["error"]


def test_cost_brake_stops_and_keeps_what_was_done(tmp_path):
    code, data = run_fake(tmp_path, "--mode", "ambos", "--max-cost", "-1")
    assert code == 2 and len(data["runs"]) == 1


def test_real_run_stops_before_spending_if_redis_is_down(tmp_path, monkeypatch):
    import redis

    class Down:
        def scan_iter(self, *a, **k):
            raise redis.ConnectionError("Redis caído")

    monkeypatch.setattr(redis.Redis, "from_url", lambda *a, **k: Down())
    out = tmp_path / "r.json"
    assert main(["--http", "http://127.0.0.1:9", "--output", str(out)]) == 3
    assert not out.exists()


def test_failed_session_creation_is_an_error_and_the_run_continues():
    """Un 502 en HTML al crear la sesión (proxy, Docker) no puede tumbar la ejecución."""
    import asyncio

    import httpx

    from evals.dataset import load_dataset
    from evals.run import run

    calls = {"sessions": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v1/sessions":
            calls["sessions"] += 1
            if calls["sessions"] == 1:
                return httpx.Response(502, text="<html>Bad Gateway</html>")
            return httpx.Response(201, json={"session_id": "s"})
        return httpx.Response(400, json={"detail": {"reason": "pii", "message": "x"}})

    async def go():
        records: list[dict] = []
        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            await run(client, load_dataset()[:2], ["actor"], 1.0, records)
        return records

    records = asyncio.run(go())
    assert [r["status"] for r in records] == ["error", "bloqueado"]
    assert "502" in records[0]["error"]


def _answer(**overrides):
    from tests.helpers import fake_result_json

    payload = {
        "result": json.loads(fake_result_json("CRM comercial con React.")),
        "tier": "default", "model": "claude-haiku-4-5", "provider": "anthropic",
        "fallback_used": False, "cache_hit_kind": "none",
        "observation": {"cost_usd": 0.01, "llm_calls": 3}, "acb": None,
    }
    payload.update(overrides)
    return payload


def _single_case(payload):
    import asyncio

    import httpx

    from evals.dataset import load_dataset
    from evals.run import run_case

    def handler(request):
        if request.url.path == "/api/v1/sessions":
            return httpx.Response(201, json={"session_id": "s"})
        return httpx.Response(200, json=payload)

    async def go():
        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            return await run_case(client, load_dataset()[0], "actor")

    return asyncio.run(go())


def test_record_keeps_the_answer_and_how_it_was_produced():
    """Para explicar un fallo sin pagar otra ejecución."""
    record = _single_case(_answer())
    assert record["status"] == "ok"
    assert record["summary"] == "CRM comercial con React."
    assert record["phases"][0]["name"] == "Desarrollo"
    assert record["assumptions"] == []
    assert (record["model"], record["provider"]) == ("claude-haiku-4-5", "anthropic")
    assert record["fallback_used"] is False and record["cache_hit_kind"] == "none"


def test_cache_hit_invalidates_the_case():
    """Un acierto de caché sirve la estimación de otro proyecto: no compara nada."""
    record = _single_case(_answer(cache_hit_kind="semantic"))
    assert record["status"] == "error"
    assert "caché" in record["error"]
    assert record["score"] < 1.0
