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


def test_cli_messages_survive_a_cp1252_windows_console(tmp_path, monkeypatch):
    """La consola de Windows usa cp1252: los mensajes no pueden llevar flechas Unicode."""
    import io
    import sys

    console = io.TextIOWrapper(io.BytesIO(), encoding="cp1252")
    monkeypatch.setattr(sys, "stdout", console)
    csv_path = tmp_path / "results.csv"
    assert run_main(["--in-process", "--fake-llm", "--output", str(csv_path),
                     "--pdf-dir", str(tmp_path / "p"), "--scenarios", "growing", "--turns", "2",
                     "--attachment-sizes", "5", "--repeats", "1"]) == 0
    assert main(["--input", str(csv_path), "--output", str(tmp_path / "R.md"),
                 "--reading", str(tmp_path / "none.md")]) == 0


def test_latency_percentiles_ignore_cache_hits():
    base = {"block": "attachment", "scenario": "attachment", "attachment_kb": "100", "status": "ok",
            "cost_usd": "0", "tokens_in": "0", "memory_recall": "", "memory_recall_with_window": "",
            "project_name_recalled": "", "attachment_recall": "0.33", "turn_index": "1",
            "attachments_total_chars": "20000"}
    rows = [{**base, "repeat": "1", "cache_hit_kind": "none", "latency_ms": "15000"}] + [
        {**base, "repeat": str(i), "cache_hit_kind": "exact", "latency_ms": "1"} for i in (2, 3, 4)]
    summary_line = next(l for l in build_report(rows, None).splitlines() if l.startswith("| attachment"))
    assert "| 15000 | 15000 |" in summary_line


def test_token_buckets_reach_realistic_turn_sizes():
    from evals.stress.report import TOKEN_BUCKETS
    assert TOKEN_BUCKETS[-1][0] >= 20_000
