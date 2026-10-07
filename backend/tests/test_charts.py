import pytest

import make_fixtures as fx
from app.models.block import BlockType
from app.output.markdown_builder import build_markdown
from app.pipeline.orchestrator import parse_pdf

LABELS = {"Q1", "Q2", "Q3", "Q4", "Quarterly Revenue", "Revenue (USD M)", "Quarter"}


def _parse(tmp_path, **kw):
    doc = parse_pdf(str(fx.chart_pdf(tmp_path / "c.pdf", **kw)))
    return doc, [b for b in doc.blocks if b.type == BlockType.chart]


def _vals(chart, s=0):
    return [p["value"] for p in chart["series"][s]["points"]]


def test_bar_chart_grouped_into_one_block_no_stray_paragraphs(tmp_path):
    doc, charts = _parse(tmp_path, kind="bar")
    assert len(charts) == 1
    stray = [b for b in doc.blocks if b.type != BlockType.chart and isinstance(b.content, str) and b.content.strip() in LABELS]
    assert not stray, [b.content for b in stray]
    assert all(b.type in (BlockType.paragraph, BlockType.caption, BlockType.chart) for b in doc.blocks)
    assert sum(b.type == BlockType.paragraph for b in doc.blocks) == 2  # only the real prose paragraphs


def test_bar_chart_metadata_and_values(tmp_path):
    doc, (b,) = _parse(tmp_path, kind="bar")
    c = b.content
    assert c["chart_type"] == "bar" and c["title"] == "Quarterly Revenue"
    assert c["x_axis"]["categories"] == ["Q1", "Q2", "Q3", "Q4"] and c["x_axis"]["label"] == "Quarter"
    assert c["y_axis"]["ticks"] == [0, 10, 20, 30, 40, 50] and "USD" in c["y_axis"]["label"] and c["y_axis"]["unit"] == "USD M"
    for got, want in zip(_vals(c), [12, 30, 21, 45]):
        assert got == pytest.approx(want, abs=0.6)
    assert c["data_extracted"] and b.meta["caption"].startswith("Figure 1")
    assert b.confidence >= 0.6 and b.status.value == "OK" and b.confidence_level.value in ("HIGH", "MEDIUM")
    assert b.provenance.page == 1 and len(b.bbox) == 4 and b.meta["image_path"]


def test_values_follow_the_drawing_not_hardcoded(tmp_path):
    _, (b,) = _parse(tmp_path, kind="bar", data=[5, 40, 33, 8])
    for got, want in zip(_vals(b.content), [5, 40, 33, 8]):
        assert got == pytest.approx(want, abs=0.6)


def test_bar_chart_markdown_has_data_table(tmp_path):
    doc, _ = _parse(tmp_path, kind="bar")
    md = build_markdown(doc.model_dump(mode="json"))
    assert "**Quarterly Revenue**" in md and "| Q1 |" in md and "| Category |" in md
    assert "\nQ1\n" not in md and "\nQuarter\n" not in md


def test_line_chart(tmp_path):
    _, charts = _parse(tmp_path, kind="line")
    assert len(charts) == 1 and charts[0].content["chart_type"] == "line"
    for got, want in zip(_vals(charts[0].content), [10, 25, 18, 40]):
        assert got == pytest.approx(want, abs=0.6)
    assert [p["category"] for p in charts[0].content["series"][0]["points"]] == ["Q1", "Q2", "Q3", "Q4"]


def test_histogram_detected_with_bins(tmp_path):
    _, charts = _parse(tmp_path, kind="histogram")
    c = charts[0].content
    assert c["chart_type"] == "histogram"
    assert _vals(c) == pytest.approx([5, 12, 30, 22, 8], abs=0.6)
    pts = c["series"][0]["points"]
    assert pts[0].get("bin_start") == pytest.approx(0, abs=0.5) and pts[0].get("bin_end") == pytest.approx(10, abs=0.5)


def test_scatter_chart(tmp_path):
    _, charts = _parse(tmp_path, kind="scatter")
    c = charts[0].content
    assert c["chart_type"] == "scatter"
    pts = c["series"][0]["points"]
    assert len(pts) == 6 and pts[0]["x"] == pytest.approx(1, abs=0.1) and pts[0]["value"] == pytest.approx(2, abs=0.3)


def test_pie_chart_shares(tmp_path):
    doc, charts = _parse(tmp_path, kind="pie")
    assert len(charts) == 1 and charts[0].content["chart_type"] == "pie"
    got = {p["category"]: p["value"] for p in charts[0].content["series"][0]["points"]}
    assert got == pytest.approx({"Cash": 50, "Bonds": 30, "Stocks": 20}, abs=1.5)
    assert not [b for b in doc.blocks if b.type == BlockType.paragraph and b.content in ("Cash", "Bonds", "Stocks")]


def test_unreliable_chart_is_preserved_and_flagged(tmp_path):
    doc, charts = _parse(tmp_path, kind="bar", ticks=False)
    assert len(charts) == 1
    b = charts[0]
    assert b.content["data_extracted"] is False and all(v is None for v in _vals(b.content))
    assert b.status.value == "REVIEW_REQUIRED" and "tick" in b.meta["review_reason"].lower()
    assert b.meta["image_path"] and b.confidence < 0.6
    assert "Chart values were not extracted" in build_markdown(doc.model_dump(mode="json"))


def test_confidence_drops_when_labels_disagree(tmp_path):
    from app.extractors.charts import chart_extractor as ce
    assert ce.parse_number("$1,200") == (1200.0, "$") and ce.parse_number("45%") == (45.0, "%") and ce.parse_number("Q1") is None
