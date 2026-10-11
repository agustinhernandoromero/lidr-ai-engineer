"""results.json del golden → evals/REPORT.md.

Las tablas se calculan del JSON; la lectura se escribe a mano en
``evals/reading.md`` y se incrusta, así el informe se regenera sin perderla.

    uv run python -m evals.report
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from evals.metrics import GOLDEN_METRIC_NAMES

MODES = ("actor", "acb")
DASH = "—"
LABELS = {"schema_adherence": "Esquema", "hours_bounds": "Horas",
          "content_recall": "Contenido", "tier": "Tier"}


def _by_mode(runs: list[dict]) -> dict[str, list[dict]]:
    return {m: [r for r in runs if r["mode"] == m] for m in MODES}


def _passed(run: dict, metric: str) -> bool:
    return next(m["passed"] for m in run["metrics"] if m["name"] == metric)


def _summary(by_mode) -> list[str]:
    head = " | ".join(LABELS[m] for m in GOLDEN_METRIC_NAMES)
    lines = [f"| Modo | Casos | {head} | Métricas OK | Coste total ($) | Coste medio por caso ($) "
             "| Latencia media (ms) |",
             "|---" * (len(GOLDEN_METRIC_NAMES) + 6) + "|"]
    for mode, runs in by_mode.items():
        if not runs:
            continue
        n = len(runs)
        counts = [sum(_passed(r, m) for r in runs) for m in GOLDEN_METRIC_NAMES]
        total = sum(counts)
        cost = sum(r["cost_usd"] for r in runs)
        lat = [r["latency_ms"] for r in runs if r["status"] == "ok" and r["latency_ms"] is not None]
        mean_lat = f"{sum(lat) / len(lat):.0f}" if lat else DASH
        lines.append(f"| {mode} | {n} | " + " | ".join(f"{c}/{n}" for c in counts)
                     + f" | {total}/{n * 4} ({total / (n * 4):.0%}) | {cost:.4f} | {cost / n:.4f} "
                     f"| {mean_lat} |")
    return lines


def _cell(run: dict | None) -> str:
    if run is None:
        return DASH
    score = f"{run['score']:.2f}"
    if run["status"] in ("bloqueado", "error"):
        return f"{score} ({run['status']})"
    return score


def _failed(run: dict | None) -> str:
    if run is None:
        return DASH
    return ", ".join(m["name"] for m in run["metrics"] if not m["passed"]) or DASH


def _per_case(by_mode) -> list[str]:
    lines = ["| Caso | Actor | ACB | Decisión del jefe | Falló en actor | Falló en ACB |",
             "|---|---|---|---|---|---|"]
    ids = list(dict.fromkeys(r["case_id"] for runs in by_mode.values() for r in runs))
    index = {(r["mode"], r["case_id"]): r for runs in by_mode.values() for r in runs}
    for case_id in ids:
        actor, acb = index.get(("actor", case_id)), index.get(("acb", case_id))
        decision = (acb or {}).get("acb_final_decision") or DASH
        lines.append(f"| {case_id} | {_cell(actor)} | {_cell(acb)} | {decision} "
                     f"| {_failed(actor)} | {_failed(acb)} |")
    return lines


def _diff(by_mode) -> list[str]:
    missing = [m for m in MODES if not by_mode[m]]
    if missing:
        return [f"Falta el modo {', '.join(missing)}: ejecuta `--mode ambos` para comparar."]
    actor = {r["case_id"]: r["score"] for r in by_mode["actor"]}
    acb = {r["case_id"]: r["score"] for r in by_mode["acb"]}
    common = [c for c in actor if c in acb]
    fixed = [c for c in common if acb[c] > actor[c]]
    broken = [c for c in common if acb[c] < actor[c]]

    def fmt(ids: list[str]) -> str:
        return ", ".join(f"{c} ({actor[c]:.2f} → {acb[c]:.2f})" for c in ids) or "ninguno"

    return [f"**Arregló ({len(fixed)}):** {fmt(fixed)}", "",
            f"**Rompió ({len(broken)}):** {fmt(broken)}", "",
            f"**Igual ({len(common) - len(fixed) - len(broken)})**"]


def _decisions(by_mode) -> list[str]:
    decisions = [r.get("acb_final_decision") for r in by_mode["acb"] if r["status"] == "ok"]
    if not decisions:
        return ["Sin ejecuciones del ACB."]
    return [f"- {d}: {decisions.count(d)}" for d in ("aceptar", "rehacer", "sintetizar")]


METHOD = """## Método

- **Casos:** 16 en `evals/golden_dataset.json` (14 dentro de alcance, 2 fuera; 7 con tier
  distinto de `default`). Cada caso va en una sesión nueva, de un solo turno.
- **Métricas** (`evals/metrics.py`, deterministas, sin LLM-as-judge):
  `schema_adherence` (reglas de negocio), `hours_bounds` (fases, horas y semanas dentro de
  rangos anchos; el intervalo estimado debe caber en el esperado), `content_recall` (lo
  pedido aparece en resumen, fases o supuestos) y `tier` (audiencia detectada).
- **Fuera de alcance:** acierta si el resumen empieza por "Fuera de alcance:" o si un
  guardrail lo bloqueó (400). Un bloqueo de un caso normal cuenta como fallo.
- **caso-10 falla a propósito:** `small_team_pm` lee el tamaño de equipo de la memoria,
  vacía en el turno 1, así que un caso de un solo turno nunca da `pm`.
- **Caché:** la del turno 1 se vacía antes de la ejecución; el ACB no la usa.
"""


def build_report(data: dict, reading: str | None) -> str:
    by_mode = _by_mode(data["runs"])
    parts = [
        "# Golden dataset — actor frente a Actor-Critic-Boss",
        "",
        f"Datos: `evals/results.json` (modelo `{data['model']}`, {data['generated_at']}). "
        "Generado por `evals/report.py`.",
        "",
        "## Resumen por modo", "", *_summary(by_mode), "",
        "## Caso a caso", "", *_per_case(by_mode), "",
        "## Qué cambió el ACB", "", *_diff(by_mode), "",
        "## Decisiones del jefe", "", *_decisions(by_mode), "",
        "## Lectura", "",
        reading.strip() if reading else "(pendiente: lectura tras la ejecución real)", "",
        METHOD,
    ]
    return "\n".join(parts)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Genera evals/REPORT.md a partir de results.json")
    parser.add_argument("--input", default="evals/results.json")
    parser.add_argument("--output", default="evals/REPORT.md")
    parser.add_argument("--reading", default="evals/reading.md")
    args = parser.parse_args(argv)
    data = json.loads(Path(args.input).read_text(encoding="utf-8"))
    reading_path = Path(args.reading)
    reading = reading_path.read_text(encoding="utf-8") if reading_path.exists() else None
    Path(args.output).write_text(build_report(data, reading), encoding="utf-8")
    print(f"{args.output} <- {len(data['runs'])} ejecuciones")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
