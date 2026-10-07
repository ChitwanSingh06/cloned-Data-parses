import json
import os
from pathlib import Path

import pytest

from app.core.config import PROCESSED_DIR
from app.models.block import BlockType
from app.models.document import Document
from app.output.markdown_builder import build_markdown
from app.pipeline.confidence import add_confidence, level, score
from app.pipeline.detector import detect_document
from app.pipeline.orchestrator import parse_pdf


def test_confidence_from_signals_not_random():
    assert score({}) < 0.6  # no evidence -> low
    assert score({"ocr": 0.95, "layout": 0.9}) > 0.85
    assert score({"ocr": 0.95, "layout": 0.2}) < 0.7  # weakest signal drags the score
    assert level(0.9).value == "HIGH" and level(0.7).value == "MEDIUM" and level(0.3).value == "LOW"


def test_pdf_loading_and_page_info(pdfs):
    det = detect_document(str(pdfs["digital"]))
    assert not det["errors"] and len(det["pages"]) == 1
    assert det["pages"][0]["width"] > 0 and det["pages"][0]["is_scanned"] is False


def test_digital_text_headings_lists_tables(parsed):
    doc = parsed["digital"]
    types = [b.type for b in doc.blocks]
    assert BlockType.heading in types and BlockType.paragraph in types and BlockType.table in types
    heads = [b for b in doc.blocks if b.type == BlockType.heading]
    assert heads[0].level == 1 and heads[1].level == 2 and heads[1].parent_id == heads[0].id
    lst = [b for b in doc.blocks if b.type == BlockType.list]
    assert lst and lst[0].content["items"] == ["First bullet item", "Second bullet item"]


def test_header_footer_removed_from_markdown(parsed):
    doc = parsed["mixed"]  # digital, scanned, digital: running footer repeats across pages
    assert any(b.type == BlockType.footer and "Acme Corp" in b.content for b in doc.blocks)  # kept in JSON
    assert any(b.type == BlockType.footer and b.meta.get("page_number_only") for b in doc.blocks)
    md = (PROCESSED_DIR / doc.document_id / "document.md").read_text(encoding="utf-8")
    assert "Acme Corp Confidential" not in md  # excluded from main content


def test_scanned_page_detection_and_mixed(parsed):
    assert parsed["scanned"].pages[0].is_scanned is True
    assert [p.is_scanned for p in parsed["mixed"].pages] == [False, True, False]
    assert {p.source for p in parsed["mixed"].pages} == {"digital", "ocr"}


def test_reading_order_two_column(parsed):
    texts = [b.content for b in parsed["twocol"].blocks if b.type == BlockType.paragraph]
    tags = [t.split()[0] for t in texts]
    assert tags == ["LEFTCOL"] * 3 + ["RIGHTCOL"] * 3


def test_provenance_confidence_status_on_every_block(parsed):
    for doc in parsed.values():
        for b in doc.blocks:
            assert b.provenance and b.provenance.page >= 1 and b.provenance.document == doc.document_id
            assert b.bbox and len(b.bbox) == 4 and b.provenance.sources
            assert 0.0 <= b.confidence <= 1.0 and b.confidence_level and b.status


def test_ocr_blocks_carry_ocr_signal(parsed):
    paras = [b for b in parsed["scanned"].blocks if b.type == BlockType.paragraph]
    assert paras and all("ocr" in b.signals for b in paras)
    assert any("quick brown fox" in b.content for b in paras)


def test_markdown_and_json_from_same_model(parsed):
    doc = parsed["digital"]
    out = PROCESSED_DIR / doc.document_id
    payload = json.loads((out / "document.json").read_text(encoding="utf-8"))
    assert Document(**payload).document_id == doc.document_id
    assert (out / "document.md").read_text(encoding="utf-8") == build_markdown(payload)
    assert "| Region |" in build_markdown(payload)


def test_cross_page_paragraph_and_table_merge(parsed):
    t = [b for b in parsed["multitable"].blocks if b.type == BlockType.table]
    assert len(t) == 1 and len(t[0].content["rows"]) == 79
    assert t[0].content["page_span"] == [1, 2, 3] and len(t[0].provenance.sources) == 3
    assert t[0].meta["merge_signals"]["repeated_header"]


def test_failsafe_corrupt_unsupported(pdfs):
    for key, code in (("corrupt", "CORRUPT_PDF"), ("notpdf", "CORRUPT_PDF"), ("xlsx", "UNSUPPORTED_FORMAT")):
        doc = parse_pdf(str(pdfs[key]))
        assert doc.status == "FAILED" and doc.errors[0]["code"] == code
        assert doc.processing_time < 60
        assert (PROCESSED_DIR / doc.document_id / "document.json").exists()


def test_failed_region_gives_partial_success(pdfs, monkeypatch):
    import app.pipeline.router as router
    monkeypatch.setattr(router, "extract_table", lambda *a, **k: (_ for _ in ()).throw(ValueError("boom")))
    doc = parse_pdf(str(pdfs["digital"]))
    assert doc.status == "PARTIAL_SUCCESS"
    assert any(e["code"] == "TABLE_EXTRACTION_FAILURE" for e in doc.errors)
    assert any(b.status.value == "REVIEW_REQUIRED" and b.meta.get("fallback_for") == "table" for b in doc.blocks)
    assert any(b.type == BlockType.paragraph for b in doc.blocks)  # rest of the doc survives


def _find_unicode_math_font():
    """A system TTF that has the math glyphs used below (Linux DejaVu, Windows Arial/Segoe, macOS Arial), else None."""
    import pymupdf
    win_fonts = Path(os.environ.get("WINDIR") or os.environ.get("SystemRoot") or r"C:\Windows") / "Fonts"
    candidates = [
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"), Path("/usr/share/fonts/dejavu/DejaVuSans.ttf"),
        win_fonts / "arial.ttf", win_fonts / "segoeui.ttf", win_fonts / "seguisym.ttf", win_fonts / "l_10646.ttf",
        Path("/Library/Fonts/Arial Unicode.ttf"), Path("/System/Library/Fonts/Supplemental/Arial Unicode.ttf"),
    ]
    for c in candidates:
        try:
            if c.is_file():
                font = pymupdf.Font(fontfile=str(c))
                if all(font.has_glyph(ord(ch)) for ch in "∑∫≤αβ"):
                    return c
        except Exception:
            continue
    return None


@pytest.mark.skipif(_find_unicode_math_font() is None, reason="needs a unicode font to build the fixture")
def test_equation_never_invented(tmp_path, monkeypatch):
    # With no usable geometry/recognizer the region must be preserved and flagged, never given invented LaTeX.
    import app.extractors.equations.equation_extractor as ee
    monkeypatch.setattr(ee, "page_region_to_latex", lambda page, bbox: {"latex": None, "unmapped": [], "structures": []})
    monkeypatch.setattr(ee, "_pix2tex", lambda: None)
    import pymupdf
    pdf = pymupdf.open(); pg = pdf.new_page()
    pg.insert_text((72, 100), "A normal paragraph of ordinary prose that is long enough to be text.", fontsize=11)
    pg.insert_text((200, 200), "∑ x_i = ∫ f(x) dx ≤ α + β   (1)", fontsize=12, fontname="dj", fontfile=str(_find_unicode_math_font()))
    pdf.save(str(tmp_path / "eq.pdf"))
    doc = parse_pdf(str(tmp_path / "eq.pdf"))
    eq = [b for b in doc.blocks if b.type == BlockType.equation]
    assert eq and eq[0].meta["latex"] is None and eq[0].status.value == "REVIEW_REQUIRED"


def test_end_to_end_smoke(pdfs):
    doc = parse_pdf(str(pdfs["mixed"]))
    out = PROCESSED_DIR / doc.document_id
    js = json.loads((out / "document.json").read_text(encoding="utf-8"))
    md = (out / "document.md").read_text(encoding="utf-8")
    assert md.strip() and js["status"] in ("SUCCESS", "PARTIAL_SUCCESS") and js["page_count"] == 3
    for b in js["blocks"]:
        assert b["provenance"]["page"] and b["provenance"]["bbox"] and "confidence" in b and b["status"]
    assert js["stats"]["seconds_per_page"] > 0


def test_figure_preserved_with_caption(tmp_path):
    import pymupdf
    from PIL import Image, ImageDraw
    img = Image.new("RGB", (400, 250), "white")
    ImageDraw.Draw(img).rectangle([40, 60, 120, 220], fill="navy")
    img.save(tmp_path / "chart.png")
    pdf = pymupdf.open(); pg = pdf.new_page()
    pg.insert_text((72, 80), "Opening paragraph of ordinary prose that introduces the figure below in detail.", fontsize=11)
    pg.insert_image(pymupdf.Rect(100, 120, 400, 307), filename=str(tmp_path / "chart.png"))
    pg.insert_text((100, 325), "Figure 1: Revenue by quarter", fontsize=10)
    pdf.save(str(tmp_path / "fig.pdf"))
    doc = parse_pdf(str(tmp_path / "fig.pdf"))
    fig = [b for b in doc.blocks if b.type in (BlockType.figure, BlockType.chart)]
    assert len(fig) == 1 and fig[0].meta["caption"].startswith("Figure 1")
    assert (PROCESSED_DIR / doc.document_id / fig[0].meta["image_path"]).exists()
    assert fig[0].type == BlockType.figure  # caption gives no chart cue, so it is not upgraded to "chart"
    assert fig[0].provenance.page == 1 and fig[0].bbox
