"""Printed-vs-handwriting detection and line-level routing to the HTR engine.

Handwriting is only claimed when geometry (baseline jitter, stroke-width variation) AND weak printed-OCR
confidence agree; printed text that Tesseract reads confidently is never re-routed.
"""
import logging
from typing import Optional

import numpy as np
from PIL import Image

from app.core import config
from app.extractors.ocr import htr_engine

log = logging.getLogger("parse-anything")


def _ink(gray: np.ndarray) -> np.ndarray:
    import cv2
    return cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)[1]


def handwriting_features(gray: np.ndarray) -> dict:
    import cv2
    bw = _ink(gray)
    n, _, stats, _ = cv2.connectedComponentsWithStats(bw, connectivity=8)
    comps = [s for s in stats[1:] if s[cv2.CC_STAT_AREA] >= 12 and s[cv2.CC_STAT_HEIGHT] >= 4]
    if len(comps) < 3:
        return {"components": len(comps), "baseline_jitter": 0.0, "stroke_cv": 0.0}
    heights = np.array([c[cv2.CC_STAT_HEIGHT] for c in comps], float)
    bottoms = np.array([c[cv2.CC_STAT_TOP] + c[cv2.CC_STAT_HEIGHT] for c in comps], float)
    big = heights >= 0.6 * np.median(heights)  # ignore dots / punctuation for baseline estimate
    jitter = float(np.std(bottoms[big]) / max(np.median(heights[big]), 1.0)) if big.sum() >= 3 else 0.0
    dist = cv2.distanceTransform(bw, cv2.DIST_L2, 3)
    widths = np.array([dist[c[1]:c[1] + c[3], c[0]:c[0] + c[2]].max() for c in comps if c[2] > 2 and c[3] > 2], float)
    stroke_cv = float(np.std(widths) / max(np.mean(widths), 1e-6)) if widths.size >= 3 else 0.0
    return {"components": len(comps), "baseline_jitter": jitter, "stroke_cv": stroke_cv}


def handwriting_score(gray: np.ndarray, ocr_conf: Optional[float]) -> float:
    """0-1 likelihood that a text-line crop is handwritten. ocr_conf=None means printed OCR found nothing."""
    f = handwriting_features(gray)
    if f["components"] < 3:
        return 0.0
    geo = 0.55 * min(1.0, f["baseline_jitter"] / 0.30) + 0.45 * min(1.0, f["stroke_cv"] / 0.55)
    weak = 1.0 if ocr_conf is None else max(0.0, min(1.0, (0.85 - ocr_conf) / 0.35))
    return round(0.5 * geo + 0.5 * weak, 3)


def _crop(gray: np.ndarray, box_px: list[float], pad: int = 6) -> np.ndarray:
    h, w = gray.shape
    x0, y0, x1, y1 = box_px
    return gray[max(0, int(y0) - pad):min(h, int(y1) + pad), max(0, int(x0) - pad):min(w, int(x1) + pad)]


def refine_lines(lines: list[dict], gray: np.ndarray) -> list[dict]:
    """Annotate each OCR line with kind=printed|handwritten and, when HTR is available, replace its text."""
    use_htr = htr_engine.htr_available()
    for ln in lines:
        ln.setdefault("kind", "printed")
        crop = _crop(gray, ln["bbox"])
        if crop.size == 0 or ln["confidence"] >= 0.8:  # confident printed OCR: leave alone
            continue
        score = handwriting_score(crop, ln["confidence"])
        ln["hw_score"] = score
        if score < config.HTR_THRESHOLD:
            continue
        ln["kind"] = "handwritten"
        if not use_htr:
            ln["review_reason"] = "Probable handwriting; no HTR model installed, printed-OCR text is unreliable."
            continue
        try:
            text, conf = htr_engine.recognize(Image.fromarray(crop))
        except Exception as exc:
            log.warning("HTR failed: %s", exc)
            ln["review_reason"] = f"Handwriting recognition failed: {exc}"
            continue
        if not text.strip():
            ln["review_reason"] = "HTR returned empty text for a handwritten line."
            continue
        ln.update(text=text, confidence=conf, recognizer="htr",
                  words=[{"text": text, "bbox": list(ln["bbox"]), "confidence": conf}])
    return lines


def segment_lines(gray_blob: np.ndarray) -> list[tuple[int, int]]:
    """Horizontal-projection text-line segmentation of an ink blob -> [(y0, y1)] in blob pixels."""
    ink = (_ink(gray_blob) > 0).sum(axis=1).astype(float)
    if ink.max() == 0:
        return []
    thr = 0.08 * ink.max()
    rows, start = [], None
    for y, v in enumerate(ink):
        if v > thr and start is None:
            start = y
        elif v <= thr and start is not None:
            if y - start >= 8:
                rows.append((start, y))
            start = None
    if start is not None and len(ink) - start >= 8:
        rows.append((start, len(ink)))
    return rows


def find_handwriting_blobs(gray: np.ndarray, scale: float, occupied: list[list[float]]) -> list[dict]:
    """Ink areas that printed OCR/tables did not explain and that look handwritten.
    Returns [{bbox(pt), lines:[{bbox(pt), crop(np)}]}]; recognition happens in the caller."""
    import cv2
    h, w = gray.shape
    bw = _ink(gray)
    for o in occupied:
        x0, y0, x1, y1 = [int(v / scale) for v in o]
        bw[max(0, y0 - 4):y1 + 4, max(0, x0 - 4):x1 + 4] = 0
    merged = cv2.dilate(bw, cv2.getStructuringElement(cv2.MORPH_RECT, (35, 9)))
    cnts, _ = cv2.findContours(merged, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    out = []
    for c in cnts:
        x, y, cw, ch = cv2.boundingRect(c)
        if cw < 0.08 * w or ch < 14 or cw * ch > 0.4 * w * h:
            continue
        crop = gray[y:y + ch, x:x + cw]
        if handwriting_score(crop, None) < config.HTR_THRESHOLD:
            continue
        lines = [{"bbox": [x * scale, (y + a) * scale, (x + cw) * scale, (y + b) * scale], "crop": crop[a:b]}
                 for a, b in segment_lines(crop)]
        if lines:
            out.append({"bbox": [x * scale, y * scale, (x + cw) * scale, (y + ch) * scale], "lines": lines})
    return out
