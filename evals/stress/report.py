"""CSV del estrés → evals/stress/REPORT.md.

Las tablas y curvas se calculan del CSV; los dos párrafos de lectura se
escriben a mano en ``evals/stress/reading.md`` y se incrustan, de modo que el
REPORT se puede regenerar sin perder el texto.

    uv run python -m evals.stress.report
"""

from __future__ import annotations

import argparse
import csv
import math
from pathlib import Path

DASH = "—"
SCENARIOS = ["growing", "pivot", "contradiction"]
CHECKPOINTS = [1, 3, 6, 10]
# tokens_in suma todas las llamadas del turno (estimador + extractor + resumidor).
TOKEN_BUCKETS = [(0, 5_000), (5_000, 10_000), (10_000, 15_000), (15_000, 20_000), (20_000, 10**9)]


def _f(value) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def percentile(values: list[float], p: float) -> float | None:
    """Percentil por rango más cercano (sin interpolar)."""
    if not values:
        return None
    ordered = sorted(values)
    return ordered[max(0, math.ceil(p * len(ordered)) - 1)]


def _fmt(value, spec: str = ".0f") -> str:
    return DASH if value is None else format(value, spec)


def _mean(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def _turn_of(row: dict):
    """Turno del guion (alineado aunque falle un turno); CSV antiguos usan turn_index."""
    return row.get("scenario_turn") or row["turn_index"]


def _ok(rows):
    return [r for r in rows if r.get("status") == "ok"]


def _summary(rows) -> list[str]:
    lines = [
        "| Bloque | Escenario | Adjunto (KB) | Filas | Latencia P50 sin caché (ms) "
        "| Latencia P95 sin caché (ms) "
        "| Coste total ($) | Caché exacta | Caché semántica | Recuerdo medio |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    groups: dict[tuple, list] = {}
    for r in rows:
        groups.setdefault((r["block"], r["scenario"], r["attachment_kb"]), []).append(r)
    for (block, scenario, kb), group in groups.items():
        ok = _ok(group)
        # Latencia solo de turnos sin caché: un acierto (~1 ms) no es la latencia del sistema.
        misses = [r for r in ok if r.get("cache_hit_kind") == "none"]
        lat = [v for v in (_f(r["latency_ms"]) for r in misses) if v is not None]
        cost = sum(_f(r["cost_usd"]) or 0 for r in ok)
        kinds = [r.get("cache_hit_kind") for r in ok]
        recall_key = "memory_recall" if block == "multiturn" else "attachment_recall"
        recall = _mean([v for v in (_f(r.get(recall_key)) for r in ok) if v is not None])

        def rate(kind: str) -> str:
            return f"{kinds.count(kind) / len(kinds):.0%}" if kinds else DASH

        lines.append(
            f"| {block} | {scenario} | {kb} | {len(group)} | {_fmt(percentile(lat, .5))} "
            f"| {_fmt(percentile(lat, .95))} | {cost:.4f} | {rate('exact')} "
            f"| {rate('semantic')} | {_fmt(recall, '.2f')} |"
        )
    return lines


def _curve_latency(rows) -> list[str]:
    lines = ["| tokens_in | Turnos | Latencia media (ms) | Latencia P95 (ms) |", "|---|---|---|---|"]
    llm_rows = [r for r in _ok(rows) if r.get("cache_hit_kind") == "none"]
    for low, high in TOKEN_BUCKETS:
        bucket = [r for r in llm_rows if low <= (_f(r["tokens_in"]) or 0) < high]
        lat = [v for v in (_f(r["latency_ms"]) for r in bucket) if v is not None]
        if high < 10**9:
            label = f"{low:,}–{high:,}".replace(",", ".")
        else:
            label = f"≥ {low:,}".replace(",", ".")
        lines.append(f"| {label} | {len(bucket)} | {_fmt(_mean(lat))} | {_fmt(percentile(lat, .95))} |")
    return lines


def _curve_cost(rows) -> list[str]:
    lines = ["| Turno | " + " | ".join(SCENARIOS) + " |", "|---" * (len(SCENARIOS) + 1) + "|"]
    cumulative = {s: 0.0 for s in SCENARIOS}
    by_turn: dict[int, dict[str, float]] = {}
    for r in _ok(rows):
        if r["block"] == "multiturn":
            by_turn.setdefault(int(_turn_of(r)), {})[r["scenario"]] = _f(r["cost_usd"]) or 0
    for turn in sorted(by_turn):
        cells = []
        for s in SCENARIOS:
            if s in by_turn[turn]:
                cumulative[s] += by_turn[turn][s]
                cells.append(f"{cumulative[s]:.4f}")
            else:
                cells.append(DASH)
        lines.append(f"| {turn} | " + " | ".join(cells) + " |")
    return lines


def _curve_recall(rows) -> list[str]:
    lines = [
        "| N | " + " | ".join(f"{s} (memoria / +ventana)" for s in SCENARIOS)
        + " | Nombre del proyecto recordado |",
        "|---" * (len(SCENARIOS) + 2) + "|",
    ]
    multiturn = [r for r in _ok(rows) if r["block"] == "multiturn"]
    for n in CHECKPOINTS:
        at_n = [r for r in multiturn if str(_turn_of(r)) == str(n)]
        cells = []
        for s in SCENARIOS:
            row = next((r for r in at_n if r["scenario"] == s), None)
            if row is None:
                cells.append(DASH)
            else:
                cells.append(f"{_fmt(_f(row['memory_recall']), '.2f')} / "
                             f"{_fmt(_f(row['memory_recall_with_window']), '.2f')}")
        names = [r for r in at_n if _f(r.get("project_name_recalled")) is not None]
        recalled = sum(int(_f(r["project_name_recalled"]) or 0) for r in names)
        lines.append(f"| {n} | " + " | ".join(cells) + f" | {recalled}/{len(names) or DASH} |")
    return lines


def _attachments(rows) -> list[str]:
    lines = [
        "| Adjunto (KB) | Rep | Caché | Chars adjunto | tokens_in | Latencia (ms) | Coste ($) "
        "| Recuerdo adjunto |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for r in rows:
        if r["block"] != "attachment":
            continue
        lines.append(
            f"| {r['attachment_kb']} | {r['repeat']} | {r.get('cache_hit_kind') or DASH} "
            f"| {r.get('attachments_total_chars') or DASH} | {r.get('tokens_in') or DASH} "
            f"| {r.get('latency_ms') or DASH} | {r.get('cost_usd') or DASH} "
            f"| {r.get('attachment_recall') or DASH} |"
        )
    return lines


SCOPE = """## ⚠️ Alcance reducido por coste

Esta entrega **no ejecuta el enunciado completo, a propósito y por coste**. Cada turno
se paga con llamadas reales al LLM, y a partir del turno 6 cada uno cuesta de media
$0,05 porque reenvía entre 25.000 y 45.000 tokens. La ejecución reducida costó **$1,11**.
Estas son las diferencias con el enunciado y lo que habría costado cumplirlo
(estimaciones a partir de los costes medidos en esta misma ejecución):

| Qué pide el enunciado | Qué hace esta entrega | Por qué | Coste estimado de hacerlo completo |
|---|---|---|---|
| **20 turnos** por escenario | **10 turnos** | Coste. Con la ventana de 6 turnos, el resumen y las anclas ya se ponen a prueba desde el turno 7 | $2,5–3,4 (frente a $1,0 del multiturno con 10 turnos) |
| **3 repeticiones** de cada conversación | **1 repetición** | Coste. Sin repeticiones no hay varianza: las curvas son una sola conversación | $7,5–10 con 20 turnos |
| Adjunto **en todos los turnos** (escenarios × tamaños × repeticiones) | Adjunto **solo en el turno 1**, en un bloque aparte (5 tamaños × 4 repeticiones) | Coste. El cruce completo son unos 900 turnos con el adjunto sumado al historial | ≈ $45–70 |
| Presupuesto de latencia de **8 s** | **20 s** | Criterio, no coste: con Claude Haiku ningún turno sin caché bajó de 12 s, así que con 8 s fallarían todos y la métrica no distinguiría nada | — |
| Límite de adjunto de **60.000** caracteres | **20.000** (constante del proyecto desde la sesión 05) | Se mantiene sin tocar. La caída del recuerdo del adjunto con 50 y 100 KB depende de este límite: con 60.000, el PDF de 50 KB entraría entero y el problema se desplazaría a documentos más grandes y a un contexto tres veces más caro | — |

**Qué no se ve por este recorte:** el efecto de comprimir el resumen varias veces
seguidas (turnos 11–20), la varianza entre ejecuciones y cómo crece el coste cuando el
adjunto se reenvía en cada turno. Las conclusiones de la lectura no dependen de ello: la
latencia y el coste ya se disparan hacia el turno 5–6 y la memoria ya se degrada en
silencio antes del turno 10.
"""


METHOD = """## Método

- **Escala**: 3 conversaciones de 10 turnos, una por escenario, y 5 tamaños de adjunto
  × 4 repeticiones en el turno 1 (50 filas); ver "Alcance reducido por coste". Las
  curvas por N se leen en los turnos 1, 3, 6 y 10 de la misma conversación.
- **Constantes sin tocar**: ventana `MAX_TURNS=6`, `MAX_ATTACHMENT_CHARS=20.000`,
  umbral semántico 0,92. "KB" de adjunto = miles de caracteres de texto del PDF.
- **Observación**: un evento `turn_observed` por turno (13 campos + `llm_calls`,
  `structured_attempts`, `tier_rule`) que agrega todas las llamadas del turno; un único
  evento se convierte a CSV en una pasada, sin reconciliar marcas de tiempo.
- **Métricas** en `evals/stress/metrics.py` (aparte de `evals/metrics.py` porque evalúan
  la observación y el snapshot, no un `EstimationResult`): `LatencyBudgetMetric(20.000 ms)`,
  `CostBudgetMetric($0,02)`, `MemoryDriftMetric` (coincidencia exacta sin mayúsculas en
  resumen, anclas y metadata). `memory_recall_with_window` añade la ventana para separar
  "olvidado" de "aún en ventana".
- **Repeticiones de adjuntos**: las repeticiones 2–4 aciertan en la caché exacta; miden la
  caché, no la latencia del LLM. Por eso la latencia P50/P95 se calcula solo sobre turnos
  sin caché, y coste y recuerdo de esas repeticiones son copias de la primera.
- **Latencia**: `latency_ms` cubre el turno en el servicio (render, caché, LLM, extracción,
  compresión); no incluye la extracción del PDF en el router ni el tiempo de red. Para
  eso el runner escribe ahora `wall_clock_ms` (medido desde el cliente); la columna se
  añadió después de la ejecución real, así que el `results.csv` actual no la tiene.
- **Turno 1**: no tiene hechos anteriores que recordar; su recuerdo queda en blanco y no
  cuenta en las medias.
- **No medido**: ráfagas concurrentes (sin bloque en el enunciado) y conversaciones de
  más de 10 turnos.
"""


def build_report(rows: list[dict], reading: str | None) -> str:
    parts = [
        "# Estrés del CAG — sesión 06",
        "",
        "Datos: `evals/stress/results.csv`. Generado por `evals/stress/report.py`.",
        "",
        SCOPE,
        "## Resumen",
        "", *_summary(rows), "",
        "## Curva 1 — latencia frente a tokens de entrada (turnos sin caché)",
        "", *_curve_latency(rows), "",
        "## Curva 2 — coste acumulado (USD) frente a turno",
        "", *_curve_cost(rows), "",
        "## Curva 3 — recuerdo de hechos frente a N",
        "", *_curve_recall(rows), "",
        "## Adjuntos",
        "", *_attachments(rows), "",
        "## Lectura",
        "", reading.strip() if reading else "(pendiente: lectura tras la ejecución real)", "",
        METHOD,
    ]
    return "\n".join(parts)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Genera REPORT.md a partir del CSV de estrés")
    parser.add_argument("--input", default="evals/stress/results.csv")
    parser.add_argument("--output", default="evals/stress/REPORT.md")
    parser.add_argument("--reading", default="evals/stress/reading.md")
    args = parser.parse_args(argv)
    with Path(args.input).open(encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    reading_path = Path(args.reading)
    reading = reading_path.read_text(encoding="utf-8") if reading_path.exists() else None
    Path(args.output).write_text(build_report(rows, reading), encoding="utf-8")
    print(f"{args.output} <- {len(rows)} filas")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
