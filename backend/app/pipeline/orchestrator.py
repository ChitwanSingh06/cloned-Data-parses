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
from app.pipeline.failsafe import final_status, make_error
from app.pipeline.provenance import add_provenance
from app.pipeline.router import route_blocks
from app.summary.summarizer import build_summary
from app.pipeline.timing import StageTimer, compute_metrics
from app.utils.platform_utils import peak_memory_mb

log = logging.getLogger("parse-anything")


def _stats(doc: Document, elapsed: float, pages_with_regions: int) -> dict:
    blocks = doc.blocks
    return {
        "pages_processed": doc.page_count, "seconds_per_page": compute_metrics(elapsed, doc.page_count)["seconds_per_page"],
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
    timer = StageTimer()
    document_id = document_id or uuid.uuid4().hex[:12]
    filename = filename or Path(path).name
    out_dir = (out_root or PROCESSED_DIR) / document_id
    out_dir.mkdir(parents=True, exist_ok=True)
    try:
        detected = detect_document(path, size_limit_mb=MAX_UPLOAD_MB, timer=timer)
        with timer.stage("layout_analysis"):  # region routing / block building (table time is split out)
            extracted = route_blocks(detected, out_dir, timer)
        with timer.stage("assembly"):
            doc = assemble_document(extracted, document_id, filename)
        with timer.stage("validation"):
            add_confidence(doc)
            add_provenance(doc)
    except Exception as exc:  # last-resort guard: still return a structured document
        log.exception("pipeline crashed")
        from app.pipeline.failsafe import make_error
        doc = Document(document_id=document_id, filename=filename, errors=[make_error("PARSING_FAILED", str(exc))])
    doc.status = final_status(doc.errors, len(doc.blocks))
    doc.format = "pdf"
    doc.stats = _stats(doc, time.perf_counter() - t0, 0)
    with timer.stage("summary"):
        try:
            doc.summary = build_summary(doc)
        except Exception:  # a summary problem must never fail the parse
            log.exception("summary failed")
            doc.summary = {}
    with timer.stage("output_generation"):
        payload = doc.model_dump(mode="json")
        build_json(payload)  # serialisation cost is measured here; the file is written once, after timing is final
        (out_dir / "document.md").write_text(build_markdown(payload), encoding="utf-8", newline="\n")
    elapsed = time.perf_counter() - t0
    doc.processing_time = round(elapsed, 3)
    doc.timing = {**compute_metrics(elapsed, doc.page_count), "stages": timer.as_dict()}
    doc.stats["seconds_per_page"] = doc.timing["seconds_per_page"]
    payload = doc.model_dump(mode="json")  # the single JSON write carries the complete timing
    (out_dir / "document.json").write_text(build_json(payload), encoding="utf-8", newline="\n")
    return doc


def parse_document(path: str, document_id: Optional[str] = None, filename: Optional[str] = None,
                   out_root: Optional[Path] = None) -> Document:
    """Format-aware entry point. Existing PDF parsing remains unchanged."""
    suffix = Path(path).suffix.lower()
    if suffix == ".pdf":
        return parse_pdf(path, document_id=document_id, filename=filename, out_root=out_root)
    if suffix == ".docx":
        from app.formats.docx_handler import parse_docx
        return parse_docx(path, document_id=document_id, filename=filename, out_root=out_root)
    if suffix == ".pptx":
        from app.formats.pptx_handler import parse_pptx
        return parse_pptx(path, document_id=document_id, filename=filename, out_root=out_root)
    if suffix == ".xlsx":
        from app.formats.xlsx_handler import parse_xlsx
        return parse_xlsx(path, document_id=document_id, filename=filename, out_root=out_root)
    doc_id = document_id or uuid.uuid4().hex[:12]
    name = filename or Path(path).name
    return Document(document_id=doc_id, filename=name, format=suffix.lstrip(".") or "unknown",
                    status="FAILED", errors=[make_error(
                        "UNSUPPORTED_FORMAT", f"Unsupported extension '{suffix}'. Only PDF, DOCX, PPTX and XLSX are supported.")])
