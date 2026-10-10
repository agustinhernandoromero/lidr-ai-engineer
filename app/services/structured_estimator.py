"""Estimación estructurada: JSON forzado por esquema + validación + reintento.

El modelo devuelve un ``EstimationResult`` en horas. Si una regla de negocio
falla (las fases no suman el total, confianza baja sin declararlo…), se le
reenvía su propio JSON con el error y se le pide corregirlo. Es lo mismo que
hace Instructor por dentro, pero visible y sin dependencias. El Markdown que
ve el usuario se genera aquí, en código, a partir del JSON validado.
"""

from __future__ import annotations

from app.schemas import EstimationResult, cost_range_eur


def _fmt(n: int) -> str:
    """Miles con punto, como se escriben en España: 13500 → '13.500'."""
    return f"{n:,}".replace(",", ".")


def render_markdown(result: EstimationResult, output_format: str, rate: int) -> str:
    cost_min, cost_max = cost_range_eur(result, rate)
    totals = (
        f"**Total: {result.total_hours_min}–{result.total_hours_max} h** · "
        f"**Coste: {_fmt(cost_min)}–{_fmt(cost_max)} €** ({rate} €/h) · "
        f"**Duración: {result.total_duration_weeks} semanas** · "
        f"**Confianza: {result.confidence_pct}%**"
    )
    parts = [result.summary, ""]

    if output_format == "phases_table":
        parts += [
            "| Fase | Descripción | Horas min | Horas max | Confianza |",
            "|---|---|---|---|---|",
        ]
        parts += [
            f"| {p.name} | {p.summary} | {p.hours_min} | {p.hours_max} | {p.confidence_pct}% |"
            for p in result.phases
        ]
        parts += [
            f"| **Total** | | **{result.total_hours_min}–{result.total_hours_max} h** "
            f"| | **{result.confidence_pct}%** |",
            "",
            totals,
        ]
    elif output_format == "line_items":
        parts += [
            f"- **{p.name}**: {p.hours_min}–{p.hours_max} h ({p.confidence_pct}%) — {p.summary}"
            for p in result.phases
        ]
        parts += ["", totals]
    else:  # narrative
        parts += [
            f"**{p.name}** ({p.hours_min}–{p.hours_max} h, {p.confidence_pct}% de confianza): "
            f"{p.summary}"
            for p in result.phases
        ]
        parts += ["", totals]

    if result.assumptions:
        parts += ["", "**Supuestos:**"] + [f"- {a}" for a in result.assumptions]
    if result.out_of_scope:
        parts += ["", "**Fuera de alcance:**"] + [f"- {o}" for o in result.out_of_scope]
    return "\n".join(parts)
