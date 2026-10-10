"""Detector heurístico de anclas: compromisos que no pueden olvidarse."""

import pytest

from app.services.compression.anchors import detect_anchor


@pytest.mark.parametrize("text, rule", [
    ("Hemos firmado un acuerdo de confidencialidad con el cliente", "nda"),
    ("Todo esto está bajo NDA", "nda"),
    ("Ya hemos firmado el contrato marco", "signed_contract"),
    ("We signed the contract yesterday", "signed_contract"),
    ("El alcance queda cerrado con estas cinco pantallas", "scope_frozen"),
    ("The scope is frozen", "scope_frozen"),
    ("El presupuesto está cerrado en 30.000 euros", "budget_locked"),
    ("Hay un tope de presupuesto de 80k", "budget_locked"),
    ("The budget is capped at 50k", "budget_locked"),
    ("Tiene que cumplir el RGPD", "compliance"),
    ("Necesitamos certificación ISO 27001", "compliance"),
    ("La fecha límite es inamovible: 1 de marzo", "deadline_hard"),
    ("Tiene que estar en producción antes de Navidad", "deadline_hard"),
    ("El cliente se compromete a entregar los diseños", "explicit_commitment"),
    ("We agreed to deliver in two phases", "explicit_commitment"),
])
def test_commitments_are_detected(text, rule):
    assert detect_anchor(text) == rule


@pytest.mark.parametrize("text", [
    "Quizá el presupuesto ronde los 30k",
    "Haremos un ensayo de carga antes de salir",
    "Aún no hay nada firmado",
    "El alcance todavía puede cambiar",
    "Queremos un portal de reservas con React",
])
def test_ordinary_sentences_are_not_anchors(text):
    assert detect_anchor(text) is None
