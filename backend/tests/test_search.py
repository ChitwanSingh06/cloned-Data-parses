import json

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.models.block import Block, BlockType
from app.models.document import Document
from app.search.engine import build_pattern, search_document

client = TestClient(app)


def _doc():
    return Document(document_id="a" * 12, filename="x.pdf", page_count=3, blocks=[
        Block(id="B0001", type=BlockType.heading, content="Annual Revenue Review", page=1, bbox=[10, 10, 200, 30], confidence=0.97),
        Block(id="B0002", type=BlockType.paragraph, content="Total revenue grew.\nRevenue   rose again.", page=1, bbox=[10, 40, 200, 90], confidence=0.9),
        Block(id="B0003", type=BlockType.list, content={"ordered": False, "items": ["Cost cutting", "New REVENUE streams"]}, page=2, bbox=[10, 10, 100, 50], confidence=0.8),
        Block(id="B0004", type=BlockType.table, page=2, bbox=[10, 60, 300, 160], confidence=0.94,
              content={"headers": [["Region", "Revenue"]], "rows": [["North", "1,200"]], "cells": [
                  {"row": 0, "col": 0, "text": "Region"}, {"row": 0, "col": 1, "text": "Revenue"},
                  {"row": 1, "col": 0, "text": "North"}, {"row": 1, "col": 1, "text": "1,200"}]}),
        Block(id="B0005", type=BlockType.caption, content="Table 1: Regional performance", page=2, bbox=[10, 165, 200, 180], confidence=0.7),
        Block(id="B0006", type=BlockType.paragraph, content="Scanned OCR line about margins", page=3, bbox=[5, 5, 90, 20], confidence=0.61,
              extractor="ocr:tesseract"),
    ])


def test_exact_search_returns_provenance_fields():
    r = search_document(_doc(), "Regional performance")
    assert r.total_matches == 1
    h = r.results[0]
    assert (h.block_id, h.block_type.value, h.page, h.bbox, h.confidence) == ("B0005", "caption", 2, [10, 165, 200, 180], 0.7)
    assert h.matched_text == "Regional performance" and h.reading_order == 5 and h.confidence_level.value


def test_case_insensitive_and_original_case_kept():
    for q in ("revenue", "REVENUE", "ReVeNuE"):
        r = search_document(_doc(), q)
        assert [h.block_id for h in r.results] == ["B0001", "B0002", "B0003", "B0004"]
    assert search_document(_doc(), "revenue").results[2].matched_text == "REVENUE"


def test_multiple_matches_counted_and_in_reading_order():
    r = search_document(_doc(), "revenue")
    assert r.returned == 4 and [h.reading_order for h in r.results] == [1, 2, 3, 4]
    assert r.results[1].match_count == 2  # two matches inside one block; whitespace/newlines normalised
    assert [h.page for h in r.results] == [1, 1, 2, 2]


def test_partial_and_phrase_matching():
    assert [h.block_id for h in search_document(_doc(), "reven").results][0] == "B0001"
    assert search_document(_doc(), "total revenue").total_matches == 1
    assert search_document(_doc(), '"revenue rose"').total_matches == 1
    assert search_document(_doc(), "revenue north").total_matches == 0  # phrase must be contiguous


def test_no_matches_and_blank_query():
    r = search_document(_doc(), "zebra")
    assert r.total_matches == 0 and r.results == [] and "zebra" in r.message
    with pytest.raises(ValueError):
        build_pattern("   ")
    assert search_document(_doc(), "a.c*").total_matches == 0  # regex characters are literal


def test_table_cells_searchable_and_not_joined_across_cells():
    assert search_document(_doc(), "1,200").results[0].block_type.value == "table"
    assert search_document(_doc(), "Region Revenue").total_matches == 0  # adjacent cells are separate units


def test_ocr_block_searchable():
    h = search_document(_doc(), "scanned ocr").results[0]
    assert h.block_id == "B0006" and h.confidence == 0.61


def test_limit_truncates():
    r = search_document(_doc(), "revenue", limit=2)
    assert r.total_matches == 4 and r.returned == 2 and r.truncated


def _parse(pdf):
    with open(pdf, "rb") as fh:
        fid = client.post("/api/upload", files={"file": (pdf.name, fh, "application/pdf")}).json()["file_id"]
    client.post(f"/api/parse?file_id={fid}&wait=true")
    return fid


def test_api_search_real_digital_pdf(pdfs):
    fid = _parse(pdfs["digital"])
    res = client.post("/api/search", json={"document_id": fid, "query": "revenue"})
    assert res.status_code == 200
    body = res.json()
    assert body["total_matches"] >= 2
    types = {h["block_type"] for h in body["results"]}
    assert "table" in types and "paragraph" in types
    for h in body["results"]:
        assert h["page"] >= 1 and len(h["bbox"]) == 4 and 0 <= h["confidence"] <= 1 and h["reading_order"] >= 1
        assert h["provenance"]["page"] == h["page"] and h["matched_text"].lower() == "revenue"
    saved = json.loads(client.get(f"/api/result/{fid}").text)
    ids = {b["id"]: b for b in saved["blocks"]}
    h = body["results"][0]
    assert ids[h["block_id"]]["bbox"] == h["bbox"]  # same bbox as the canonical document


def test_api_search_ocr_and_table_in_scanned_pdf(pdfs):
    fid = _parse(pdfs["scanned"])
    body = client.post("/api/search", json={"document_id": fid, "query": "north"}).json()
    assert body["total_matches"] >= 1 and any(h["block_type"] == "table" for h in body["results"])
    body = client.post("/api/search", json={"document_id": fid, "query": "quick brown"}).json()
    assert body["total_matches"] >= 1 and body["results"][0]["provenance"]["extractor"].startswith("ocr")


def test_api_no_match_and_errors(pdfs):
    fid = _parse(pdfs["digital"])
    body = client.post("/api/search", json={"document_id": fid, "query": "qqqzzz"}).json()
    assert body["total_matches"] == 0 and body["results"] == [] and body["message"]
    assert client.post("/api/search", json={"document_id": fid, "query": "   "}).status_code == 422
    assert client.post("/api/search", json={"document_id": fid, "query": ""}).status_code == 422
    assert client.post("/api/search", json={"document_id": "../etc", "query": "x"}).status_code == 400
    assert client.post("/api/search", json={"document_id": "0" * 12, "query": "x"}).status_code == 404


def test_search_preserves_xlsx_cell_provenance():
    from app.models.block import Block
    doc = Document(document_id="x" * 12, filename="x.xlsx", format="xlsx", page_count=1, blocks=[
        Block(id="X1", type=BlockType.table, page=1, content={
            "cells": [{"row": 0, "col": 0, "text": "Revenue"}, {"row": 0, "col": 1, "text": "1350"}]
        }, meta={
            "cell_provenance": [
                {"worksheet": "Financials", "worksheet_index": 1, "cell": "F24", "row": 24, "column": 6, "column_letter": "F"},
                {"worksheet": "Financials", "worksheet_index": 1, "cell": "G24", "row": 24, "column": 7, "column_letter": "G"},
            ],
        })
    ])
    # Supply the same kind of base source produced by the XLSX handler.
    doc.blocks[0].provenance = __import__('app.models.block', fromlist=['Provenance']).Provenance(
        document=doc.document_id, page=1, bbox=None, sources=[{
            "page": 1, "bbox": None, "source_type": "xlsx", "worksheet": "Financials",
            "worksheet_index": 1, "range": "F24:G24"
        }]
    )
    hit = search_document(doc, "1350").results[0]
    assert hit.provenance.sources[0]["cell"] == "G24"
    assert hit.provenance.sources[0]["worksheet"] == "Financials"


def test_search_preserves_docx_table_cell_provenance():
    from app.models.block import Provenance
    doc = Document(document_id="d" * 12, filename="x.docx", format="docx", page_count=1, blocks=[
        Block(id="D1", type=BlockType.table, page=1, content={
            "cells": [{"row": 0, "col": 0, "text": "Column A"}, {"row": 0, "col": 1, "text": "Column B"}]
        }, meta={
            "cell_sources": [
                {"table_index": 2, "row": 0, "column": 0},
                {"table_index": 2, "row": 0, "column": 1},
            ],
        })
    ])
    doc.blocks[0].provenance = Provenance(document=doc.document_id, page=1, bbox=None, sources=[{
        "page": 1, "bbox": None, "source_type": "docx", "table_index": 2
    }])
    hit = search_document(doc, "Column B").results[0]
    assert hit.provenance.sources[0]["table_index"] == 2
    assert hit.provenance.sources[0]["row"] == 0
    assert hit.provenance.sources[0]["column"] == 1
