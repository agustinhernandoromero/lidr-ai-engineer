"""Informe del golden: secciones, comparación actor/ACB y un solo modo ($0)."""

from evals.report import build_report

NAMES = ["schema_adherence", "hours_bounds", "content_recall", "tier"]


def run(case_id, mode, passed, status="ok", decision=None, cost=0.01):
    metrics = [{"name": n, "passed": bool(p), "details": "x"} for n, p in zip(NAMES, passed)]
    return {"case_id": case_id, "mode": mode, "status": status, "score": sum(passed) / 4,
            "metrics": metrics, "cost_usd": cost, "latency_ms": 1000.0,
            "acb_final_decision": decision, "acb_iterations": 1 if decision else None}


DATA = {"generated_at": "2026-10-11T00:00:00+00:00", "model": "claude-haiku-4-5", "dataset_size": 2,
        "runs": [run("caso-a", "actor", [1, 0, 1, 1]), run("caso-b", "actor", [1, 1, 1, 1]),
                 run("caso-a", "acb", [1, 1, 1, 1], decision="rehacer"),
                 run("caso-b", "acb", [1, 1, 0, 1], decision="aceptar")]}


def test_report_has_all_sections_and_reading():
    text = build_report(DATA, "Mi lectura de prueba.")
    for heading in ("## Resumen por modo", "## Caso a caso", "## Qué cambió el ACB",
                    "## Decisiones del jefe", "## Lectura", "## Método"):
        assert heading in text
    assert "Mi lectura de prueba." in text
    assert "| actor | 2 | 2/2 | 1/2 | 2/2 | 2/2 | 7/8 (88%) |" in text


def test_report_lists_fixed_and_broken_cases():
    text = build_report(DATA, None)
    assert "**Arregló (1):** caso-a (0.75 → 1.00)" in text
    assert "**Rompió (1):** caso-b (1.00 → 0.75)" in text
    assert "rehacer: 1" in text and "aceptar: 1" in text


def test_report_with_a_single_mode_says_what_is_missing():
    only_actor = {**DATA, "runs": [r for r in DATA["runs"] if r["mode"] == "actor"]}
    text = build_report(only_actor, None)
    assert "Falta el modo acb" in text
