import pytest

from app.extractors.ocr.ocr_engine import OCRUnavailable, available_engine


def test_ocr_engine_and_scanned_table(parsed):
    try:
        available_engine()
    except OCRUnavailable:
        pytest.skip("no OCR engine installed")
    doc = parsed["scanned"]
    assert doc.pages[0].source == "ocr"
    tables = [b for b in doc.blocks if b.type.value == "table"]
    assert tables and "North" in " ".join(" ".join(r) for r in tables[0].content["rows"])
    assert any(b.confidence_level.value in ("HIGH", "MEDIUM") for b in doc.blocks)
