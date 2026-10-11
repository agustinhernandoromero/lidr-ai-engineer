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
