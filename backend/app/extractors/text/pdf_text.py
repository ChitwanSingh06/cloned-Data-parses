"""Digital text extraction (PyMuPDF) + lightweight semantic classification."""
import re
from collections import Counter
from typing import Optional

from app.utils.bbox import union

BULLET_RE = re.compile(r"^\s*(?P<m>[•●▪◦‣·∙■□\-–—*]|\(?\d{1,3}[.)]|\(?[a-zA-Z]\)|\(?[ivxlIVXL]{1,5}[.)])\s+(?P<rest>\S.*)", re.S)
CAPTION_RE = re.compile(r"^\s*(Figure|Fig\.?|Table|Chart|Graph|Exhibit|Diagram|Plate)\s*[\dA-Z][\w.\-]*\s*[.:–—\-|]?\s", re.I)
NUMBERED_HEADING_RE = re.compile(r"^\s*(\d+(\.\d+){0,4}|[A-Z]|[IVX]+)[.)]?\s+[A-Z][^.]{2,}$")
FOOTNOTE_RE = re.compile(r"^\s*(\d{1,3}|[*†‡§¹²³])\s*[.)]?\s*\S")
EQNUM_RE = re.compile(r"\(\s*\d{1,3}(\.\d+)?\s*\)\s*$")
MATH_FONTS = ("cmmi", "cmsy", "cmex", "cmr", "mathematica", "cambria math", "stix", "symbol", "mtmi", "mtsy", "msam", "msbm")
MATH_CHARS = set("∑∏∫∂∇√∞≈≠≤≥±×÷∈∉⊂⊆∪∩→⇒⇔∀∃αβγδεζηθικλμνξπρστυφχψωΔΘΛΞΠΣΦΨΩ=+<>^_{}|")
PAGE_NUM_RE = re.compile(r"^\s*(page\s*)?\d{1,4}(\s*(of|/)\s*\d{1,4})?\s*$|^\s*[-–]\s*\d{1,4}\s*[-–]\s*$", re.I)


def _is_bold(span: dict) -> bool:
    return bool(span["flags"] & 16) or "bold" in span["font"].lower() or "black" in span["font"].lower()


def _line_record(line: dict) -> Optional[dict]:
    spans = [s for s in line["spans"] if s["text"].strip()]
    if not spans:
        return None
    text = "".join(s["text"] for s in line["spans"]).strip()
    n = sum(len(s["text"].strip()) for s in spans) or 1
    size = sum(s["size"] * len(s["text"].strip()) for s in spans) / n
    bold = sum(len(s["text"].strip()) for s in spans if _is_bold(s)) / n
    math_font = sum(len(s["text"].strip()) for s in spans if any(m in s["font"].lower() for m in MATH_FONTS)) / n
    return {"text": text, "bbox": list(line["bbox"]), "size": size, "bold": bold,
            "italic": sum(len(s["text"].strip()) for s in spans if s["flags"] & 2) / n,
            "math_font": math_font, "font": spans[0]["font"], "dir": line.get("dir", (1, 0))}


MARKER_ONLY_RE = re.compile(r"^(?:[•●▪◦‣·∙■□\-–—*]|\(?\d{1,3}[.)]|\(?[a-zA-Z]\))$")


def _attach_markers(lines: list[dict]) -> list[dict]:
    """Bullets/numbers emitted as their own text object are glued to the line on the same baseline."""
    drop = set()
    for i, m in enumerate(lines):
        if not MARKER_ONLY_RE.match(m["text"]):
            continue
        mid = (m["bbox"][1] + m["bbox"][3]) / 2
        cands = [(j, l) for j, l in enumerate(lines) if j != i and j not in drop and 0 <= l["bbox"][0] - m["bbox"][2] < 40
                 and abs((l["bbox"][1] + l["bbox"][3]) / 2 - mid) < 4]
        if cands:
            j, l = min(cands, key=lambda c: c[1]["bbox"][0])
            l["text"] = f"{m['text']} {l['text']}"
            l["bbox"] = union(l["bbox"], m["bbox"])
            l["block_no"] = l["block_no"]
            drop.add(i)
    return [l for i, l in enumerate(lines) if i not in drop]


def page_lines(page) -> list[dict]:
    """All text lines on a page with font metadata."""
    d = page.get_text("dict", flags=1 | 2 | 8)  # ligatures, whitespace, dehyphenate off
    out = []
    for b in d["blocks"]:
        if b["type"] != 0:
            continue
        for ln in b["lines"]:
            rec = _line_record(ln)
            if rec:
                rec["block_no"] = b["number"]
                out.append(rec)
    return _attach_markers(out)


def estimate_body_size(all_lines: list[dict]) -> float:
    c: Counter = Counter()
    for ln in all_lines:
        c[round(ln["size"] * 2) / 2] += len(ln["text"])
    return c.most_common(1)[0][0] if c else 10.0


def _group_paragraphs(lines: list[dict]) -> list[list[dict]]:
    """Group lines (already in a single PyMuPDF block) into paragraphs."""
    paras: list[list[dict]] = []
    for ln in lines:
        if not paras:
            paras.append([ln]); continue
        prev = paras[-1][-1]
        h = max(prev["bbox"][3] - prev["bbox"][1], 1.0)
        gap = ln["bbox"][1] - prev["bbox"][3]
        new = gap > 0.45 * h or abs(ln["size"] - prev["size"]) > 1.0 or bool(BULLET_RE.match(ln["text"]))
        same_row = min(ln["bbox"][3], prev["bbox"][3]) - max(ln["bbox"][1], prev["bbox"][1]) > 0.5 * h
        if same_row and ln["bbox"][0] - prev["bbox"][2] > 20:  # side-by-side text (e.g. left/right footer)
            new = True
        if ln["bbox"][1] < prev["bbox"][1] - 2 * h:  # jumped upward: different column flow
            new = True
        (paras.append([ln]) if new else paras[-1].append(ln))
    return paras


def _join(lines: list[dict]) -> str:
    out = ""
    for ln in lines:
        t = ln["text"]
        if not out:
            out = t
        elif re.search(r"[A-Za-z]-$", out) and t[:1].islower():
            out = out[:-1] + t
        else:
            out += " " + t
    return re.sub(r"\s+", " ", out).strip()


def build_paragraphs(lines: list[dict]) -> list[dict]:
    """Lines -> paragraph candidates, preserving PyMuPDF block boundaries."""
    by_block: dict[int, list[dict]] = {}
    for ln in lines:
        by_block.setdefault(ln["block_no"], []).append(ln)
    out = []
    for _, blines in by_block.items():
        for para in _group_paragraphs(blines):
            bbox = None
            for ln in para:
                bbox = union(bbox, ln["bbox"])
            n = sum(len(l["text"]) for l in para) or 1
            confs = [l["conf"] for l in para if l.get("conf") is not None]
            out.append({
                "text": _join(para), "bbox": bbox, "n_lines": len(para),
                "ocr_conf": (sum(confs) / len(confs)) if confs else None,
                "size": sum(l["size"] * len(l["text"]) for l in para) / n,
                "bold": sum(l["bold"] * len(l["text"]) for l in para) / n,
                "italic": sum(l["italic"] * len(l["text"]) for l in para) / n,
                "math_font": sum(l["math_font"] * len(l["text"]) for l in para) / n,
                "font": para[0]["font"], "line_boxes": [l["bbox"] for l in para],
            })
    return out


def math_score(p: dict) -> float:
    t = p["text"]
    if not t:
        return 0.0
    sym = sum(1 for ch in t if ch in MATH_CHARS) / len(t)
    alpha_words = len(re.findall(r"[A-Za-z]{4,}", t))
    score = max(p["math_font"], min(1.0, sym * 3))
    if alpha_words >= 4:  # prose with an occasional symbol is not an equation
        score *= 0.3
    return score


def classify(p: dict, page_w: float, page_h: float, body: float) -> dict:
    """Return {'type', 'level_hint', 'signals', 'meta'} for a paragraph candidate."""
    t, (x0, y0, x1, y1) = p["text"], p["bbox"]
    meta: dict = {"font": p["font"], "font_size": round(p["size"], 2), "bold": p["bold"] > 0.6}
    sig = {"text_layer": 0.98}
    in_margin = y1 < 0.07 * page_h or y0 > 0.93 * page_h
    if in_margin:
        meta["margin"] = "top" if y1 < 0.5 * page_h else "bottom"
    m = math_score(p)
    if m >= 0.55 and len(t) <= 200 and p["n_lines"] <= 4:
        sig["classification"] = round(0.5 + 0.4 * m, 2)
        meta["math_score"] = round(m, 2)
        meta["equation_number"] = bool(EQNUM_RE.search(t))
        return {"type": "equation", "signals": sig, "meta": meta}
    if CAPTION_RE.match(t) and p["n_lines"] <= 6:
        sig["classification"] = 0.9
        return {"type": "caption", "signals": sig, "meta": meta}
    small = p["size"] <= 0.88 * body
    if small and y0 > 0.6 * page_h and not in_margin and FOOTNOTE_RE.match(t) and len(t) > 15:
        sig["classification"] = 0.8
        return {"type": "footnote", "signals": sig, "meta": meta}
    short = len(t) <= 110 and p["n_lines"] <= 3 and not re.search(r"[.!?;,]$", t)
    big = p["size"] >= 1.15 * body
    if short and (big or (p["bold"] > 0.8 and p["size"] >= 0.95 * body) or
                  (NUMBERED_HEADING_RE.match(t) and p["size"] >= 0.98 * body and p["bold"] > 0.5)):
        sig["classification"] = 0.92 if big else 0.78
        return {"type": "heading", "signals": sig, "meta": meta}
    bm = BULLET_RE.match(t)
    if bm and not PAGE_NUM_RE.match(t):
        marker = bm.group("m")
        meta.update({"marker": marker, "ordered": bool(re.match(r"\(?[\dA-Za-z]+[.)]", marker)) and marker not in "•●▪◦‣·∙■□-–—*"})
        meta["text_without_marker"] = bm.group("rest").strip()
        sig["classification"] = 0.85
        return {"type": "list", "signals": sig, "meta": meta}
    sig["classification"] = 0.93
    return {"type": "paragraph", "signals": sig, "meta": meta}


def extract_text(path: str) -> list[dict]:
    """Convenience: raw paragraph candidates for every page of a PDF."""
    import pymupdf
    out = []
    with pymupdf.open(path) as doc:
        for i, page in enumerate(doc, start=1):
            for p in build_paragraphs(page_lines(page)):
                p["page"] = i
                out.append(p)
    return out
