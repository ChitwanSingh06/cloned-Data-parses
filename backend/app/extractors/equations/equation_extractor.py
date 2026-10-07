"""Equation handling. No formula-recognition model ships with the repo, so by default the region is
preserved (image + raw text-layer text) and flagged for review; LaTeX is never invented."""
import logging
from functools import lru_cache
from pathlib import Path
from typing import Optional

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
    meta["review_reason"] = "No formula recognizer available; LaTeX not generated. Original region preserved."
    return {"signals": sig, "meta": meta}
