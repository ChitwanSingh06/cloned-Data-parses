from pathlib import Path

SUPPORTED_EXTENSIONS = {".pdf", ".docx", ".pptx", ".xlsx"}
PLANNED_EXTENSIONS = {".png", ".jpg", ".jpeg"}


def is_supported(path: str) -> bool:
    return Path(path).suffix.lower() in SUPPORTED_EXTENSIONS


def is_pdf_bytes(head: bytes) -> bool:
    return b"%PDF-" in head[:1024]


def detect_format(path: str) -> str:
    return Path(path).suffix.lower().lstrip(".")
