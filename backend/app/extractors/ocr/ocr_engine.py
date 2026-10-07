"""OCR with a pluggable backend. PaddleOCR if installed/configured, else Tesseract."""
import logging
import os
import statistics
from functools import lru_cache

from PIL import Image

from app.core.config import OCR_ENGINE, OCR_LANGS
from app.utils.platform_utils import find_tesseract

log = logging.getLogger("parse-anything")
os.environ.setdefault("OMP_THREAD_LIMIT", "1")  # tesseract+OpenMP is ~2.5x faster single-threaded per page


class OCRUnavailable(RuntimeError):
    pass


def _pytesseract():
    """Import pytesseract and point it at tesseract.exe on Windows, where the installer does not update PATH."""
    import pytesseract
    cmd = find_tesseract()
    if cmd:
        pytesseract.pytesseract.tesseract_cmd = cmd
    return pytesseract


@lru_cache(maxsize=1)
def _paddle():
    from paddleocr import PaddleOCR  # heavy import; only when requested/available
    return PaddleOCR(use_angle_cls=False, lang="en", show_log=False)


@lru_cache(maxsize=1)
def tesseract_langs() -> str:
    """Requested languages (default eng+hin+tam) limited to traineddata actually installed; missing packs degrade gracefully."""
    wanted = [l for l in OCR_LANGS.split("+") if l] or ["eng"]
    try:
        installed = set(_pytesseract().get_languages(config=""))
    except Exception:
        return "eng"
    usable = [l for l in wanted if l in installed]
    for l in wanted:
        if l not in installed:
            log.warning("Tesseract language '%s' is not installed; skipping it", l)
    return "+".join(usable) if usable else "eng"


def available_engine() -> str:
    # PaddleOCR is configured for English only here, so use Tesseract whenever a non-English
    # requested language (e.g. Hindi or Tamil) is actually available.
    langs = tesseract_langs().split("+") if _tesseract_ok() else []
    multilingual = any(lang != "eng" for lang in langs)
    if OCR_ENGINE in ("auto", "paddle") and not (OCR_ENGINE == "auto" and multilingual):
        try:
            import paddleocr  # noqa: F401
            return "paddle"
        except Exception:
            if OCR_ENGINE == "paddle":
                log.warning("PaddleOCR requested but not importable; falling back to tesseract")
    try:
        _pytesseract().get_tesseract_version()
        return "tesseract"
    except Exception as exc:
        raise OCRUnavailable(f"No OCR engine available: {exc}. Install Tesseract and add it to PATH "
                             f"or set TESSERACT_CMD to the full path of the executable.")


def _tesseract_ok() -> bool:
    try:
        _pytesseract().get_tesseract_version()
        return True
    except Exception:
        return False


def _tesseract(img: Image.Image) -> list[dict]:
    pytesseract = _pytesseract()
    d = pytesseract.image_to_data(img, output_type=pytesseract.Output.DICT, config="--psm 3", lang=tesseract_langs())
    lines: dict[tuple, dict] = {}
    for i, txt in enumerate(d["text"]):
        txt = (txt or "").strip()
        conf = float(d["conf"][i])
        if not txt or conf < 0:
            continue
        key = (d["block_num"][i], d["par_num"][i], d["line_num"][i])
        x, y, w, h = d["left"][i], d["top"][i], d["width"][i], d["height"][i]
        word = {"text": txt, "bbox": [x, y, x + w, y + h], "confidence": conf / 100.0}
        ln = lines.setdefault(key, {"block": key[0], "par": key[1], "words": []})
        ln["words"].append(word)
    return list(lines.values())


def _paddle_lines(img: Image.Image) -> list[dict]:
    import numpy as np
    res = _paddle().ocr(np.array(img.convert("RGB")), cls=False)
    out = []
    for i, item in enumerate((res[0] or []) if res else []):
        pts, (txt, conf) = item
        xs, ys = [p[0] for p in pts], [p[1] for p in pts]
        word = {"text": txt, "bbox": [min(xs), min(ys), max(xs), max(ys)], "confidence": float(conf)}
        out.append({"block": 0, "par": i, "words": [word]})  # paddle gives lines; no paragraph ids
    return out


def extract_ocr(img: Image.Image) -> tuple[list[dict], str]:
    """Return (lines, engine). Each line: words[], text, bbox, confidence, height (px)."""
    engine = available_engine()
    raw = _paddle_lines(img) if engine == "paddle" else _tesseract(img)
    lines = []
    for ln in raw:
        ws = sorted(ln["words"], key=lambda w: w["bbox"][0])
        x0 = min(w["bbox"][0] for w in ws); y0 = min(w["bbox"][1] for w in ws)
        x1 = max(w["bbox"][2] for w in ws); y1 = max(w["bbox"][3] for w in ws)
        lines.append({"block": ln["block"], "par": ln["par"], "words": ws,
                      "text": " ".join(w["text"] for w in ws), "bbox": [x0, y0, x1, y1],
                      "confidence": statistics.fmean(w["confidence"] for w in ws), "height": y1 - y0})
    lines.sort(key=lambda l: (l["bbox"][1], l["bbox"][0]))
    return lines, engine
