"""Table region detection: PyMuPDF find_tables for digital pages, OpenCV ruling lines for scans."""
import logging
import re
from typing import Optional

import numpy as np

from app.utils.bbox import overlap_ratio

log = logging.getLogger("parse-anything")
NUM_RE = re.compile(r"^[\(\-–−$€£₹]*\s*[\d.,]+\s*[%)]*$")


def _fill_and_numeric(rows: list[list]) -> tuple[float, float]:
    cells = [c for r in rows for c in r]
    if not cells:
        return 0.0, 0.0
    filled = [str(c).strip() for c in cells if c is not None and str(c).strip()]
    nums = [c for c in filled if NUM_RE.match(c)]
    return len(filled) / len(cells), (len(nums) / len(filled) if filled else 0.0)


def _pack(t, strategy: str, conf: float) -> dict:
    return {"type": "table", "bbox": [float(v) for v in t.bbox], "confidence": conf, "strategy": strategy,
            "raw": {"kind": "pymupdf", "text": t.extract(),
                    "row_cells": [[list(c) if c is not None else None for c in r.cells] for r in t.rows]}}


def detect_tables_pdf(page) -> list[dict]:
    """Ruled tables first; conservative text-alignment fallback for borderless numeric tables."""
    found: list[dict] = []
    try:
        for t in page.find_tables().tables:
            if t.row_count >= 2 and t.col_count >= 2:
                fill, _ = _fill_and_numeric(t.extract())
                if fill >= 0.25:
                    found.append(_pack(t, "lines", 0.92 if fill > 0.5 else 0.75))
    except Exception as exc:
        log.warning("find_tables(lines) failed on page %s: %s", page.number + 1, exc)
        raise
    try:
        for t in page.find_tables(strategy="text").tables:
            bbox = [float(v) for v in t.bbox]
            if any(overlap_ratio(bbox, f["bbox"]) > 0.3 for f in found):
                continue
            rows = t.extract()
            fill, num = _fill_and_numeric(rows)
            if t.col_count >= 3 and t.row_count >= 3 and fill >= 0.6 and num >= 0.3:
                found.append(_pack(t, "text", 0.58))  # borderless: reviewable by design
    except Exception as exc:
        log.info("find_tables(text) skipped on page %s: %s", page.number + 1, exc)
    return found


def _cluster(vals: list[float], tol: float) -> list[float]:
    out: list[list[float]] = []
    for v in sorted(vals):
        if out and v - out[-1][-1] <= tol:
            out[-1].append(v)
        else:
            out.append([v])
    return [float(np.mean(g)) for g in out]


def detect_tables_image(gray: np.ndarray, scale: float) -> list[dict]:
    """Detect ruled tables on a raster page. `scale` converts px -> PDF points."""
    import cv2
    h, w = gray.shape
    bw = cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_MEAN_C, cv2.THRESH_BINARY_INV, 15, 10)
    hor = cv2.morphologyEx(bw, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (max(w // 25, 20), 1)))
    ver = cv2.morphologyEx(bw, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (1, max(h // 25, 20))))
    grid = cv2.dilate(cv2.bitwise_or(hor, ver), np.ones((5, 5), np.uint8))
    cnts, _ = cv2.findContours(grid, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    tables = []
    for c in cnts:
        x, y, cw, ch = cv2.boundingRect(c)
        if cw * ch < 0.02 * w * h or cw < w * 0.2:
            continue
        ys = _cluster([float(v) for v in np.where(hor[y:y + ch, x:x + cw].sum(axis=1) > 0.5 * 255 * cw)[0] + y], 6)
        xs = _cluster([float(v) for v in np.where(ver[y:y + ch, x:x + cw].sum(axis=0) > 0.5 * 255 * ch)[0] + x], 6)
        if len(ys) < 3 or len(xs) < 3:
            continue
        tables.append({"type": "table", "bbox": [x * scale, y * scale, (x + cw) * scale, (y + ch) * scale],
                       "confidence": 0.7, "strategy": "opencv-lines",
                       "raw": {"kind": "grid", "row_edges": [v * scale for v in ys], "col_edges": [v * scale for v in xs]}})
    return tables
