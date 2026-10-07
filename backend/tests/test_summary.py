import json

from app.core.config import PROCESSED_DIR
from app.models.block import Block, BlockType, ConfidenceLevel, Status
from app.models.document import Document, Page
from app.pipeline.orchestrator import parse_pdf
from app.summary.summarizer import build_summary

P1 = ("Quarterly revenue increased across all regions during the year. Operating margins improved because costs "
      "were reduced in the logistics network. The committee reviewed the debt schedule in detail.")
P2 = "Revenue growth in the northern region was driven by new customer contracts signed in March."


def blk(i, t, content, page=1, conf=0.95, **kw):
    lvl = ConfidenceLevel.high if conf >= 0.85 else ConfidenceLevel.medium if conf >= 0.6 else ConfidenceLevel.low
    st = Status.review if conf < 0.6 else Status.ok
    return Block(id=f"B{i:04d}", type=BlockType(t), content=content, page=page, bbox=[0, 0, 10, 10], confidence=conf,
                 confidence_level=lvl, status=st, **kw)


def doc(blocks, pages=2, scanned=()):
    return Document(document_id="a" * 12, filename="report.pdf", page_count=pages, blocks=blocks,
                    pages=[Page(page_number=i, width=612, height=792, is_scanned=i in scanned) for i in range(1, pages + 1)])


def test_empty_document():
    s = build_summary(doc([], pages=0))
    assert s["status"] == "empty" and s["key_points"] == [] and s["sections"] == []
    assert "No content" in s["executive_summary"]
    assert s["statistics"]["pages"] == 0 and s["statistics"]["text_blocks"] == 0
    assert s["overview"]["title"] is None and s["overview"]["language"] is None


def test_document_with_headings_sections_and_title():
    d = doc([blk(1, "heading", "Annual Report 2025", level=1), blk(2, "paragraph", P1),
             blk(3, "heading", "Financial Results", page=2, level=2), blk(4, "heading", "Detailed Notes", page=2, level=3),
             blk(5, "paragraph", P2, page=2)])
    s = build_summary(d)
    assert s["overview"]["title"]["text"] == "Annual Report 2025" and s["overview"]["page_count"] == 2
    assert [x["text"] for x in s["sections"]] == ["Annual Report 2025", "Financial Results"]  # top two levels only
    assert s["sections"][1]["page"] == 2 and s["sections"][1]["block_id"] == "B0003"
    assert "Annual Report 2025" in s["executive_summary"] and "Financial Results" in s["executive_summary"]


def test_normal_text_sentences_are_verbatim_from_blocks():
    d = doc([blk(1, "paragraph", P1), blk(2, "paragraph", P2, page=2)])
    s = build_summary(d)
    assert s["status"] == "ok" and s["executive_sources"]
    source_text = " ".join([P1, P2])
    for src in s["executive_sources"] + [k for k in s["key_points"] if k["kind"] == "sentence"]:
        assert src["text"] in source_text  # nothing invented
        assert src["block_id"] in ("B0001", "B0002") and src["uncertain"] is False
    assert s["overview"]["title"] is None  # no heading, no invented title
    assert s["overview"]["document_type"] is None and s["overview"]["language"] is None


def test_deterministic():
    d = doc([blk(1, "paragraph", P1), blk(2, "paragraph", P2)])
    assert build_summary(d) == build_summary(d)


def test_statistics_counts():
    d = doc([blk(1, "heading", "Title", level=1), blk(2, "paragraph", P1), blk(3, "list", {"ordered": False, "items": ["one two three", "four"]}),
             blk(4, "table", {"n_rows": 3, "n_cols": 2, "headers": [["Region", "Revenue"]]}), blk(5, "figure", ""),
             blk(6, "equation", {"raw_text": "E=mc2", "latex": None}, conf=0.4), blk(7, "caption", "Table 1: Results", conf=0.7)])
    st = build_summary(d)["statistics"]
    assert (st["pages"], st["text_blocks"], st["tables"], st["figures"], st["equations"]) == (2, 4, 1, 1, 1)
    assert st["low_confidence_blocks"] == 1 and st["review_required_blocks"] == 1 and st["total_blocks"] == 7
    assert st["words"] > 10


def test_low_confidence_content_excluded_when_reliable_content_exists():
    bad = "The secret code name of the project is Falcon and it was approved by the board."
    d = doc([blk(1, "paragraph", P1), blk(2, "paragraph", bad, conf=0.3), blk(3, "heading", "Shaky Heading", level=1, conf=0.4)])
    s = build_summary(d)
    assert "Falcon" not in s["executive_summary"] and all("Falcon" not in k["text"] for k in s["key_points"])
    assert s["warnings"] and "low-confidence" in s["warnings"][0]
    assert s["sections"][0]["uncertain"] is True  # shown, but flagged
    assert "Shaky Heading" not in s["executive_summary"]  # uncertain title/sections never stated as fact


def test_only_low_confidence_content_is_flagged_uncertain():
    d = doc([blk(1, "paragraph", P1, conf=0.3)])
    s = build_summary(d)
    assert s["status"] == "uncertain" and s["executive_sources"] and all(x["uncertain"] for x in s["executive_sources"])
    assert "low confidence" in s["warnings"][0] and "may be inaccurate" in s["warnings"][0]


def test_table_point_and_source_kind():
    d = doc([blk(1, "table", {"n_rows": 4, "n_cols": 3, "headers": [["Region", "Revenue"]]}, meta={"caption": "Table 1: Regional performance"})],
            scanned={2})
    s = build_summary(d)
    pts = [k for k in s["key_points"] if k["kind"] == "table"]
    assert pts and "4 rows x 3 columns" in pts[0]["text"] and "Region" in pts[0]["text"]
    assert s["overview"]["source_kind"] == "mixed"


def test_summary_in_parsed_document_and_saved_json(parsed):
    d = parsed["digital"]
    assert d.summary["method"] == "extractive-local" and d.summary["statistics"]["pages"] == d.page_count
    assert d.summary["statistics"]["tables"] == sum(b.type.value == "table" for b in d.blocks)
    js = json.loads((PROCESSED_DIR / d.document_id / "document.json").read_text(encoding="utf-8"))
    assert js["summary"]["overview"]["page_count"] == d.page_count and js["summary"]["executive_summary"]
    assert any(s["text"] for s in js["summary"]["sections"])
    ids = {b["id"] for b in js["blocks"]}
    assert all(k["block_id"] in ids for k in js["summary"]["key_points"])


def test_failed_document_still_has_a_summary(pdfs):
    d = parse_pdf(str(pdfs["corrupt"]))
    assert d.summary["status"] == "empty"


def test_summary_returned_by_api(pdfs):
    from fastapi.testclient import TestClient
    from app.main import app
    c = TestClient(app)
    with open(pdfs["twocol"], "rb") as fh:
        fid = c.post("/api/upload", files={"file": ("t.pdf", fh, "application/pdf")}).json()["file_id"]
    c.post(f"/api/parse?file_id={fid}&wait=true")
    res = c.get(f"/api/result/{fid}").json()
    assert res["summary"]["statistics"]["pages"] == res["page_count"] and res["summary"]["method"] == "extractive-local"


def test_no_sentences_is_not_reported_as_uncertain():
    s = build_summary(doc([blk(1, "heading", "Only A Heading", level=1)]))
    assert s["status"] == "ok" and s["warnings"] == [] and "No complete sentences" in s["executive_summary"]


def test_unterminated_final_sentence_accepted_but_short_fragments_not():
    s = build_summary(doc([blk(1, "paragraph", "Short. The committee reviews quarterly revenue and margins in considerable detail and then")]))
    assert s["executive_sources"] and s["executive_sources"][0]["text"].startswith("The committee")
    assert build_summary(doc([blk(1, "paragraph", "Page 4 of 9")]))["executive_sources"] == []
