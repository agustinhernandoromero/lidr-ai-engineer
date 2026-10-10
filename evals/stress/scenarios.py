"""Escenarios sintéticos multiturno sobre un mismo proyecto.

Cada turno declara, opcionalmente, un hecho corto que debe seguir en la memoria
de la sesión (resumen, anclas o metadata) en los turnos siguientes. Los hechos
están escritos literalmente en el texto del turno para que la comprobación sea
una coincidencia exacta, sin LLM-as-judge.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Turn:
    index: int
    transcript: str
    fact: str | None = None


@dataclass(frozen=True)
class Scenario:
    name: str
    project_name: str
    project_type: str
    turns: list[Turn]


def _turns(items: list[tuple[str, str | None]]) -> list[Turn]:
    return [Turn(i, text, fact) for i, (text, fact) in enumerate(items, start=1)]


GROWING = Scenario("growing", "Nimbus", "web_saas", _turns([
    ("Proyecto Nimbus: un SaaS de reservas de salas de reuniones para empresas medianas, "
     "con React y PostgreSQL.", "Nimbus"),
    ("Necesitamos autenticación con email y contraseña y recuperación de cuenta.", "autenticación"),
    ("Debe ser multi-tenant: cada empresa ve solo sus salas y sus reservas.", "multi-tenant"),
    ("Queremos un audit log de quién reserva, cambia o cancela cada sala.", "audit log"),
    ("Añadimos exportación a CSV de las reservas del mes.", "CSV"),
    ("Integración con Google Calendar y Outlook para bloquear las salas reservadas.", "Google Calendar"),
    ("Un panel de ocupación con estadísticas por planta y por semana.", "ocupación"),
    ("Las empresas grandes piden SSO con SAML para entrar con su cuenta corporativa.", "SSO"),
    ("Notificaciones por email y Slack antes de cada reunión.", "Slack"),
    ("Dame la estimación total actualizada de Nimbus con todo lo acordado hasta ahora.", None),
]))

PIVOT = Scenario("pivot", "Orbit", "mobile_app", _turns([
    ("Proyecto Orbit: app de fidelización para cafeterías, con React Native en el móvil "
     "y Node en el backend.", "Orbit"),
    ("Los clientes acumulan puntos escaneando un código QR en la caja.", "QR"),
    ("Cada cafetería puede configurar sus propias recompensas.", "recompensas"),
    ("Un panel web para que el dueño vea clientes, puntos y canjes.", "canjes"),
    ("Cambio importante: abandonamos React Native y la app se hará en Flutter.", "Flutter"),
    ("Queremos notificaciones push para anunciar promociones.", "push"),
    ("Integración con el TPV Square para registrar las compras.", "Square"),
    ("Modo sin conexión: los puntos se sincronizan al recuperar la red.", "sin conexión"),
    ("Soporte para varias cafeterías de la misma cadena con una sola cuenta.", "cadena"),
    ("Resume el stack definitivo de Orbit y la estimación actualizada.", None),
]))

CONTRADICTION = Scenario("contradiction", "Atlas", "web_saas", _turns([
    ("Proyecto Atlas: portal B2B para que los distribuidores hagan pedidos al por mayor.", "Atlas"),
    ("Catálogo con precios por cliente y pedidos recurrentes programados.", "precios por cliente"),
    ("El presupuesto está cerrado en 30.000 euros.", "30.000"),
    ("Integración con el ERP Odoo para stock y facturas.", "Odoo"),
    ("Los distribuidores necesitan ver el estado de sus envíos en tiempo real.", "envíos"),
    ("Añadimos un buscador avanzado por referencia y por familia de producto.", "buscador"),
    ("Informes de ventas por distribuidor exportables a Excel.", "Excel"),
    ("Cambio de planes: el presupuesto está cerrado ahora en 80.000 euros.", "80.000"),
    ("Queremos también una API para que los distribuidores grandes integren sus sistemas.", "API"),
    ("Recuérdame el presupuesto vigente de Atlas y si la estimación actual cabe en él.", None),
]))

SCENARIOS: dict[str, Scenario] = {s.name: s for s in (GROWING, PIVOT, CONTRADICTION)}


def facts_due(scenario: Scenario, n: int) -> list[str]:
    """Hechos declarados en turnos anteriores a ``n`` que la memoria debería conservar."""
    return [t.fact for t in scenario.turns if t.fact and t.index < n]
