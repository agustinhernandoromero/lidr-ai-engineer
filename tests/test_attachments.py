"""Unitarios de extracción local de adjuntos (camino B)."""

import pytest

from app.services.attachments import AttachmentError, extract_attachment, format_attachments
from tests.helpers import make_docx, make_pdf

MAX_BYTES = 3_000_000
MAX_CHARS = 20_000


def test_pdf_text_is_extracted():
    result = extract_attachment(
        "spec.pdf", make_pdf("El despliegue se hara en Kubernetes"), MAX_BYTES, MAX_CHARS
    )
    assert "Kubernetes" in result.text
    assert not result.truncated and not result.empty
    assert result.warnings == []


def test_docx_paragraphs_and_tables_are_extracted():
    data = make_docx(["Requisito: login con SSO"], table=[["Modulo", "Pagos"]])
    result = extract_attachment("propuesta.DOCX", data, MAX_BYTES, MAX_CHARS)
    assert "login con SSO" in result.text
    assert "Modulo | Pagos" in result.text


def test_text_over_limit_is_truncated_with_notice():
    data = make_docx(["x" * 150])
    result = extract_attachment("largo.docx", data, MAX_BYTES, max_chars=100)
    assert result.truncated
    assert result.chars == 150
    assert result.text.endswith("[…truncado: se omitieron 50 caracteres]")
    assert "truncado" in result.warnings[0]


def test_pdf_without_text_is_marked_not_rejected():
    result = extract_attachment("escaneado.pdf", make_pdf(""), MAX_BYTES, MAX_CHARS)
    assert result.empty
    assert result.text == "[sin texto extraíble]"
    assert "escaneado.pdf" in result.warnings[0]


@pytest.mark.parametrize("filename", ["notas.txt", "imagen.png", "sin_extension"])
def test_unsupported_extension_is_415(filename):
    with pytest.raises(AttachmentError) as exc:
        extract_attachment(filename, b"hola", MAX_BYTES, MAX_CHARS)
    assert exc.value.status_code == 415


def test_file_over_size_limit_is_413():
    with pytest.raises(AttachmentError) as exc:
        extract_attachment("grande.pdf", b"x" * 11, max_bytes=10, max_chars=MAX_CHARS)
    assert exc.value.status_code == 413


@pytest.mark.parametrize("filename", ["roto.pdf", "roto.docx"])
def test_corrupt_file_is_422_with_filename(filename):
    with pytest.raises(AttachmentError) as exc:
        extract_attachment(filename, b"no soy un documento", MAX_BYTES, MAX_CHARS)
    assert exc.value.status_code == 422
    assert filename in exc.value.detail


def test_format_attachments_uses_separator():
    a = extract_attachment("a.pdf", make_pdf("Texto A"), MAX_BYTES, MAX_CHARS)
    b = extract_attachment("b.docx", make_docx(["Texto B"]), MAX_BYTES, MAX_CHARS)
    formatted = format_attachments([a, b])
    assert formatted.startswith("--- attachment: a.pdf ---\nTexto A")
    assert "--- attachment: b.docx ---\nTexto B" in formatted
    assert format_attachments([]) == ""
