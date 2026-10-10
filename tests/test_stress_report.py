"""Report: tablas y curvas a partir del CSV, sin caerse con datos incompletos."""

from evals.stress.report import build_report, main, percentile
from evals.stress.run import main as run_main


def test_percentile_nearest_rank():
    assert percentile([1, 2, 3, 4], 0.5) == 2
    assert percentile([1, 2, 3, 4], 0.95) == 4
    assert percentile([], 0.5) is None


def test_report_from_fake_run_has_all_sections(tmp_path):
    csv_path = tmp_path / "results.csv"
    run_main(["--in-process", "--fake-llm", "--output", str(csv_path), "--pdf-dir", str(tmp_path / "p")])
    out = tmp_path / "REPORT.md"
    reading = tmp_path / "reading.md"
    reading.write_text("Párrafo de lectura de prueba.", encoding="utf-8")

    assert main(["--input", str(csv_path), "--output", str(out), "--reading", str(reading)]) == 0
    text = out.read_text(encoding="utf-8")
    for heading in ("## Resumen", "## Curva 1", "## Curva 2", "## Curva 3",
                    "## Adjuntos", "## Lectura", "## Método"):
        assert heading in text
    assert "Párrafo de lectura de prueba." in text


def test_report_survives_error_rows_and_missing_blocks():
    rows = [{"block": "attachment", "scenario": "attachment", "attachment_kb": "5", "repeat": "1",
             "status": "error", "latency_ms": "", "cost_usd": "", "cache_hit_kind": "",
             "tokens_in": "", "memory_recall": "", "memory_recall_with_window": "",
             "project_name_recalled": "", "attachment_recall": "", "turn_index": "1",
             "attachments_total_chars": ""}]
    text = build_report(rows, None)
    assert "—" in text and "pendiente" in text
