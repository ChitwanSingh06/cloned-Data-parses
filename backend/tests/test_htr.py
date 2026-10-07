import numpy as np
import pymupdf
import pytest

import make_fixtures as fx
from app.extractors.ocr import handwriting, htr_engine
from app.models.block import BlockType
from app.pipeline.orchestrator import parse_pdf


@pytest.fixture(scope="module")
def hw_pdf(tmp_path_factory):
    d = tmp_path_factory.mktemp("hw")
    return fx.image_pdf(fx.handwriting_image(), d / "hw.pdf")


def _printed_line_crop(pdfs):
    pg = pymupdf.open(str(pdfs["digital"]))[0]
    pix = pg.get_pixmap(dpi=200, clip=pymupdf.Rect(72, 130, 540, 146), colorspace=pymupdf.csGRAY)
    return np.frombuffer(pix.samples, np.uint8).reshape(pix.height, pix.width)


def test_handwriting_score_separates_printed_from_wobbly(pdfs):
    printed = handwriting.handwriting_score(_printed_line_crop(pdfs), 0.95)
    hw = np.array(fx.handwriting_image(lines=1))
    wobbly = handwriting.handwriting_score(hw, None)
    assert printed < 0.4 and wobbly >= 0.55, (printed, wobbly)


def test_printed_lines_are_never_rerouted_to_htr(parsed):
    assert all(b.meta.get("text_kind", "printed") == "printed" for b in parsed["scanned"].blocks)
    assert all("htr" not in b.signals for b in parsed["scanned"].blocks)


def test_handwriting_uses_htr_when_available(hw_pdf, monkeypatch):
    monkeypatch.setattr(htr_engine, "htr_available", lambda: True)
    monkeypatch.setattr(htr_engine, "recognize", lambda img: ("meeting notes tuesday", 0.82))
    doc = parse_pdf(str(hw_pdf))
    hw = [b for b in doc.blocks if b.meta.get("text_kind") == "handwritten"]
    assert hw and hw[0].type == BlockType.paragraph
    b = hw[0]
    assert "meeting notes tuesday" in b.content and b.signals["htr"] == 0.82 and "ocr" not in b.signals
    assert b.provenance.extractor == "htr:trocr" and b.bbox and b.provenance.page == 1
    assert 0 <= b.bbox[0] < b.bbox[2] <= doc.pages[0].width and 0 <= b.bbox[1] < b.bbox[3] <= doc.pages[0].height


def test_handwriting_without_model_is_review_required_not_empty(hw_pdf, monkeypatch):
    monkeypatch.setattr(htr_engine, "htr_available", lambda: False)
    doc = parse_pdf(str(hw_pdf))
    assert doc.blocks, "page must not come back empty"
    flagged = [b for b in doc.blocks if b.status.value == "REVIEW_REQUIRED" and "handwriting" in b.meta.get("review_reason", "").lower()]
    assert flagged and flagged[0].confidence_level.value in ("LOW", "MEDIUM") and flagged[0].signals.get("htr_unavailable") or \
        flagged and flagged[0].meta.get("image_path")


def test_htr_failure_is_review_required(hw_pdf, monkeypatch):
    monkeypatch.setattr(htr_engine, "htr_available", lambda: True)
    monkeypatch.setattr(htr_engine, "recognize", lambda img: (_ for _ in ()).throw(RuntimeError("model crashed")))
    doc = parse_pdf(str(hw_pdf))
    assert any(b.status.value == "REVIEW_REQUIRED" and "failed" in b.meta.get("review_reason", "") for b in doc.blocks)


def test_ocr_unavailable_preserves_page_for_review(pdfs, monkeypatch):
    import app.pipeline.detector as det
    monkeypatch.setattr(det, "extract_ocr", lambda img: (_ for _ in ()).throw(det.OCRUnavailable("no tesseract")))
    doc = parse_pdf(str(pdfs["scanned"]))
    assert doc.status == "PARTIAL_SUCCESS" and any(e["code"] == "OCR_FAILURE" for e in doc.errors)
    assert doc.blocks and doc.blocks[0].status.value == "REVIEW_REQUIRED"
