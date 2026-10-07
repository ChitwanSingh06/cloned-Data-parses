import os
from pathlib import Path

BASE_DIR = Path(os.getenv("PARSE_BASE_DIR", Path(__file__).resolve().parents[3]))
UPLOAD_DIR = Path(os.getenv("PARSE_UPLOAD_DIR", BASE_DIR / "data" / "uploads"))
PROCESSED_DIR = Path(os.getenv("PARSE_PROCESSED_DIR", BASE_DIR / "data" / "processed"))
for _d in (UPLOAD_DIR, PROCESSED_DIR):
    _d.mkdir(parents=True, exist_ok=True)

MAX_UPLOAD_MB = int(os.getenv("PARSE_MAX_UPLOAD_MB", "50"))
OCR_DPI = int(os.getenv("PARSE_OCR_DPI", "200"))
OCR_ENGINE = os.getenv("PARSE_OCR_ENGINE", "auto")  # auto | paddle | tesseract
MIN_TEXT_CHARS = int(os.getenv("PARSE_MIN_TEXT_CHARS", "25"))  # below this a page is treated as scanned
REVIEW_THRESHOLD = float(os.getenv("PARSE_REVIEW_THRESHOLD", "0.6"))
HIGH_THRESHOLD = float(os.getenv("PARSE_HIGH_THRESHOLD", "0.85"))
