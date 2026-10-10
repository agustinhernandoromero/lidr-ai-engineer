"""Runner del estrés del CAG (sesión 06) → CSV con una fila por turno.

    uv run python -m evals.stress.run --http http://localhost:8000 \\
        --scenarios growing,pivot,contradiction --turns 10 \\
        --attachment-sizes 0,5,20,50,100 --repeats 4 --output evals/stress/results.csv

``--in-process`` usa la app sin servidor (mismo camino de código);
``--fake-llm`` (solo en proceso) ensaya todo con el LLM falso, coste $0.
``--max-cost`` para la ejecución si el coste acumulado lo supera, guardando
las filas hechas. La observación de cada turno sale de la propia respuesta
(campo ``observation``) y el snapshot de memoria de ``GET /sessions/{id}``.
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import sys
import time
from pathlib import Path

import httpx

from evals.stress.fixtures.build_pdfs import DEFAULT_DIR, MARKERS, build_all
from evals.stress.metrics import CostBudgetMetric, LatencyBudgetMetric, MemoryDriftMetric
from evals.stress.scenarios import SCENARIOS, facts_due

API = "/api/v1"
FORM = {"detail_level": "summary", "output_format": "narrative"}
ATTACHMENT_TRANSCRIPT = "Estima este proyecto de reservas a partir de la especificación adjunta."
LATENCY = LatencyBudgetMetric(budget_ms=20_000)
COST = CostBudgetMetric(budget_usd=0.02)
EST_COST_PER_TURN = 0.017  # medido en la sesión 05

OBS_COLUMNS = [
    "turn_index", "session_id", "enriched_transcript_chars", "attachments_total_chars",
    "messages_in_window", "anchors_count", "summary_chars", "tokens_in", "tokens_out",
    "cost_usd", "latency_ms", "cache_hit_kind", "last_resolved_tier",
    "tier_rule", "llm_calls", "structured_attempts",
]
COLUMNS = [
    "block", "scenario", "attachment_kb", "repeat", "status", "error", *OBS_COLUMNS,
    "latency_ok", "cost_ok", "memory_recall", "memory_recall_with_window",
    "project_name_recalled", "facts_due", "facts_missing", "attachment_recall",
    "technologies", "anchors", "total_hours_min", "total_hours_max",
]


def _recall(snapshot: dict, facts: list[str], where: list[str] | None = None) -> tuple[float, list[str]]:
    if not facts:
        return 1.0, []
    missing = [f for f in facts if not MemoryDriftMetric(f, where).evaluate(snapshot).passed]
    return round(1 - len(missing) / len(facts), 3), missing


async def _turn(client, sid: str, transcript: str, project_type: str, files=None) -> dict:
    response = await client.post(
        f"{API}/sessions/{sid}/estimate",
        data={"transcript": transcript, "project_type": project_type, **FORM},
        files=files,
    )
    if response.status_code != 200:
        raise RuntimeError(f"HTTP {response.status_code}: {response.text[:200]}")
    return response.json()


def _row(base: dict, data: dict | None, snapshot: dict, error: str = "") -> dict:
    row = {c: "" for c in COLUMNS}
    row.update(base)
    row["status"] = "error" if error else "ok"
    row["error"] = error
    if data:
        obs = data["observation"]
        row.update({c: obs.get(c, "") for c in OBS_COLUMNS})
        row["latency_ok"] = int(LATENCY.evaluate(obs).passed)
        row["cost_ok"] = int(COST.evaluate(obs).passed)
        row["total_hours_min"] = data["result"]["total_hours_min"]
        row["total_hours_max"] = data["result"]["total_hours_max"]
    metadata = snapshot.get("project_metadata") or {}
    row["technologies"] = ", ".join(metadata.get("mentioned_technologies") or [])
    row["anchors"] = " | ".join(
        f"[{a['rule']}] {a['user'][:80]}" for a in snapshot.get("anchors") or []
    )
    return row


async def _multiturn(client, name: str, turns: int, rows: list, spent: list, max_cost: float) -> bool:
    scenario = SCENARIOS[name]
    sid = (await client.post(f"{API}/sessions")).json()["session_id"]
    for turn in scenario.turns[:turns]:
        base = {"block": "multiturn", "scenario": name, "attachment_kb": 0, "repeat": 1}
        try:
            data, error = await _turn(client, sid, turn.transcript, scenario.project_type), ""
        except RuntimeError as exc:
            data, error = None, str(exc)
        snapshot = (await client.get(f"{API}/sessions/{sid}")).json()
        row = _row(base, data, snapshot, error)
        if not data:
            row["turn_index"] = turn.index
        # Enunciado: hecho del turno k evaluado en el turno N > k (estrictamente anteriores).
        due = facts_due(scenario, turn.index) if data else []
        recall, missing = _recall(snapshot, due)
        recall_window, _ = _recall(snapshot, due, ["summary", "anchors", "metadata", "window"])
        row.update({
            "memory_recall": recall,
            "memory_recall_with_window": recall_window,
            "project_name_recalled": int(
                MemoryDriftMetric(scenario.project_name).evaluate(snapshot).passed
            ),
            "facts_due": "; ".join(due),
            "facts_missing": "; ".join(missing),
        })
        rows.append(row)
        spent[0] += float(row["cost_usd"] or 0)
        print(f"  {name} turno {turn.index}: {row['status']} · ${float(row['cost_usd'] or 0):.4f} "
              f"· {row['latency_ms']} ms · recuerdo {recall}", flush=True)
        if spent[0] > max_cost:
            return True
    return False


async def _attachments(client, sizes_kb, repeats, pdfs, rows, spent, max_cost) -> bool:
    for kb in sizes_kb:
        for rep in range(1, repeats + 1):
            sid = (await client.post(f"{API}/sessions")).json()["session_id"]
            files = None
            if kb:
                files = [("attachments", (pdfs[kb].name, pdfs[kb].read_bytes(), "application/pdf"))]
            base = {"block": "attachment", "scenario": "attachment", "attachment_kb": kb, "repeat": rep}
            try:
                data, error = await _turn(client, sid, ATTACHMENT_TRANSCRIPT, "web_saas", files), ""
            except RuntimeError as exc:
                data, error = None, str(exc)
            snapshot = (await client.get(f"{API}/sessions/{sid}")).json()
            row = _row(base, data, snapshot, error)
            if data and kb:
                haystack = (data["text"] + " " + row["technologies"]).lower()
                found = [m for m in MARKERS if m.lower() in haystack]
                row["attachment_recall"] = round(len(found) / len(MARKERS), 3)
            rows.append(row)
            spent[0] += float(row["cost_usd"] or 0)
            print(f"  adjunto {kb} KB rep {rep}: {row['status']} · {row['cache_hit_kind']} "
                  f"· ${float(row['cost_usd'] or 0):.4f}", flush=True)
            if spent[0] > max_cost:
                return True
    return False


async def run(client, *, scenarios, turns, sizes_kb, repeats, max_cost, pdf_dir) -> tuple[list[dict], bool]:
    pdfs = build_all(pdf_dir, [kb for kb in sizes_kb if kb])
    rows: list[dict] = []
    spent = [0.0]
    for name in scenarios:
        if await _multiturn(client, name, turns, rows, spent, max_cost):
            return rows, True
    stopped = await _attachments(client, sizes_kb, repeats, pdfs, rows, spent, max_cost)
    return rows, stopped


def write_csv(rows: list[dict], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=COLUMNS)
        writer.writeheader()
        writer.writerows(rows)


def _parse(argv) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Estrés del CAG conversacional (sesión 06)")
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument("--http", help="URL del servicio, p. ej. http://localhost:8000")
    target.add_argument("--in-process", action="store_true", help="usar la app sin servidor")
    parser.add_argument("--fake-llm", action="store_true", help="LLM falso (solo en proceso), coste $0")
    parser.add_argument("--scenarios", default="growing,pivot,contradiction")
    parser.add_argument("--turns", type=int, default=10)
    parser.add_argument("--attachment-sizes", default="0,5,20,50,100")
    parser.add_argument("--repeats", type=int, default=4)
    parser.add_argument("--max-cost", type=float, default=1.0)
    parser.add_argument("--output", default="evals/stress/results.csv")
    parser.add_argument("--pdf-dir", default=str(DEFAULT_DIR))
    args = parser.parse_args(argv)
    if args.fake_llm and not args.in_process:
        parser.error("--fake-llm solo funciona con --in-process")
    return args


def _client(args):
    if args.http:
        return httpx.AsyncClient(base_url=args.http, timeout=300), None
    from app.dependencies import get_llm_wrapper, get_session_cache, get_session_store
    from app.main import app
    from app.services.sessions import SessionStore

    store = SessionStore(max_turns=6)
    app.dependency_overrides[get_session_store] = lambda: store
    if args.fake_llm:
        import fakeredis

        from app.services.session_cache import SessionTurnCache
        from tests.helpers import FakeLLM

        llm = FakeLLM()
        cache = SessionTurnCache(fakeredis.FakeRedis(decode_responses=True), embedder=None,
                                 threshold=0.92, log_only=False, ttl=600)
        app.dependency_overrides[get_llm_wrapper] = lambda: llm
        app.dependency_overrides[get_session_cache] = lambda: cache
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test", timeout=300)
    return client, app


def main(argv=None) -> int:
    args = _parse(argv)
    scenarios = [s.strip() for s in args.scenarios.split(",") if s.strip()]
    sizes = [int(s) for s in args.attachment_sizes.split(",") if s.strip()]
    n_turns = len(scenarios) * args.turns + len(sizes) * args.repeats
    llm_turns = len(scenarios) * args.turns + len(sizes)  # las repeticiones aciertan en caché
    if not args.fake_llm:
        print(f"Estimación: {n_turns} turnos, ~{llm_turns} con LLM, "
              f"~${llm_turns * EST_COST_PER_TURN:.2f}, ~{llm_turns * 15 // 60} min. "
              f"Freno: ${args.max_cost:.2f}.", flush=True)

    async def _go():
        client, app = _client(args)
        try:
            async with client:
                return await run(client, scenarios=scenarios, turns=args.turns, sizes_kb=sizes,
                                 repeats=args.repeats, max_cost=args.max_cost,
                                 pdf_dir=Path(args.pdf_dir))
        finally:
            if app is not None:
                app.dependency_overrides.clear()

    started = time.perf_counter()
    rows, stopped = asyncio.run(_go())
    write_csv(rows, Path(args.output))
    total = sum(float(r["cost_usd"] or 0) for r in rows)
    print(f"{len(rows)} filas → {args.output} · coste ${total:.4f} · "
          f"{time.perf_counter() - started:.0f} s", flush=True)
    if stopped:
        print(f"FRENO DE COSTE: se superó ${args.max_cost:.2f}; filas guardadas.", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
