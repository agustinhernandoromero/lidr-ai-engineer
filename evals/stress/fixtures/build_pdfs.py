"""PDFs sintéticos de tamaño calibrado para el estrés de adjuntos.

"KB" aquí son miles de caracteres de texto (lo que llega al prompt), no bytes
del fichero. Cada documento lleva tres marcadores en posiciones conocidas del
texto (10 %, 50 % y 90 %): con el límite real de 20.000 caracteres, los
documentos grandes pierden los marcadores tardíos y el recuerdo del adjunto lo
refleja. Deterministas y sin dependencias: el PDF se escribe a mano (ASCII).

    uv run python -m evals.stress.fixtures.build_pdfs
"""

from __future__ import annotations

from pathlib import Path

MARKERS: dict[str, float] = {"Stripe": 0.1, "Twilio": 0.5, "Salesforce": 0.9}
MARKER_LINES = {
    "Stripe": "Requisito clave: los cobros de las reservas se procesan con Stripe.",
    "Twilio": "Requisito clave: los avisos por SMS se envian con Twilio.",
    "Salesforce": "Requisito clave: los clientes se sincronizan con Salesforce.",
}
FILLER = [
    "Requisito {i}: el sistema registra cada reserva con fecha, hora, sala y responsable.",
    "Requisito {i}: los administradores pueden bloquear salas por mantenimiento.",
    "Requisito {i}: cada cambio de estado queda registrado para auditoria posterior.",
    "Requisito {i}: los usuarios reciben una confirmacion al completar la operacion.",
    "Requisito {i}: los listados admiten filtros por fecha, sede y tipo de sala.",
]
LINES_PER_PAGE = 50
DEFAULT_DIR = Path(__file__).parent


def _lines(target_chars: int) -> list[str]:
    lines: list[str] = []
    total, i = 0, 1
    pending = sorted(MARKERS.items(), key=lambda kv: kv[1])
    while total < target_chars:
        if pending and total >= pending[0][1] * target_chars:
            line = MARKER_LINES[pending.pop(0)[0]]
        else:
            line = FILLER[i % len(FILLER)].format(i=i)
            i += 1
        lines.append(line)
        total += len(line) + 1  # + salto de línea en la extracción
    return lines


def build_pdf(target_chars: int) -> bytes:
    lines = _lines(target_chars)
    pages = [lines[k : k + LINES_PER_PAGE] for k in range(0, len(lines), LINES_PER_PAGE)]
    n_pages = len(pages)
    font_id = 3 + 2 * n_pages
    # Orden de objetos: 1 Catalog, 2 Pages, pares (Page = 3+2p, Contents = 4+2p), fuente al final.
    objects: list[bytes] = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids ["
        + b" ".join(b"%d 0 R" % (3 + 2 * p) for p in range(n_pages))
        + b"] /Count %d >>" % n_pages,
    ]
    for p, page_lines in enumerate(pages):
        body = " ".join(f"({line}) Tj T*" for line in page_lines)
        content = f"BT /F1 9 Tf 40 800 Td 14 TL {body} ET".encode("latin-1")
        objects.append(
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 842] /Contents %d 0 R "
            b"/Resources << /Font << /F1 %d 0 R >> >> >>" % (4 + 2 * p, font_id)
        )
        objects.append(b"<< /Length %d >>\nstream\n" % len(content) + content + b"\nendstream")
    objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")

    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for number, obj in enumerate(objects, start=1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % number + obj + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
    for off in offsets:
        out += b"%010d 00000 n \n" % off
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (
        len(objects) + 1,
        xref,
    )
    return bytes(out)


def pdf_path(out_dir: Path, kb: int) -> Path:
    return out_dir / f"attach_{kb}kb.pdf"


def build_all(out_dir: Path = DEFAULT_DIR, sizes_kb: list[int] | None = None) -> dict[int, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = {}
    for kb in sizes_kb or [5, 20, 50, 100]:
        path = pdf_path(out_dir, kb)
        path.write_bytes(build_pdf(kb * 1000))
        paths[kb] = path
    return paths


if __name__ == "__main__":
    for kb, path in build_all().items():
        print(f"{kb} KB -> {path} ({path.stat().st_size} bytes)")
