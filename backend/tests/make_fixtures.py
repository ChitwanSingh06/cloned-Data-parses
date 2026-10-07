"""Generate synthetic test PDFs (digital, two-column, multi-page table, scanned, mixed)."""
from pathlib import Path

import pymupdf
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import BaseDocTemplate, Frame, PageBreak, PageTemplate, Paragraph, Spacer, Table, TableStyle, FrameBreak, ListFlowable, ListItem

SS = getSampleStyleSheet()
LOREM = ("The quick brown fox jumps over the lazy dog while the committee reviews quarterly revenue, "
         "operating margins and the debt schedule in considerable detail. ") * 4


def _footer(canvas, doc):
    canvas.setFont("Helvetica", 8)
    canvas.drawString(72, 30, "Acme Corp Confidential")
    canvas.drawRightString(540, 30, f"Page {doc.page}")
    canvas.drawString(72, 765, "Annual Report 2025")


def digital_pdf(path: Path) -> Path:
    doc = BaseDocTemplate(str(path), pagesize=letter)
    doc.addPageTemplates([PageTemplate(id="p", frames=[Frame(72, 60, 468, 690)], onPage=_footer)])
    s = []
    s.append(Paragraph("1 Introduction", SS["Heading1"]))
    s.append(Paragraph(LOREM, SS["BodyText"]))
    s.append(Paragraph("1.1 Scope", SS["Heading2"]))
    s.append(Paragraph(LOREM, SS["BodyText"]))
    s.append(ListFlowable([ListItem(Paragraph("First bullet item", SS["BodyText"])), ListItem(Paragraph("Second bullet item", SS["BodyText"]))], bulletType="bullet"))
    s.append(Spacer(1, 12))
    data = [["Region", "FY2024", "", "FY2025", ""], ["", "Revenue", "Margin", "Revenue", "Margin"],
            ["North", "1,200", "12%", "1,350", "14%"], ["South", "980", "9%", "1,010", "10%"], ["East", "750", "7%", "820", "8%"]]
    t = Table(data)
    t.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.5, colors.black), ("SPAN", (1, 0), (2, 0)), ("SPAN", (3, 0), (4, 0)),
                           ("SPAN", (0, 0), (0, 1)), ("FONTNAME", (0, 0), (-1, 1), "Helvetica-Bold")]))
    s.append(t)
    s.append(Paragraph("Table 1: Regional performance", SS["BodyText"]))
    s.append(Paragraph(LOREM * 3, SS["BodyText"]))
    doc.build(s)
    return path


def twocol_pdf(path: Path) -> Path:
    doc = BaseDocTemplate(str(path), pagesize=letter)
    f1, f2 = Frame(60, 60, 230, 600, id="c1"), Frame(320, 60, 230, 600, id="c2")
    top = Frame(60, 670, 490, 80, id="top")
    doc.addPageTemplates([PageTemplate(id="two", frames=[top, f1, f2])])
    s = [Paragraph("A Two Column Study", SS["Title"]), FrameBreak()]
    s += [Paragraph(f"LEFTCOL paragraph {i}. " + LOREM[:150], SS["BodyText"]) for i in range(1, 4)]
    s += [FrameBreak()] + [Paragraph(f"RIGHTCOL paragraph {i}. " + LOREM[:150], SS["BodyText"]) for i in range(1, 4)]
    doc.build(s)
    return path


def multipage_table_pdf(path: Path) -> Path:
    doc = BaseDocTemplate(str(path), pagesize=letter)
    doc.addPageTemplates([PageTemplate(id="p", frames=[Frame(72, 60, 468, 690)])])
    rows = [["Item", "Qty", "Price"]] + [[f"Widget {i}", str(i), f"{i * 1.5:.2f}"] for i in range(1, 80)]
    t = Table(rows, repeatRows=1, colWidths=[200, 100, 100])
    t.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.5, colors.black), ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold")]))
    doc.build([Paragraph("Inventory", SS["Heading1"]), t])
    return path


def to_scanned(src: Path, dst: Path, pages: list[int] | None = None, dpi: int = 200) -> Path:
    """Rasterise pages of src into an image-only PDF (no text layer). Pages not listed stay digital."""
    s = pymupdf.open(str(src))
    out = pymupdf.open()
    for i, pg in enumerate(s):
        if pages is None or i in pages:
            pix = pg.get_pixmap(dpi=dpi)
            np_ = out.new_page(width=pg.rect.width, height=pg.rect.height)
            np_.insert_image(np_.rect, pixmap=pix)
        else:
            out.insert_pdf(s, from_page=i, to_page=i)
    out.save(str(dst))
    return dst
