"""Equation extraction: span-geometry LaTeX (text layer) -> pix2tex (images, optional) -> preserved + REVIEW_REQUIRED.
LaTeX is never invented; every path records its recognizer and evidence."""
import logging
from functools import lru_cache
from pathlib import Path
from typing import Optional

from app.extractors.equations.math_layout import page_region_to_latex

log = logging.getLogger("parse-anything")


@lru_cache(maxsize=1)
def _pix2tex():
    try:
        from pix2tex.cli import LatexOCR  # optional dependency
        return LatexOCR()
    except Exception:
        return None


def extract_equation(region: dict, page=None, out_dir: Optional[Path] = None, block_id: str = "eq") -> dict:
    from app.extractors.figures.figure_extractor import save_crop
    meta = {"latex": None, "raw_text": region.get("text", ""), "recognizer": None}
    sig = {"equation_detection": float(region.get("confidence", 0.6))}
    img_rel = None
    if page is not None and out_dir is not None:
        img_rel = f"figures/{save_crop(page, region['bbox'], out_dir / 'figures' / f'{block_id}.png', dpi=200)}"
        meta["image_path"] = img_rel
    if page is not None and not region.get("source", "").startswith(("ocr", "htr")):
        try:
            r = page_region_to_latex(page, region["bbox"])
            if r["latex"]:
                meta.update(latex=r["latex"], recognizer="span-geometry", structures=r["structures"])
                sig["formula"] = 0.85 if not r["unmapped"] else 0.5
                if r["unmapped"]:
                    meta["unmapped_symbols"] = r["unmapped"]
                    meta["review_reason"] = f"LaTeX contains symbols without a known mapping: {''.join(r['unmapped'])}"
                return {"signals": sig, "meta": meta}
        except Exception as exc:
            log.warning("structural equation conversion failed: %s", exc)
            meta["formula_error"] = str(exc)
    model = _pix2tex()
    if model is not None and img_rel:
        try:
            from PIL import Image
            latex = model(Image.open(out_dir / img_rel)).strip()
            if latex:
                meta.update(latex=latex, recognizer="pix2tex")
                sig["formula"] = 0.75
                return {"signals": sig, "meta": meta}
        except Exception as exc:
            log.warning("formula recognition failed: %s", exc)
            meta["formula_error"] = str(exc)
    sig["formula"] = 0.35
    meta["review_reason"] = "No reliable formula recognition (no text-layer geometry, no pix2tex); LaTeX not generated. Original region preserved."
    return {"signals": sig, "meta": meta}
