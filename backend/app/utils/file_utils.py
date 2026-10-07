from pathlib import Path

SUPPORTED_EXTENSIONS = {".pdf"}  # only PDF is implemented; other handlers are stubs
PLANNED_EXTENSIONS = {".docx", ".pptx", ".xlsx", ".png", ".jpg", ".jpeg"}


def is_supported(path: str) -> bool:
    return Path(path).suffix.lower() in SUPPORTED_EXTENSIONS


def is_pdf_bytes(head: bytes) -> bool:
    return b"%PDF-" in head[:1024]
