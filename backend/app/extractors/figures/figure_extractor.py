"""Figure/chart region detection and cropping. Never interprets figure content."""
import logging
from pathlib import Path
from typing import Optional

import numpy as np

from app.utils.bbox import bbox_area, intersection_area, overlap_ratio, union

log = logging.getLogger("parse-anything")


def _merge_overlapping(boxes: list[list[float]], pad: float = 4.0) -> list[list[float]]:
    boxes = [list(b) for b in boxes]
    changed = True
    while changed:
        changed = False
        out: list[list[float]] = []
        for b in boxes:
            for o in out:
                if intersection_area([b[0] - pad, b[1] - pad, b[2] + pad, b[3] + pad], o) > 0:
                    o[:] = union(o, b)
                    changed = True
                    break
            else:
                out.append(b)
        boxes = out
    return boxes


def detect_figures_pdf(page, table_bboxes: list[list[float]]) -> list[dict]:
    W, H = page.rect.width, page.rect.height
    page_area = W * H
    regions: list[dict] = []
    imgs = []
    try:
        for info in page.get_image_info():
            b = list(info["bbox"])
            if bbox_area(b) >= 0.005 * page_area and (b[2] - b[0]) > 30 and (b[3] - b[1]) > 30:
                imgs.append(b)
    except Exception as exc:
        log.info("image info failed p%s: %s", page.number + 1, exc)
    for b in _merge_overlapping(imgs):
        if bbox_area(b) > 0.9 * page_area:  # full-page background image, not a figure
            continue
        regions.append({"type": "figure", "bbox": b, "confidence": 0.85, "source": "embedded-image"})
    try:
        drawings = page.get_drawings()
        for rect in page.cluster_drawings(drawings=drawings):
            b = [rect.x0, rect.y0, rect.x1, rect.y1]
            w, h = b[2] - b[0], b[3] - b[1]
            if w < 60 or h < 60 or bbox_area(b) < 0.02 * page_area or bbox_area(b) > 0.85 * page_area:
                continue
            if any(overlap_ratio(b, t) > 0.5 or overlap_ratio(t, b) > 0.5 for t in table_bboxes):
                continue
            n = sum(1 for d in drawings if overlap_ratio([d["rect"].x0, d["rect"].y0, d["rect"].x1, d["rect"].y1], b) > 0.9)
            if n < 8:  # decorative boxes / rules
                continue
            if any(overlap_ratio(b, r["bbox"]) > 0.6 for r in regions):
                continue
            regions.append({"type": "figure", "bbox": b, "confidence": 0.65, "source": "vector-drawing", "n_paths": n})
    except Exception as exc:
        log.info("vector figure detection skipped p%s: %s", page.number + 1, exc)
    return regions


def detect_figures_image(gray: np.ndarray, scale: float, occupied: list[list[float]]) -> list[dict]:
    """Raster pages: large ink blobs that OCR/tables did not explain. Low confidence by design."""
    import cv2
    h, w = gray.shape
    bw = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)[1]
    for o in occupied:
        x0, y0, x1, y1 = [int(v / scale) for v in o]
        bw[max(0, y0 - 4):y1 + 4, max(0, x0 - 4):x1 + 4] = 0
    bw = cv2.dilate(bw, cv2.getStructuringElement(cv2.MORPH_RECT, (25, 25)))
    cnts, _ = cv2.findContours(bw, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    out = []
    for c in cnts:
        x, y, cw, ch = cv2.boundingRect(c)
        if cw * ch >= 0.04 * w * h and cw > 0.15 * w and ch > 0.08 * h:
            out.append({"type": "figure", "bbox": [x * scale, y * scale, (x + cw) * scale, (y + ch) * scale],
                        "confidence": 0.5, "source": "raster-blob"})
    return out


def save_crop(page, bbox: list[float], out_path: Path, dpi: int = 150) -> str:
    import pymupdf
    out_path.parent.mkdir(parents=True, exist_ok=True)
    clip = pymupdf.Rect(bbox) & page.rect
    page.get_pixmap(dpi=dpi, clip=clip).save(str(out_path))
    return out_path.name


def extract_figure(region: dict, page=None, out_dir: Optional[Path] = None, block_id: str = "fig") -> dict:
    meta = {"source": region.get("source"), "embedded_text": region.get("embedded_text", []), "caption": None}
    if page is not None and out_dir is not None:
        meta["image_path"] = f"figures/{save_crop(page, region['bbox'], out_dir / 'figures' / f'{block_id}.png')}"
    sig = {"figure_detection": float(region.get("confidence", 0.6))}
    return {"signals": sig, "meta": meta}
