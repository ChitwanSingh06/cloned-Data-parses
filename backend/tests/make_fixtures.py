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


def handwriting_image(width: int = 1400, lines: int = 3, seed: int = 7):
    """Synthetic 'handwriting': wobbly pen strokes with varying width and a drifting baseline (no real glyphs)."""
    import random
    from PIL import Image, ImageDraw
    rnd = random.Random(seed)
    img = Image.new("L", (width, 150 * lines + 100), 255)
    d = ImageDraw.Draw(img)
    for li in range(lines):
        base = 150 + li * 150
        x = 90.0
        while x < width - 140:
            h = rnd.uniform(30, 75)
            drift = rnd.uniform(-14, 14)
            pts = [(x + rnd.uniform(-5, 5), base + drift), (x + 10 + rnd.uniform(-4, 4), base - h + drift * 0.5),
                   (x + 22 + rnd.uniform(-4, 4), base - h * rnd.uniform(0.2, 0.9) + drift), (x + 30, base + drift + rnd.uniform(-6, 6))]
            d.line(pts, fill=0, width=rnd.randint(2, 7), joint="curve")
            x += rnd.uniform(24, 40) if rnd.random() > 0.12 else 70
    return img


def image_pdf(img, path: Path) -> Path:
    import io
    doc = pymupdf.open()
    page = doc.new_page(width=img.width * 72 / 200, height=img.height * 72 / 200)
    buf = io.BytesIO(); img.save(buf, format="PNG")
    page.insert_image(page.rect, stream=buf.getvalue())
    doc.save(str(path))
    return path


def _tick_label(page, text, x_right, y_center, size=8):
    w = pymupdf.get_text_length(text, fontsize=size)
    page.insert_text((x_right - w, y_center + size * 0.35), text, fontsize=size)


def chart_pdf(path: Path, kind: str = "bar", ticks: bool = True, data=None) -> Path:
    """Vector chart drawn with PyMuPDF primitives (axes, ticks, bars/lines/wedges/markers + real text labels)."""
    import math
    doc = pymupdf.open()
    pg = doc.new_page()
    pg.insert_text((72, 80), "This paragraph introduces the quarterly results discussed in the chart that follows below.", fontsize=11)
    L, R, T, B = 130.0, 430.0, 220.0, 480.0           # plot area (pt, y down)
    sh = pg.new_shape()
    top = {"bar": 50, "line": 50, "histogram": 40, "scatter": 10, "pie": 0}.get(kind, 50)
    ymap = lambda v: B - v * (B - T) / top
    if kind != "pie":
        sh.draw_line((L, T), (L, B)); sh.draw_line((L, B), (R, B)); sh.finish(color=(0, 0, 0), width=1, closePath=False)
        for v in range(0, top + 1, 10 if top >= 40 else 2):
            sh.draw_line((L - 4, ymap(v)), (L, ymap(v))); sh.finish(color=(0, 0, 0), width=0.5)
            if ticks:
                _tick_label(pg, str(v), L - 6, ymap(v))
    cats = ["Q1", "Q2", "Q3", "Q4"]
    if kind == "bar":
        data = data or [12, 30, 21, 45]
        step = (R - L) / len(data)
        for i, v in enumerate(data):
            x0 = L + i * step + step * 0.2
            sh.draw_rect(pymupdf.Rect(x0, ymap(v), x0 + step * 0.6, B)); sh.finish(fill=(0.2, 0.4, 0.8), color=None)
            w = pymupdf.get_text_length(cats[i], fontsize=9)
            pg.insert_text((x0 + step * 0.3 - w / 2, B + 14), cats[i], fontsize=9)
    elif kind == "histogram":
        data = data or [5, 12, 30, 22, 8]
        step = (R - L) / len(data)
        for i, v in enumerate(data):
            sh.draw_rect(pymupdf.Rect(L + i * step, ymap(v), L + (i + 1) * step, B)); sh.finish(fill=(0.8, 0.4, 0.2), color=(0, 0, 0), width=0.5)
        for i in range(len(data) + 1):
            w = pymupdf.get_text_length(str(i * 10), fontsize=9)
            pg.insert_text((L + i * step - w / 2, B + 14), str(i * 10), fontsize=9)
    elif kind == "line":
        data = data or [10, 25, 18, 40]
        step = (R - L) / len(data)
        pts = [(L + step * (i + 0.5), ymap(v)) for i, v in enumerate(data)]
        sh.draw_polyline(pts); sh.finish(color=(0.8, 0.1, 0.1), width=1.5, closePath=False)
        for i, c in enumerate(cats):
            w = pymupdf.get_text_length(c, fontsize=9)
            pg.insert_text((pts[i][0] - w / 2, B + 14), c, fontsize=9)
    elif kind == "scatter":
        data = data or [(1, 2), (2, 3.5), (3, 4), (4, 6.5), (5, 7), (6, 9)]
        for x, y in data:
            px = L + x * (R - L) / 7
            sh.draw_circle((px, ymap(y)), 3); sh.finish(fill=(0.1, 0.5, 0.2), color=None)
        for x in range(0, 8, 1):
            w = pymupdf.get_text_length(str(x), fontsize=9)
            px = L + x * (R - L) / 7
            sh.draw_line((px, B), (px, B + 3)); sh.finish(color=(0, 0, 0), width=0.5)
            pg.insert_text((px - w / 2, B + 14), str(x), fontsize=9)
    elif kind == "pie":
        data = data or [("Cash", 50), ("Bonds", 30), ("Stocks", 20)]
        cx, cy, r = 280.0, 340.0, 100.0
        ang = 0.0
        cols = [(0.9, 0.3, 0.3), (0.3, 0.7, 0.3), (0.3, 0.3, 0.9)]
        for i, (name, share) in enumerate(data):
            sweep = 360.0 * share / 100.0
            a0 = math.radians(ang)
            sh.draw_sector((cx, cy), (cx + r * math.cos(a0), cy + r * math.sin(a0)), -sweep, fullSector=True)  # clockwise on screen
            sh.finish(fill=cols[i], color=(1, 1, 1), width=0.5)
            mid = math.radians(ang + sweep / 2)
            lx, ly = cx + (r + 24) * math.cos(mid), cy + (r + 24) * math.sin(mid)
            ang += sweep
            pg.insert_text((lx - 12, ly), name, fontsize=9)
    sh.commit()
    if kind != "pie":
        w = pymupdf.get_text_length("Quarterly Revenue", fontsize=12)
        pg.insert_text(((L + R) / 2 - w / 2, T - 14), "Quarterly Revenue", fontsize=12)
        pg.insert_text((L - 32, (T + B) / 2 + 40), "Revenue (USD M)", fontsize=9, rotate=90)
        w = pymupdf.get_text_length("Quarter", fontsize=9)
        pg.insert_text(((L + R) / 2 - w / 2, B + 30), "Quarter", fontsize=9)
        pg.insert_text((L, B + 52), "Figure 1: Quarterly revenue by quarter", fontsize=10)
    else:
        pg.insert_text((200, 480), "Figure 1: Portfolio mix", fontsize=10)
    pg.insert_text((72, B + 90), "Closing paragraph that discusses the figure above and what it means for the year ahead overall.", fontsize=11)
    doc.save(str(path))
    return path


def unicode_font() -> str | None:
    """A TTF with math/Greek glyphs on this machine (Linux DejaVu, Windows Segoe UI Symbol/Arial), else None."""
    import os
    cands = ["/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", r"C:\Windows\Fonts\seguisym.ttf", r"C:\Windows\Fonts\arial.ttf",
             r"C:\Windows\Fonts\segoeui.ttf", "/System/Library/Fonts/Supplemental/Arial Unicode.ttf"]
    return next((c for c in cands if os.path.exists(c)), None)


def equation_pdf(path: Path, items: list[tuple], rules: list[tuple] = ()) -> Path:
    """items: (x, y_baseline, text, size[, 'uni']). All items go into ONE text object so geometry is the only
    evidence of scripts. rules: (x0, x1, y) horizontal lines. Page also carries a 11pt prose paragraph."""
    doc = pymupdf.open()
    pg = doc.new_page()
    pg.insert_text((72, 80), "The relationship between present and future value is shown in the following expression.", fontsize=11)
    ff = unicode_font()
    tw = pymupdf.TextWriter(pg.rect)
    uni = pymupdf.Font(fontfile=ff) if ff else None
    helv = pymupdf.Font("helv")
    for it in items:
        x, y, text, size = it[:4]
        tw.append((x, y), text, font=uni if (len(it) > 4 and it[4] == "uni") else helv, fontsize=size)
    tw.write_text(pg)
    for x0, x1, y in rules:
        pg.draw_line((x0, y), (x1, y), color=(0, 0, 0), width=0.8)
    doc.save(str(path))
    return path


def adv(text: str, size: float, uni: bool = False) -> float:
    """Advance width of text in the same font equation_pdf uses (so scripts can be placed exactly)."""
    ff = unicode_font()
    font = pymupdf.Font(fontfile=ff) if (uni and ff) else pymupdf.Font("helv")
    return font.text_length(text, fontsize=size)
