"""Structured errors. A failed region never aborts the document."""
from typing import Any, Optional

ERROR_CODES = {
    "UNSUPPORTED_FORMAT": "The input format is not supported.",
    "CORRUPT_PDF": "The PDF could not be opened or is corrupt.",
    "CORRUPT_DOCX": "The DOCX could not be opened or is corrupt.",
    "ENCRYPTED_PDF": "The PDF is password-protected.",
    "FILE_TOO_LARGE": "The file exceeds the configured size limit.",
    "OCR_FAILURE": "OCR failed for a page.",
    "LAYOUT_DETECTION_FAILURE": "Layout/region detection failed for a page.",
    "TABLE_EXTRACTION_FAILURE": "A table region could not be structured.",
    "FORMULA_EXTRACTION_FAILURE": "Formula recognition failed.",
    "LOW_CONFIDENCE": "The extracted block requires review.",
    "READING_ORDER_AMBIGUITY": "Reading order on this page is ambiguous.",
    "PARSING_FAILED": "Document parsing failed.",
}
FAILURE_CODES = {"UNSUPPORTED_FORMAT", "CORRUPT_PDF", "CORRUPT_DOCX", "ENCRYPTED_PDF", "FILE_TOO_LARGE", "OCR_FAILURE",
                 "LAYOUT_DETECTION_FAILURE", "TABLE_EXTRACTION_FAILURE", "FORMULA_EXTRACTION_FAILURE", "PARSING_FAILED"}


def make_error(code: str, message: Optional[str] = None, page: Optional[int] = None,
               block_id: Optional[str] = None, severity: Optional[str] = None) -> dict[str, Any]:
    return {"code": code, "message": message or ERROR_CODES.get(code, "Unknown error"), "page": page,
            "block_id": block_id, "severity": severity or ("error" if code in FAILURE_CODES else "warning")}


def error_response(code: str, message: str | None = None) -> dict[str, Any]:
    e = make_error(code, message)
    return {"status": "FAILED", "error_code": code, "message": e["message"], "errors": [e]}


def final_status(errors: list[dict], n_blocks: int) -> str:
    hard = [e for e in errors if e.get("severity") == "error"]
    if n_blocks == 0 and hard:
        return "FAILED"
    return "PARTIAL_SUCCESS" if hard else "SUCCESS"
