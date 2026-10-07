"""Optional local handwriting recognition (TrOCR via transformers+torch). Pure-Python, Windows-safe.

Never raises on missing dependencies: `htr_available()` is False and callers fall back to REVIEW_REQUIRED.
"""
import importlib.util
import logging
import math
from functools import lru_cache

from PIL import Image

from app.core import config

log = logging.getLogger("parse-anything")


class HTRUnavailable(RuntimeError):
    pass


def htr_available() -> bool:
    if config.HTR_MODE == "off":
        return False
    return all(importlib.util.find_spec(m) is not None for m in ("torch", "transformers"))


@lru_cache(maxsize=1)
def _load():
    if not htr_available():
        raise HTRUnavailable("HTR disabled or torch/transformers not installed (pip install -r requirements-htr.txt)")
    from transformers import TrOCRProcessor, VisionEncoderDecoderModel
    kw = {"cache_dir": str(config.HTR_CACHE_DIR)}
    processor = TrOCRProcessor.from_pretrained(config.HTR_MODEL, **kw)
    model = VisionEncoderDecoderModel.from_pretrained(config.HTR_MODEL, **kw).eval()
    return processor, model


def recognize(line_img: Image.Image) -> tuple[str, float]:
    """Recognise ONE handwritten text line. Returns (text, confidence 0-1 from token probabilities)."""
    import torch
    processor, model = _load()
    pixel = processor(images=line_img.convert("RGB"), return_tensors="pt").pixel_values
    with torch.no_grad():
        out = model.generate(pixel, max_new_tokens=64, output_scores=True, return_dict_in_generate=True)
    text = processor.batch_decode(out.sequences, skip_special_tokens=True)[0].strip()
    scores = model.compute_transition_scores(out.sequences, out.scores, normalize_logits=True)[0]
    probs = [math.exp(float(s)) for s in scores if float(s) > -1e8]
    conf = sum(probs) / len(probs) if probs else 0.0
    return text, round(max(0.0, min(1.0, conf)), 3)
