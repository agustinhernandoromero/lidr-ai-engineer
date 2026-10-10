"""Tier dinámico: para quién se redacta la estimación.

Cadena de reglas puras evaluadas en orden; gana la primera que se cumple. El
resolutor devuelve el tier y el nombre de la regla, para poder explicar en el
panel "executive (nda_detected)" en vez de solo "executive". Sin llamadas al
LLM. El tier decide el enfoque; ``detail_level`` sigue decidiendo la profundidad.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from typing import Callable

import structlog

from app.services.compression.anchors import affirmed_match
from app.services.sessions import ProjectMetadata

logger = structlog.get_logger(__name__)


class Tier(str, Enum):
    EXECUTIVE = "executive"
    PM = "pm"
    DEVELOPER = "developer"
    DEFAULT = "default"


_NDA = re.compile(
    r"\b(nda|non[- ]?disclosure|confidencial|confidential|acuerdo de confidencialidad|"
    r"bajo embargo|under embargo|legal hold)\b",
    re.IGNORECASE,
)
_REGULATORY = re.compile(
    r"\b(rgpd|gdpr|lopdgdd|hipaa|sox|pci[- ]?dss|iso[- ]?27001|ens|ccpa)\b", re.IGNORECASE
)
_DEV_TERMS = re.compile(
    r"\b(docker|kubernetes|k8s|microservicios?|microservices?|terraform|helm|grpc|graphql|"
    r"kafka|airflow|spark|rabbitmq)\b",
    re.IGNORECASE,
)


@dataclass
class _Context:
    transcript: str
    metadata: ProjectMetadata


# Las reglas de contenido usan affirmed_match: "Excluido: RGPD avanzado" o
# "esto no es confidencial" no deben cambiar la audiencia.
def _has_nda(ctx: _Context) -> bool:
    return affirmed_match(_NDA, ctx.transcript) or affirmed_match(_NDA, ctx.metadata.agreed_scope or "")


def _has_regulation(ctx: _Context) -> bool:
    haystacks = [ctx.transcript, ctx.metadata.agreed_scope or "", *ctx.metadata.mentioned_technologies]
    return any(affirmed_match(_REGULATORY, h) for h in haystacks)


def _technical_audience(ctx: _Context) -> bool:
    # Dos términos técnicos distintos: con uno solo ("lo desplegamos con Docker")
    # hay demasiado ruido para cambiar de audiencia. rstrip("s") hace que
    # "microservicio" y "microservicios" cuenten como un solo término.
    terms = {t.lower().rstrip("s") for t in _DEV_TERMS.findall(ctx.transcript)}
    return len(terms) >= 2


def _small_team(ctx: _Context) -> bool:
    size = ctx.metadata.assumed_team_size
    return size is not None and size <= 2


_RULES: tuple[tuple[str, Tier, Callable[[_Context], bool]], ...] = (
    ("nda_detected", Tier.EXECUTIVE, _has_nda),
    ("regulatory_context", Tier.EXECUTIVE, _has_regulation),
    ("technical_audience", Tier.DEVELOPER, _technical_audience),
    ("small_team_pm", Tier.PM, _small_team),
)


def resolve_tier(
    transcript: str, metadata: ProjectMetadata, override: Tier | None = None
) -> tuple[Tier, str]:
    if override is not None:
        logger.info("tier_resolved", tier=override.value, rule="explicit_override")
        return override, "explicit_override"

    ctx = _Context(transcript=transcript or "", metadata=metadata)
    for name, tier, predicate in _RULES:
        try:
            if predicate(ctx):
                logger.info("tier_resolved", tier=tier.value, rule=name)
                return tier, name
        except Exception as exc:  # noqa: BLE001
            logger.warning("tier_rule_failed", rule=name, error=str(exc))

    logger.info("tier_resolved", tier=Tier.DEFAULT.value, rule="default")
    return Tier.DEFAULT, "default"
