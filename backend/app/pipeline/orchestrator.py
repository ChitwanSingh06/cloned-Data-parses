"""PDF -> detect -> route/extract -> assemble -> confidence -> provenance -> canonical Document -> JSON + MD."""
import logging
import time
import uuid
from collections import Counter
from pathlib import Path
from typing import Optional

from app.core.config import MAX_UPLOAD_MB, PROCESSED_DIR
from app.models.document import Document
from app.output.json_builder import build_json
from app.output.markdown_builder import build_markdown
from app.pipeline.assembler import assemble_document
from app.pipeline.confidence import add_confidence
from app.pipeline.detector import detect_document
from app.pipeline.failsafe import final_status
from app.pipeline.provenance import add_provenance
from app.pipeline.router import route_blocks
from app.utils.platform_utils import peak_memory_mb

log = logging.getLogger("parse-anything")


def _stats(doc: Document, elapsed: float, pages_with_regions: int) -> dict:
    blocks = doc.blocks
    return {
        "pages_processed": doc.page_count, "seconds_per_page": round(elapsed / max(doc.page_count, 1), 3),
        "peak_memory_mb": peak_memory_mb(),
        "scanned_pages": sum(p.is_scanned for p in doc.pages), "digital_pages": sum(not p.is_scanned for p in doc.pages),
        "blocks_by_type": dict(Counter(b.type.value for b in blocks)),
        "review_required": sum(b.status.value == "REVIEW_REQUIRED" for b in blocks),
        "confidence_levels": dict(Counter(b.confidence_level.value for b in blocks)),
        "mean_confidence": round(sum(b.confidence for b in blocks) / len(blocks), 3) if blocks else 0.0,
        "errors": sum(e["severity"] == "error" for e in doc.errors), "warnings": sum(e["severity"] == "warning" for e in doc.errors),
    }


def parse_pdf(path: str, document_id: Optional[str] = None, filename: Optional[str] = None,
              out_root: Optional[Path] = None) -> Document:
    t0 = time.perf_counter()
    document_id = document_id or uuid.uuid4().hex[:12]
    filename = filename or Path(path).name
    out_dir = (out_root or PROCESSED_DIR) / document_id
    out_dir.mkdir(parents=True, exist_ok=True)
    try:
        detected = detect_document(path, size_limit_mb=MAX_UPLOAD_MB)
        extracted = route_blocks(detected, out_dir)
        doc = assemble_document(extracted, document_id, filename)
        add_confidence(doc)
        add_provenance(doc)
    except Exception as exc:  # last-resort guard: still return a structured document
        log.exception("pipeline crashed")
        from app.pipeline.failsafe import make_error
        doc = Document(document_id=document_id, filename=filename, errors=[make_error("PARSING_FAILED", str(exc))])
    elapsed = time.perf_counter() - t0
    doc.processing_time = round(elapsed, 3)
    doc.status = final_status(doc.errors, len(doc.blocks))
    doc.stats = _stats(doc, elapsed, 0)
    payload = doc.model_dump(mode="json")
    (out_dir / "document.json").write_text(build_json(payload), encoding="utf-8", newline="\n")
    (out_dir / "document.md").write_text(build_markdown(payload), encoding="utf-8", newline="\n")
    return doc
