"""Stage 1 — Detect & Route input: validate, per-page text-layer analysis, layout regions."""
import logging
import os
import statistics
from pathlib import Path
from typing import Any

import numpy as np
import pymupdf

from app.core.config import MIN_TEXT_CHARS, OCR_DPI
from app.extractors.figures.figure_extractor import detect_figures_image, detect_figures_pdf
from app.extractors.ocr.image_preprocessor import preprocess_image
from app.extractors.ocr.ocr_engine import OCRUnavailable, extract_ocr
from app.extractors.tables.table_detector import detect_tables_image, detect_tables_pdf
from app.extractors.text.pdf_text import build_paragraphs, classify, estimate_body_size, page_lines
from app.pipeline.failsafe import make_error
from app.utils.bbox import bbox_area, overlap_ratio, round_bbox
from app.utils.file_utils import is_pdf_bytes, is_supported

log = logging.getLogger("parse-anything")


def _garbled(text: str) -> bool:
    if not text:
        return False
    bad = sum(1 for ch in text if ch == "\ufffd" or (ord(ch) < 32 and ch not in "\n\t\r"))
    return bad / len(text) > 0.2


def _image_coverage(page) -> float:
    try:
        cov = sum(min(bbox_area(list(i["bbox"])), page.rect.width * page.rect.height) for i in page.get_image_info())
        return min(1.0, cov / (page.rect.width * page.rect.height))
    except Exception:
        return 0.0


def _center_in(b: list[float], boxes: list[list[float]]) -> int:
    cx, cy = (b[0] + b[2]) / 2, (b[1] + b[3]) / 2
    for i, o in enumerate(boxes):
        if o[0] <= cx <= o[2] and o[1] <= cy <= o[3]:
            return i
    return -1


def open_pdf(path: str) -> tuple[Any, list[dict]]:
    """Validate and open. Returns (doc|None, errors)."""
    p = Path(path)
    if not p.exists():
        return None, [make_error("CORRUPT_PDF", "File not found")]
    if not is_supported(path):
        return None, [make_error("UNSUPPORTED_FORMAT", f"Unsupported extension '{p.suffix}'. Only PDF is implemented.")]
    with open(p, "rb") as fh:
        if not is_pdf_bytes(fh.read(1024)):
            return None, [make_error("CORRUPT_PDF", "File does not contain a PDF header")]
    try:
        doc = pymupdf.open(str(p))
    except Exception as exc:
        return None, [make_error("CORRUPT_PDF", f"Cannot open PDF: {exc}")]
    if doc.needs_pass:
        doc.close()  # release the file handle (Windows cannot delete/replace a file that is still open)
        return None, [make_error("ENCRYPTED_PDF")]
    if doc.page_count == 0:
        doc.close()
        return None, [make_error("CORRUPT_PDF", "PDF has no pages")]
    return doc, []


def _split_wide_gaps(words: list[dict], height: float) -> list[list[dict]]:
    """Split an OCR line where words are separated by a column-sized gap (e.g. left/right footer)."""
    segs: list[list[dict]] = [[words[0]]]
    for w in words[1:]:
        if w["bbox"][0] - segs[-1][-1]["bbox"][2] > 4 * max(height, 1):
            segs.append([w])
        else:
            segs[-1].append(w)
    return segs


def _region(page_no: int, n: int, rtype: str, bbox, conf: float, **kw) -> dict:
    return {"id": f"R{page_no}-{n}", "page": page_no, "type": rtype, "bbox": round_bbox(bbox),
            "confidence": conf, **kw}


def _digital_regions(page, page_no: int, body: float, errors: list[dict]) -> list[dict]:
    W, H = page.rect.width, page.rect.height
    regions: list[dict] = []
    tables: list[dict] = []
    try:
        tables = detect_tables_pdf(page)
    except Exception as exc:
        errors.append(make_error("TABLE_EXTRACTION_FAILURE", f"Table detection failed: {exc}", page=page_no))
    table_boxes = [t["bbox"] for t in tables]
    figs = detect_figures_pdf(page, table_boxes)
    fig_boxes = [f["bbox"] for f in figs]
    lines = page_lines(page)
    kept = []
    for ln in lines:
        if _center_in(ln["bbox"], table_boxes) >= 0:
            continue
        fi = _center_in(ln["bbox"], fig_boxes)
        if fi >= 0:
            figs[fi].setdefault("embedded_text", []).append(ln["text"])
            continue
        kept.append(ln)
    n = 0
    for t in tables:
        n += 1
        regions.append(_region(page_no, n, "table", t["bbox"], t["confidence"], raw=t["raw"], strategy=t["strategy"], source="text-layer"))
    for f in figs:
        n += 1
        regions.append(_region(page_no, n, "figure", f["bbox"], f["confidence"], source=f["source"],
                               embedded_text=f.get("embedded_text", []), n_paths=f.get("n_paths", 0)))
    for p in build_paragraphs(kept):
        c = classify(p, W, H, body)
        n += 1
        rtype = "equation" if c["type"] == "equation" else "text"
        regions.append(_region(page_no, n, rtype, p["bbox"], c["signals"]["classification"], hint=c["type"], text=p["text"],
                               signals=c["signals"], meta=c["meta"], source="text-layer", line_boxes=p["line_boxes"]))
    return regions


def _ocr_regions(page, page_no: int, errors: list[dict]) -> list[dict]:
    W, H = page.rect.width, page.rect.height
    scale = 72.0 / OCR_DPI
    pix = page.get_pixmap(dpi=OCR_DPI, colorspace=pymupdf.csGRAY)
    from PIL import Image
    img = Image.frombytes("L", (pix.width, pix.height), pix.samples)
    gray = np.array(img)
    pre = preprocess_image(img)
    try:
        lines, engine = extract_ocr(pre)
    except OCRUnavailable as exc:
        errors.append(make_error("OCR_FAILURE", str(exc), page=page_no))
        return []
    except Exception as exc:
        errors.append(make_error("OCR_FAILURE", f"OCR failed: {exc}", page=page_no))
        return []
    regions: list[dict] = []
    tables = []
    try:
        tables = detect_tables_image(gray, scale)
    except Exception as exc:
        errors.append(make_error("TABLE_EXTRACTION_FAILURE", f"Raster table detection failed: {exc}", page=page_no))
    table_boxes = [t["bbox"] for t in tables]
    recs = []
    for ln in lines:
        b = [v * scale for v in ln["bbox"]]
        words = [{"text": w["text"], "bbox": [v * scale for v in w["bbox"]], "confidence": w["confidence"]} for w in ln["words"]]
        ti = _center_in(b, table_boxes)
        if ti >= 0:
            tables[ti].setdefault("words", []).extend(words)
            tables[ti].setdefault("confs", []).append(ln["confidence"])
            continue
        for seg in _split_wide_gaps(ln["words"], ln["height"]):
            sb = [min(w["bbox"][0] for w in seg) * scale, min(w["bbox"][1] for w in seg) * scale,
                  max(w["bbox"][2] for w in seg) * scale, max(w["bbox"][3] for w in seg) * scale]
            recs.append({"text": " ".join(w["text"] for w in seg), "bbox": sb, "size": ln["height"] * scale * 0.8, "bold": 0.0,
                         "italic": 0.0, "math_font": 0.0, "font": f"ocr:{engine}", "dir": (1, 0),
                         "conf": sum(w["confidence"] for w in seg) / len(seg),
                         "block_no": ln["block"] * 1000 + ln["par"] if engine == "tesseract" else 0})
    body = statistics.median([r["size"] for r in recs]) if recs else 10.0
    n = 0
    for t in tables:
        n += 1
        confs = t.get("confs") or [0.0]
        regions.append(_region(page_no, n, "table", t["bbox"], t["confidence"], raw=t["raw"], words=t.get("words", []),
                               ocr_conf=round(statistics.fmean(confs), 3), strategy=t["strategy"], source=f"ocr:{engine}"))
    for p in build_paragraphs(recs):
        c = classify(p, W, H, body * 1.13)
        sig = {"ocr": round(p["ocr_conf"] or 0.0, 3), "classification": c["signals"]["classification"] * 0.9}
        n += 1
        rtype = "equation" if c["type"] == "equation" else "text"
        regions.append(_region(page_no, n, rtype, p["bbox"], sig["ocr"], hint=c["type"], text=p["text"], signals=sig,
                               meta={**c["meta"], "ocr_engine": engine}, source=f"ocr:{engine}", line_boxes=p["line_boxes"]))
    for f in detect_figures_image(gray, scale, table_boxes + [r["bbox"] for r in recs]):
        n += 1
        regions.append(_region(page_no, n, "figure", f["bbox"], f["confidence"], source=f["source"], embedded_text=[], n_paths=0))
    return regions


def detect_document(path: str, size_limit_mb: int | None = None) -> dict:
    result: dict[str, Any] = {"path": path, "format": Path(path).suffix.lstrip(".").lower(), "pages": [], "regions": [], "errors": []}
    if size_limit_mb and os.path.exists(path) and os.path.getsize(path) > size_limit_mb * 1024 * 1024:
        result["errors"].append(make_error("FILE_TOO_LARGE"))
        return result
    doc, errs = open_pdf(path)
    result["errors"].extend(errs)
    if doc is None:
        return result
    try:
        infos, line_cache = [], {}
        for i, page in enumerate(doc, start=1):
            try:
                lines = page_lines(page)
                chars = sum(len(l["text"]) for l in lines)
                text = " ".join(l["text"] for l in lines)
                cov = _image_coverage(page)
                scanned = chars < MIN_TEXT_CHARS or _garbled(text) or (cov >= 0.8 and chars < 150)
                line_cache[i] = lines
            except Exception as exc:
                result["errors"].append(make_error("LAYOUT_DETECTION_FAILURE", f"Page analysis failed: {exc}", page=i))
                chars, scanned, cov = 0, True, 0.0
            infos.append({"page_number": i, "width": round(page.rect.width, 2), "height": round(page.rect.height, 2),
                          "is_scanned": scanned, "text_chars": chars, "image_coverage": round(cov, 2),
                          "source": "ocr" if scanned else "digital"})
        result["pages"] = infos
        body = estimate_body_size([l for i, ls in line_cache.items() if not infos[i - 1]["is_scanned"] for l in ls])
        result["body_size"] = body
        for info in infos:
            i, page = info["page_number"], doc[info["page_number"] - 1]
            try:
                regs = _ocr_regions(page, i, result["errors"]) if info["is_scanned"] else _digital_regions(page, i, body, result["errors"])
                result["regions"].extend(regs)
            except Exception as exc:
                log.exception("page %s failed", i)
                result["errors"].append(make_error("LAYOUT_DETECTION_FAILURE", f"Region detection failed: {exc}", page=i))
    finally:
        doc.close()
    return result
