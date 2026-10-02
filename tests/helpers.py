"""Utilidades compartidas por los tests: documentos generados en memoria y LLM falso."""

from __future__ import annotations

import io
import json


def make_pdf(text: str) -> bytes:
    """PDF mínimo de una página con ``text`` (ASCII, sin paréntesis).

    Con ``text=""`` genera una página sin texto: simula un PDF escaneado.
    Se construye a mano para no añadir dependencias solo para tests.
    """
    content = f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET".encode("latin-1") if text else b""
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R "
        b"/Resources << /Font << /F1 5 0 R >> >> >>",
        b"<< /Length %d >>\nstream\n" % len(content) + content + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for i, obj in enumerate(objects, start=1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % i + obj + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
    for off in offsets:
        out += b"%010d 00000 n \n" % off
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (
        len(objects) + 1,
        xref,
    )
    return bytes(out)


def make_docx(paragraphs: list[str], table: list[list[str]] | None = None) -> bytes:
    from docx import Document

    document = Document()
    for paragraph in paragraphs:
        document.add_paragraph(paragraph)
    if table:
        t = document.add_table(rows=len(table), cols=len(table[0]))
        for r, row in enumerate(table):
            for c, value in enumerate(row):
                t.cell(r, c).text = value
    buffer = io.BytesIO()
    document.save(buffer)
    return buffer.getvalue()


KNOWN_TECHNOLOGIES = ["React", "FastAPI", "PostgreSQL", "Kubernetes"]


class FakeLLM:
    """Sustituto de ``LLMWrapper``: graba cada ``messages`` y responde sin red.

    - Si el system es el del extractor, devuelve un JSON con los hechos que
      encuentra por palabras clave en el último mensaje (o ``extractor_text``
      literal, para simular respuestas rotas).
    - Si no, devuelve una "estimación" que nombra las tecnologías presentes en
      el último mensaje, para que el contenido de un adjunto influya en la salida.
    """

    def __init__(
        self,
        extractor_text: str | None = None,
        fail_estimator: bool = False,
        estimator_text: str | None = None,
    ):
        self.calls: list[list[dict]] = []
        self.extractor_text = extractor_text
        self.fail_estimator = fail_estimator
        self.estimator_text = estimator_text

    @staticmethod
    def _is_extractor(messages: list[dict]) -> bool:
        return "extractor de hechos" in messages[0]["content"]

    @property
    def estimator_calls(self) -> list[list[dict]]:
        return [c for c in self.calls if not self._is_extractor(c)]

    def complete(self, messages: list[dict], max_tokens: int = 4000) -> dict:
        self.calls.append(messages)
        last = messages[-1]["content"]
        base = {"model": "fake-model", "provider": "fake", "fallback_used": False}

        if self._is_extractor(messages):
            if self.extractor_text is not None:
                return {**base, "text": self.extractor_text}
            # Solo mira el mensaje del cliente y los adjuntos, no los hechos previos.
            relevant = last.split("<respuesta_estimador>")[0].split("</hechos_previos>")[-1]
            facts = {
                "project_name": "Hotelia" if "Hotelia" in relevant else None,
                "assumed_team_size": 4 if "seremos 4" in relevant.lower() else None,
                "mentioned_technologies": [t for t in KNOWN_TECHNOLOGIES if t in relevant],
                "agreed_scope": None,
            }
            return {**base, "text": json.dumps(facts)}

        if self.fail_estimator:
            raise RuntimeError("proveedor caído")
        if self.estimator_text is not None:
            return {**base, "text": self.estimator_text}
        techs = [t for t in KNOWN_TECHNOLOGIES if t in last] or ["sin stack definido"]
        n = len(self.estimator_calls)
        return {**base, "text": f"Estimación #{n}. Stack: {', '.join(techs)}."}
