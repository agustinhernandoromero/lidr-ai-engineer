"""Tier dinámico: reglas puras en orden, la primera que encaja gana."""

from app.services.sessions import ProjectMetadata
from app.services.tier_resolver import Tier, resolve_tier

EMPTY = ProjectMetadata()


def test_override_always_wins():
    assert resolve_tier("bajo NDA", EMPTY, Tier.PM) == (Tier.PM, "explicit_override")


def test_nda_in_transcript_or_scope_is_executive():
    assert resolve_tier("Todo es confidencial, hay NDA", EMPTY) == (Tier.EXECUTIVE, "nda_detected")
    md = ProjectMetadata(agreed_scope="Proyecto bajo embargo hasta el lanzamiento")
    assert resolve_tier("Añadimos login", md) == (Tier.EXECUTIVE, "nda_detected")


def test_regulation_is_executive():
    assert resolve_tier("Debe cumplir el RGPD", EMPTY) == (Tier.EXECUTIVE, "regulatory_context")
    md = ProjectMetadata(mentioned_technologies=["ISO 27001"])
    assert resolve_tier("Seguimos", md) == (Tier.EXECUTIVE, "regulatory_context")


def test_two_distinct_technical_terms_make_it_developer():
    assert resolve_tier("Microservicios en Kubernetes con Kafka", EMPTY) == (
        Tier.DEVELOPER, "technical_audience")
    assert resolve_tier("Lo desplegamos con Docker", EMPTY) == (Tier.DEFAULT, "default")


def test_small_team_is_pm():
    md = ProjectMetadata(assumed_team_size=2)
    assert resolve_tier("Seguimos con el MVP", md) == (Tier.PM, "small_team_pm")


def test_precedence_executive_beats_developer():
    text = "Bajo NDA: microservicios en Kubernetes con Kafka"
    assert resolve_tier(text, EMPTY) == (Tier.EXECUTIVE, "nda_detected")


def test_default_when_nothing_matches():
    assert resolve_tier("Un portal de reservas sencillo", EMPTY) == (Tier.DEFAULT, "default")
