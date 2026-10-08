"""Semantic table validation: totals must add up. Pure additions; no existing behaviour is changed."""
from decimal import Decimal

import pytest
from docx import Document as DocxDocument
from openpyxl import Workbook
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle

from app.formats.docx_handler import parse_docx
from app.formats.xlsx_handler import parse_xlsx
from app.models.block import Block, BlockType, Status
from app.models.document import Document
from app.models.table import TableData
from app.output.markdown_builder import build_markdown
from app.pipeline.confidence import add_confidence, score
from app.pipeline.orchestrator import parse_pdf
from app.pipeline.table_consistency import (ERROR_CODE, add_table_consistency, check_table, format_warning,
                                            parse_number)

SIGNALS = {"extraction": 0.95, "structure": 0.95}


def _content(headers, rows):
    return TableData(n_rows=len(headers) + len(rows), n_cols=max(len(r) for r in headers + rows),
                     header_rows=len(headers), headers=headers, rows=rows).model_dump()


def _doc(headers, rows, **block_kwargs):
    block = Block(id="B1", type=BlockType.table, content=_content(headers, rows), page=1, signals=dict(SIGNALS), **block_kwargs)
    return Document(document_id="d" * 12, filename="t.pdf", blocks=[block])


def _check(headers, rows):
    return check_table(_content(headers, rows))


# ---------------------------------------------------------------- number parsing
@pytest.mark.parametrize("raw,value,decimals", [
    ("40", "40", 0), ("1,234.5", "1234.5", 1), ("12,34,567", "1234567", 0), ("1.234,56", "1234.56", 2),
    ("(95)", "-95", 0), ("-5", "-5", 0), ("\u22125", "-5", 0), ("95-", "-95", 0), ("95*", "95", 0),
    ("$1,200.50", "1200.50", 2), ("12,5", "12.5", 1), ("\u20b9 1,000", "1000", 0), ("Rs. 2,500", "2500", 0), ("1 234", "1234", 0),
    (7, "7", 0), (2.5, "2.5", 1), (Decimal("3.10"), "3.10", 2),
])
def test_parse_number_accepts(raw, value, decimals):
    n = parse_number(raw)
    assert n is not None and n.value == Decimal(value) and n.decimals == decimals


@pytest.mark.parametrize("raw", ["1.2M", "12 kg", "abc", "", "-", "\u2014", "n/a", None, True, "1.2.3", "12,5,5", "1,2345"])
def test_parse_number_rejects(raw):
    assert parse_number(raw) is None


def test_percent_is_flagged_not_summed():
    n = parse_number("12.5%")
    assert n is not None and n.percent and n.value == Decimal("12.5")


# ---------------------------------------------------------------- the requested behaviour
def test_requested_example_mismatch():
    r = _check([["Year", "Revenue"]], [["2023", "40"], ["2024", "50"], ["Total", "95"]])
    assert r["checks_run"] == 1 and r["checks_passed"] == 0 and len(r["warnings"]) == 1
    w = r["warnings"][0]
    assert (w["kind"], w["expected"], w["extracted"], w["difference"]) == ("column_total", "90", "95", "+5")
    assert w["column"] == "Revenue" and w["label"] == "Total"
    assert format_warning(w).splitlines()[:3] == ["\u26a0\ufe0f TABLE CONSISTENCY WARNING", "Expected total: 90", "Extracted total: 95"]


def test_requested_example_consistent():
    r = _check([["Year", "Revenue"]], [["2023", "40"], ["2024", "50"], ["Total", "90"]])
    assert r["checks_run"] == 1 and r["checks_passed"] == 1 and r["warnings"] == []


def test_headerless_table_uses_text_first_row_as_header():
    r = _check([], [["Year", "Revenue"], ["2023", "40"], ["2024", "50"], ["Total", "95"]])
    assert [w["expected"] for w in r["warnings"]] == ["90"] and r["warnings"][0]["column"] == "Revenue"


# ---------------------------------------------------------------- row totals, subtotals, formats
def test_row_total_mismatch_and_match():
    r = _check([["Region", "Q1", "Q2", "Total"]], [["North", "10", "20", "30"], ["South", "5", "5", "11"]])
    assert r["checks_run"] == 2 and r["checks_passed"] == 1
    w = r["warnings"][0]
    assert (w["kind"], w["label"], w["expected"], w["extracted"]) == ("row_total", "South", "10", "11")


def test_row_total_ignores_unlabelled_leading_index_column():
    r = _check([["Region", "Q1", "Q2", "Total"]], [["N1", "100", "20", "30"], ["N2", "7", "5", "12"]])  # 100 is an index-like extra
    assert r["warnings"] == [] or all(w["label"] != "N2" for w in r["warnings"])


def test_subtotals_and_grand_total():
    rows = [["A", "10"], ["B", "20"], ["Subtotal", "30"], ["C", "5"], ["D", "5"], ["Subtotal", "10"]]
    ok = _check([["Item", "Amt"]], rows + [["Grand Total", "40"]])
    assert ok["checks_run"] == 3 and ok["warnings"] == []
    bad = _check([["Item", "Amt"]], rows + [["Grand Total", "45"]])
    assert [(w["label"], w["expected"], w["extracted"]) for w in bad["warnings"]] == [("Grand Total", "40", "45")]
    bad_sub = _check([["Item", "Amt"]], [["A", "10"], ["B", "20"], ["Sub-total", "31"]])
    assert bad_sub["warnings"][0]["expected"] == "30"


def test_income_statement_sections_each_checked_against_their_own_rows():
    rows = [["Sales", "100"], ["Other", "20"], ["Total revenue", "120"], ["COGS", "50"], ["Opex", "30"], ["Total expenses", "80"]]
    assert _check([["Line", "Amt"]], rows)["warnings"] == []
    rows[-1] = ["Total expenses", "85"]
    assert [(w["label"], w["expected"]) for w in _check([["Line", "Amt"]], rows)["warnings"]] == [("Total expenses", "80")]


def test_money_formats_negatives_and_message_formatting():
    ok = _check([["Item", "Amt"]], [["A", "$1,200.50"], ["B", "(200.25)"], ["Total", "$1,000.25"]])
    assert ok["checks_run"] == 1 and ok["warnings"] == []
    bad = _check([["Item", "Amt"]], [["A", "$1,200.50"], ["B", "(200.25)"], ["Total", "$1,100.25"]])
    w = bad["warnings"][0]
    assert (w["expected"], w["extracted"], w["difference"]) == ("1,000.25", "1,100.25", "+100.00")


@pytest.mark.parametrize("label", ["Total", "TOTAL", "Totals", "Grand total", "Net Total", "Subtotal", "Total:", "Sum", "\u0915\u0941\u0932", "\u0bae\u0bca\u0ba4\u0bcd\u0ba4\u0bae\u0bcd"])
def test_total_label_variants_including_hindi_and_tamil(label):
    r = _check([["Item", "Amt"]], [["A", "40"], ["B", "50"], [label, "95"]])
    assert len(r["warnings"]) == 1 and r["warnings"][0]["expected"] == "90"


@pytest.mark.parametrize("label", ["Totally unrelated", "Sum insured", "Subject", "Summary"])
def test_non_total_labels_are_not_treated_as_totals(label):
    assert _check([["Item", "Amt"]], [["A", "40"], ["B", "50"], [label, "95"]])["checks_run"] == 0


# ---------------------------------------------------------------- false-positive guards
def test_percent_year_serial_and_average_columns_are_never_flagged():
    r = _check([["No", "Year", "Share", "Average", "Revenue"]],
               [["1", "2023", "60%", "10", "40"], ["2", "2024", "30%", "20", "50"], ["Total", "4047", "90%", "35", "90"]])
    assert r["warnings"] == [] and r["checks_run"] == 1  # only Revenue is verifiable


def test_nothing_to_verify_with_fewer_than_two_numbers():
    assert _check([["Item", "Amt"]], [["A", "10"], ["Total", "10"]])["checks_run"] == 0
    assert _check([["Metric", "Value"]], [["Total employees", "120"], ["Total sites", "5"]])["checks_run"] == 0


def test_cells_with_units_or_text_are_skipped_not_guessed():
    assert _check([["Item", "Weight"]], [["A", "40 kg"], ["B", "50 kg"], ["Total", "95 kg"]])["checks_run"] == 0
    assert _check([["Item", "Amt"]], [["A", "40"], ["B", "50"], ["Total", "n/a"]])["checks_run"] == 0


def test_blank_cells_and_ragged_rows_do_not_crash():
    r = _check([["Item", "Q1", "Q2"]], [["A", "10"], ["B", "", "5"], ["C", "10", "5"], ["Total", "20"]])
    assert r["checks_run"] == 1 and r["warnings"] == []


# ---------------------------------------------------------------- tolerance
def test_rounding_is_forgiven_only_when_plausible(monkeypatch):
    big = [["A", "1,000"], ["B", "2,000"], ["C", "3,000"], ["Total", "6,001"]]
    small = [["A", "10"], ["B", "20"], ["Total", "31"]]
    assert _check([["Item", "Amt"]], big)["warnings"] == []
    assert len(_check([["Item", "Amt"]], small)["warnings"]) == 1
    monkeypatch.setenv("PARSE_TABLE_CONSISTENCY_TOLERANCE", "strict")
    assert len(_check([["Item", "Amt"]], big)["warnings"]) == 1


def test_decimal_arithmetic_is_exact():
    r = _check([["Item", "Amt"]], [["A", "0.1"], ["B", "0.2"], ["Total", "0.3"]])
    assert r["warnings"] == [] and r["checks_passed"] == 1


# ---------------------------------------------------------------- pipeline stage
def test_stage_marks_review_adds_structured_warning_and_keeps_confidence():
    doc = _doc([["Year", "Revenue"]], [["2023", "40"], ["2024", "50"], ["Total", "95"]])
    add_confidence(doc)  # the existing stage; it now also runs the consistency check
    b = doc.blocks[0]
    assert b.confidence == score(SIGNALS)  # confidence scoring untouched
    assert b.status == Status.review
    assert b.meta["table_consistency"]["status"] == "WARNING"
    assert b.meta["review_reason"].startswith("TABLE CONSISTENCY WARNING:") and "expected total 90, extracted total 95" in b.meta["review_reason"]
    errs = [e for e in doc.errors if e["code"] == ERROR_CODE]
    assert len(errs) == 1 and errs[0]["severity"] == "warning" and errs[0]["block_id"] == "B1" and errs[0]["page"] == 1
    assert "TABLE CONSISTENCY WARNING" in build_markdown(doc.model_dump(mode="json"))


def test_stage_passing_table_is_recorded_but_not_flagged():
    doc = _doc([["Year", "Revenue"]], [["2023", "40"], ["2024", "50"], ["Total", "90"]])
    add_confidence(doc)
    b = doc.blocks[0]
    assert b.status == Status.ok and b.meta["table_consistency"]["status"] == "PASS"
    assert not [e for e in doc.errors if e["code"] == ERROR_CODE]


def test_stage_leaves_tables_without_totals_exactly_unchanged():
    doc = _doc([["Item", "Qty"]], [["Widget 1", "1"], ["Widget 2", "2"], ["Widget 3", "3"]])
    before = doc.blocks[0].model_dump()
    add_table_consistency(doc)
    assert doc.blocks[0].model_dump() == before and doc.errors == []


def test_stage_appends_to_an_existing_review_reason():
    doc = _doc([["Item", "Amt"]], [["A", "40"], ["B", "50"], ["Total", "95"]], meta={"review_reason": "Low confidence"})
    add_table_consistency(doc)
    assert doc.blocks[0].meta["review_reason"].startswith("Low confidence; TABLE CONSISTENCY WARNING:")


def test_stage_can_be_switched_off(monkeypatch):
    monkeypatch.setenv("PARSE_TABLE_CONSISTENCY", "off")
    doc = _doc([["Item", "Amt"]], [["A", "40"], ["B", "50"], ["Total", "95"]])
    add_confidence(doc)
    assert doc.blocks[0].status == Status.ok and "table_consistency" not in doc.blocks[0].meta and not doc.errors


def test_stage_never_raises_on_malformed_tables():
    weird = [Block(id="W1", type=BlockType.table, content="not a dict", page=1),
             Block(id="W2", type=BlockType.table, content={}, page=1),
             Block(id="W3", type=BlockType.table, content={"headers": None, "rows": [None, 5, ["Total"]], "n_cols": "x"}, page=1),
             Block(id="W4", type=BlockType.table, content={"headers": [["A"]], "rows": [[object(), None], ["Total", float("nan")]]}, page=1)]
    doc = Document(document_id="d" * 12, filename="t.pdf", blocks=weird)
    add_table_consistency(doc)  # must not raise
    assert doc.errors == []


# ---------------------------------------------------------------- real files, end to end
def test_docx_end_to_end(tmp_path):
    def build(total, name):
        d = DocxDocument()
        t = d.add_table(rows=4, cols=2)
        for r, (a, b) in enumerate([("Year", "Revenue"), ("2023", "40"), ("2024", "50"), ("Total", total)]):
            t.cell(r, 0).text, t.cell(r, 1).text = a, b
        p = tmp_path / name
        d.save(p)
        return parse_docx(str(p), document_id="a" * 12, out_root=tmp_path)

    bad, good = build("95", "bad.docx"), build("90", "good.docx")
    tb = next(b for b in bad.blocks if b.type == BlockType.table)
    assert tb.status == Status.review and tb.meta["table_consistency"]["warnings"][0]["expected"] == "90"
    assert bad.status == "SUCCESS" and any(e["code"] == ERROR_CODE for e in bad.errors)  # a warning, never a failure
    assert bad.stats["review_required"] >= 1 and bad.stats["warnings"] >= 1
    assert "TABLE CONSISTENCY WARNING" in build_markdown(bad.model_dump(mode="json"))
    tg = next(b for b in good.blocks if b.type == BlockType.table)
    assert tg.meta["table_consistency"]["status"] == "PASS" and not any(e["code"] == ERROR_CODE for e in good.errors)


def test_xlsx_end_to_end(tmp_path):
    wb = Workbook()
    ws = wb.active
    for row in [("Year", "Revenue"), (2023, 40), (2024, 50), ("Total", 95)]:
        ws.append(row)
    p = tmp_path / "t.xlsx"
    wb.save(p)
    doc = parse_xlsx(str(p), document_id="b" * 12, out_root=tmp_path)
    t = next(b for b in doc.blocks if b.type == BlockType.table)
    w = t.meta["table_consistency"]["warnings"]
    assert t.status == Status.review and (w[0]["expected"], w[0]["extracted"]) == ("90", "95")


def test_pdf_end_to_end(tmp_path):
    def build(total, name):
        p = tmp_path / name
        rows = [["Year", "Revenue"], ["2023", "40"], ["2024", "50"], ["Total", total]]
        t = Table(rows, colWidths=[150, 150])
        t.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.5, colors.black)]))
        SimpleDocTemplate(str(p), pagesize=letter).build([t])
        return parse_pdf(str(p), document_id=name[:3] * 4, out_root=tmp_path)

    bad, good = build("95", "bad.pdf"), build("90", "goo.pdf")
    tb = next(b for b in bad.blocks if b.type == BlockType.table)
    assert tb.status == Status.review and tb.meta["table_consistency"]["warnings"][0]["expected"] == "90"
    assert bad.status == "SUCCESS" and any(e["code"] == ERROR_CODE for e in bad.errors)
    tg = next(b for b in good.blocks if b.type == BlockType.table)
    assert tg.meta["table_consistency"]["status"] == "PASS" and not any(e["code"] == ERROR_CODE for e in good.errors)
