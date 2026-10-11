"""Runner del golden dataset: actor frente a Actor-Critic-Boss → results.json.

    uv run python -m evals.run --http http://localhost:8000 --mode ambos
    uv run python -m evals.run --in-process --fake-llm --mode ambos   # ensayo, $0
    uv run python -m evals.report                                      # → evals/REPORT.md

Cada caso va en una sesión nueva. Un 400 de guardrail es "bloqueado" (acierto
si el caso esperaba quedar fuera de alcance); cualquier otro fallo es "error"
y se sigue con el siguiente. En ejecuciones reales se vacía antes la caché del
turno 1, como en el runner de estrés: si no, el modo actor serviría respuestas
de una ejecución anterior.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx

from app.schemas import EstimationResult
from evals.dataset import DEFAULT_PATH, GoldenCase, load_dataset
from evals.metrics import Outcome, run_golden_metrics
from evals.stress.run import _client, _flush_turn1

API = "/api/v1"
ENDPOINTS = {"actor": "estimate", "acb": "estimate-acb"}
EST_COST_PER_CASE = {"actor": 0.011, "acb": 0.02}  # medidos en la prueba real del ACB


def _outcome(response: httpx.Response, record: dict) -> Outcome:
    if response.status_code == 400:
        try:
            detail = response.json().get("detail")
        except ValueError:
            detail = None
        if isinstance(detail, dict) and detail.get("reason"):
            record.update(status="bloqueado", guardrail_reason=detail["reason"])
            return Outcome("bloqueado", guardrail_reason=detail["reason"])
    if response.status_code != 200:
        record["error"] = f"HTTP {response.status_code}: {response.text[:200]}"
        return Outcome("error")
    data = response.json()
    result = EstimationResult.model_validate(data["result"])
    obs = data.get("observation") or {}
    acb = data.get("acb") or {}
    record.update(
        status="ok",
        cost_usd=float(obs.get("cost_usd") or 0),
        llm_calls=int(obs.get("llm_calls") or 0),
        tier=data.get("tier"),
        total_hours_min=result.total_hours_min,
        total_hours_max=result.total_hours_max,
        total_duration_weeks=result.total_duration_weeks,
        acb_final_decision=acb.get("final_decision"),
        acb_iterations=acb.get("iterations_run"),
    )
    return Outcome("ok", result=result, tier=data.get("tier"))


async def run_case(client, case: GoldenCase, mode: str) -> dict:
    record: dict = {
        "case_id": case.id, "mode": mode, "status": "error", "guardrail_reason": None,
        "error": None, "cost_usd": 0.0, "latency_ms": None, "llm_calls": 0, "tier": None,
        "total_hours_min": None, "total_hours_max": None, "total_duration_weeks": None,
        "acb_final_decision": None, "acb_iterations": None,
    }
    form = {"transcript": case.transcript, "project_type": case.project_type,
            "detail_level": case.detail_level, "output_format": case.output_format}
    started = time.perf_counter()
    try:
        sid = (await client.post(f"{API}/sessions")).json()["session_id"]
        response = await client.post(f"{API}/sessions/{sid}/{ENDPOINTS[mode]}", data=form)
    except httpx.HTTPError as exc:
        record["error"] = f"{type(exc).__name__}: {exc}"[:300]
        outcome = Outcome("error")
    else:
        record["latency_ms"] = round((time.perf_counter() - started) * 1000, 1)
        outcome = _outcome(response, record)
    metrics = run_golden_metrics(case, outcome)
    record["metrics"] = [{"name": m.name, "passed": m.passed, "details": m.details} for m in metrics]
    record["score"] = round(sum(m.passed for m in metrics) / len(metrics), 3)
    return record


async def run(client, cases: list[GoldenCase], modes: list[str], max_cost: float,
              records: list[dict]) -> bool:
    """Añade un registro por caso y modo; ``True`` si paró por el freno de coste."""
    spent = 0.0
    for mode in modes:
        for case in cases:
            record = await run_case(client, case, mode)
            records.append(record)
            spent += record["cost_usd"]
            failed = [m["name"] for m in record["metrics"] if not m["passed"]]
            print(f"  {mode:<5} {case.id:<30} {record['status']:<9} "
                  f"{record['score']:.2f} ${record['cost_usd']:.4f} "
                  f"{'falla: ' + ', '.join(failed) if failed else ''}", flush=True)
            if spent > max_cost:
                return True
    return False


def write_results(records: list[dict], path: Path, *, model: str, dataset_size: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "model": model,
        "dataset_size": dataset_size,
        "runs": records,
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")


def _parse(argv) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Golden dataset: actor frente a Actor-Critic-Boss")
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument("--http", help="URL del servicio, p. ej. http://localhost:8000")
    target.add_argument("--in-process", action="store_true", help="usar la app sin servidor")
    parser.add_argument("--fake-llm", action="store_true", help="LLM falso (solo en proceso), coste $0")
    parser.add_argument("--mode", choices=("actor", "acb", "ambos"), default="ambos")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--max-cost", type=float, default=1.0, help="freno de coste acumulado (USD)")
    parser.add_argument("--output", default="evals/results.json")
    parser.add_argument("--dataset", default=str(DEFAULT_PATH))
    parser.add_argument("--keep-turn1-cache", action="store_true",
                        help="no vaciar la caché del turno 1 antes de una ejecución real")
    parser.add_argument("--redis-url", default=None,
                        help="Redis del servidor (por defecto REDIS_URL de la configuración)")
    args = parser.parse_args(argv)
    if args.fake_llm and not args.in_process:
        parser.error("--fake-llm solo funciona con --in-process")
    return args


def main(argv=None) -> int:
    args = _parse(argv)
    from app.config import get_settings

    settings = get_settings()
    cases = load_dataset(args.dataset)[: args.limit]
    modes = ["actor", "acb"] if args.mode == "ambos" else [args.mode]
    if not args.fake_llm and not args.keep_turn1_cache:
        redis_url = args.redis_url or settings.REDIS_URL
        try:
            flushed = _flush_turn1(redis_url)
        except Exception as exc:  # noqa: BLE001
            print(f"No se pudo vaciar la caché del turno 1 en {redis_url} ({exc}). "
                  "Arranca Redis o usa --keep-turn1-cache. No se ha gastado nada.",
                  file=sys.stderr, flush=True)
            return 3
        print(f"Caché del turno 1 vaciada: {flushed} claves.", flush=True)
        estimate = sum(EST_COST_PER_CASE[m] for m in modes) * len(cases)
        print(f"Estimación: {len(cases) * len(modes)} ejecuciones, ~${estimate:.2f}. "
              f"Freno: ${args.max_cost:.2f}.", flush=True)

    records: list[dict] = []

    async def _go() -> bool:
        client, app = _client(args)
        try:
            async with client:
                return await run(client, cases, modes, args.max_cost, records)
        finally:
            if app is not None:
                app.dependency_overrides.clear()

    try:
        stopped = asyncio.run(_go())
    finally:
        # Lo ya pagado no se pierde: el JSON se escribe aunque algo reviente.
        write_results(records, Path(args.output), dataset_size=len(cases),
                      model="fake" if args.fake_llm else settings.ANTHROPIC_MODEL)
    for mode in modes:
        done = [r for r in records if r["mode"] == mode]
        if done:
            passed = sum(m["passed"] for r in done for m in r["metrics"])
            cost = sum(r["cost_usd"] for r in done)
            print(f"{mode}: {passed}/{len(done) * 4} métricas OK · ${cost:.4f}", flush=True)
    if stopped:
        print(f"FRENO DE COSTE: se superó ${args.max_cost:.2f}; resultados guardados.", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
