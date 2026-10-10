"""PDFs sintéticos: tamaño calibrado, deterministas y con marcadores en posiciones."""

from app.services.attachments import extract_attachment
from evals.stress.fixtures.build_pdfs import MARKERS, build_all, build_pdf


def extract(data: bytes, max_chars: int = 1_000_000):
    return extract_attachment("a.pdf", data, max_bytes=10_000_000, max_chars=max_chars)


def test_text_size_is_close_to_target_and_deterministic():
    data = build_pdf(5_000)
    assert data == build_pdf(5_000)
    chars = extract(data).chars
    assert 4_500 <= chars <= 5_800


def test_all_markers_survive_without_truncation():
    text = extract(build_pdf(20_000)).text
    assert all(marker in text for marker in MARKERS)


def test_real_limit_truncates_the_late_markers_of_big_documents():
    result = extract(build_pdf(50_000), max_chars=20_000)
    assert result.truncated
    assert "Stripe" in result.text
    assert "Twilio" not in result.text and "Salesforce" not in result.text


def test_build_all_writes_one_file_per_size(tmp_path):
    paths = build_all(tmp_path, [5, 20])
    assert sorted(paths) == [5, 20]
    assert paths[5].name == "attach_5kb.pdf" and paths[5].stat().st_size > 0
