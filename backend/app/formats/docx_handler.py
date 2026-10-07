"""DOCX -> canonical Document extraction.

DOCX does not expose PDF-style page coordinates through python-docx, so this handler
uses one logical document unit (page=1) solely because the canonical models require
an integer location. Structural provenance is kept in block metadata/provenance.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from docx import Document as DocxDocument
from docx.oxml.ns import qn

from app.models.block import Block, BlockType
from app.models.document import Document, Page
from app.models.table import Cell, TableData
from app.pipeline.failsafe import make_error
from app.pipeline.timing import StageTimer, compute_metrics

_LOGICAL_PAGE = 1
_LIST_STYLE_RE = re.compile(r"^list\s+(bullet|number)(?:\s+\d+)?$", re.I)
_HEADING_RE = re.compile(r"^heading\s+([1-9])$", re.I)


def _style_name(paragraph) -> str:
    try:
        return paragraph.style.name or ""
    except Exception:
        return ""


def _list_kind(paragraph) -> bool | None:
    """Return ordered=True/False for basic Word list paragraphs, else None."""
    style = _style_name(paragraph)
    m = _LIST_STYLE_RE.match(style.strip())
    if m:
        return m.group(1).lower() == "number"

    # Some documents use a custom style but still carry Word numbering metadata.
    ppr = paragraph._p.get_or_add_pPr()
    num_pr = ppr.find(qn("w:numPr"))
    if num_pr is None:
        return None
    ilvl = num_pr.find(qn("w:ilvl"))
    num_id = num_pr.find(qn("w:numId"))
    if num_id is None:
        return None
    # The numbering definition is not needed to preserve the item; when a custom
    # numbered paragraph is present, treat it as ordered. Bullet styles are handled
    # above, and explicit numPr without a known style is the safer ordered fallback.
    return True


def _heading_level(paragraph) -> int | None:
    m = _HEADING_RE.match(_style_name(paragraph).strip())
    return int(m.group(1)) if m else None


def _run_style_info(paragraph) -> dict[str, Any]:
    runs = [r for r in paragraph.runs if r.text.strip()]
    if not runs:
        return {}
    bold = sum(bool(r.bold) for r in runs)
    italic = sum(bool(r.italic) for r in runs)
    sizes = [r.font.size.pt for r in runs if r.font.size is not None]
    return {
        "style": _style_name(paragraph),
        "bold_ratio": round(bold / len(runs), 3),
        "italic_ratio": round(italic / len(runs), 3),
        "font_size_pt": round(sum(sizes) / len(sizes), 2) if sizes else None,
    }


def _drawing_rel_ids(paragraph) -> list[str]:
    rels: list[str] = []
    for blip in paragraph._p.xpath(".//a:blip"):
        rid = blip.get(qn("r:embed"))
        if rid:
            rels.append(rid)
    return rels


def _table_cell_span(tc) -> tuple[int, int]:
    tc_pr = tc.tcPr
    grid_span = tc_pr.find(qn("w:gridSpan")) if tc_pr is not None else None
    colspan = int(grid_span.get(qn("w:val"), "1")) if grid_span is not None else 1
    # python-docx does not expose a high-level merged-cell API. vMerge is reliable
    # enough to mark a vertically merged continuation without inventing a span.
    vmerge = tc_pr.find(qn("w:vMerge")) if tc_pr is not None else None
    rowspan = 1
    if vmerge is not None and vmerge.get(qn("w:val")) == "restart":
        rowspan = 1
    return max(1, rowspan), max(1, colspan)


def _extract_table(table, table_index: int) -> tuple[TableData, list[dict[str, Any]]]:
    n_rows = len(table.rows)
    n_cols = max((len(r.cells) for r in table.rows), default=0)
    cells: list[Cell] = []
    rows: list[list[str]] = []
    source_cells: list[dict[str, Any]] = []
    for ri, row in enumerate(table.rows):
        vals: list[str] = []
        for ci, cell in enumerate(row.cells):
            text = "\n".join(p.text.strip() for p in cell.paragraphs if p.text.strip()).strip()
            rowspan, colspan = _table_cell_span(cell._tc)
            vals.append(text)
            cells.append(Cell(row=ri, col=ci, text=text, rowspan=rowspan, colspan=colspan, is_header=ri == 0))
            source_cells.append({"table_index": table_index, "row": ri, "column": ci,
                                 "rowspan": rowspan, "colspan": colspan})
        rows.append(vals)

    header_rows = 1 if rows else 0
    headers = [rows[0][:n_cols]] if rows else []
    body = rows[1:] if len(rows) > 1 else []
    data = TableData(n_rows=n_rows, n_cols=n_cols, header_rows=header_rows,
                     headers=headers, rows=body, cells=cells, page_span=[_LOGICAL_PAGE])
    return data, source_cells


def _image_size_from_rel(document, rid: str) -> tuple[int | None, int | None]:
    try:
        part = document.part.related_parts[rid]
        return getattr(part, "image", None).size if getattr(part, "image", None) is not None else (None, None)
    except Exception:
        return None, None


def _make_block(block_type: BlockType, content: Any, block_index: int, *, meta: dict[str, Any],
                extractor: str = "python-docx", signals: dict[str, float] | None = None,
                level: int | None = None) -> Block:
    return Block(
        id=f"DX{block_index:04d}", type=block_type, content=content, page=_LOGICAL_PAGE,
        bbox=None, confidence=0.0, extractor=extractor, level=level,
        meta={"source_type": "docx", "region_id": f"DX{block_index:04d}", **meta}, signals=signals or {"structural_extraction": 0.95},
    )


def _extract_body(path: str, document_id: str, filename: str, out_dir: Path | None = None) -> tuple[Document, int]:
    docx = DocxDocument(path)
    blocks: list[Block] = []
    errors: list[dict[str, Any]] = []
    paragraph_index = 0
    table_index = 0
    image_index = 0
    logical_order = 0
    pending_list: Block | None = None

    def flush_list() -> None:
        nonlocal pending_list
        if pending_list is not None:
            blocks.append(pending_list)
            pending_list = None

    def next_index() -> int:
        nonlocal logical_order
        logical_order += 1
        return logical_order

    # Iterate body XML children rather than document.paragraphs + document.tables,
    # because the latter loses the original paragraph/table interleaving.
    body = docx.element.body
    for child in body.iterchildren():
        tag = child.tag
        if tag == qn("w:p"):
            from docx.text.paragraph import Paragraph
            paragraph = Paragraph(child, docx._body)
            text = paragraph.text.strip()
            ordered = _list_kind(paragraph)
            heading = _heading_level(paragraph)
            style = _style_name(paragraph)
            image_rids = _drawing_rel_ids(paragraph)
            current_paragraph_index = paragraph_index
            paragraph_index += 1

            if ordered is not None and text:
                if pending_list is None or pending_list.content["ordered"] != ordered:
                    flush_list()
                    pending_list = _make_block(
                        BlockType.list, {"ordered": ordered, "items": [text]}, next_index(),
                        meta={"paragraph_index": current_paragraph_index, "style": style,
                              "item_sources": [{"source_type": "docx", "paragraph_index": current_paragraph_index}]},
                        signals={"structural_extraction": 0.98, "list_classification": 0.95},
                    )
                else:
                    pending_list.content["items"].append(text)
                    pending_list.meta.setdefault("item_sources", []).append(
                        {"source_type": "docx", "paragraph_index": current_paragraph_index})
                    pending_list.signals["list_classification"] = min(pending_list.signals.get("list_classification", 0.95), 0.95)
            else:
                flush_list()
                if text:
                    if heading is not None:
                        block_type = BlockType.heading
                        level = heading
                    elif style.lower() == "caption" or re.match(r"^(table|figure)\s*\d*[:.\-]", text, re.I):
                        block_type = BlockType.caption
                        level = None
                    else:
                        block_type = BlockType.paragraph
                        level = None
                    blocks.append(_make_block(
                        block_type, text, next_index(), level=level,
                        meta={"paragraph_index": current_paragraph_index, **_run_style_info(paragraph)},
                        signals={"structural_extraction": 0.99, "style_classification": 0.97 if (heading or style) else 0.9},
                    ))

            # Embedded images are preserved as figure blocks. DOCX has no trustworthy
            # PDF-style coordinates, so only relationship/image metadata is recorded.
            for rid in image_rids:
                image_index += 1
                width, height = _image_size_from_rel(docx, rid)
                image_path = None
                try:
                    part = docx.part.related_parts[rid]
                    blob = part.blob
                    filename_hint = getattr(part, "filename", None) or f"image_{image_index}.png"
                    ext = Path(filename_hint).suffix.lower() or ".png"
                    if ext not in {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp", ".tif", ".tiff"}:
                        ext = ".png"
                    if out_dir is not None:
                        image_dir = out_dir / "figures"
                        image_dir.mkdir(parents=True, exist_ok=True)
                        target = image_dir / f"docx_image_{image_index:03d}{ext}"
                        target.write_bytes(blob)
                        image_path = f"figures/{target.name}"
                except Exception as exc:
                    errors.append(make_error("PARSING_FAILED", f"Embedded image {image_index} could not be saved: {exc}",
                                             page=_LOGICAL_PAGE, severity="warning"))
                meta = {"image_index": image_index, "paragraph_index": current_paragraph_index,
                        "relationship_id": rid, "image_width_px": width, "image_height_px": height}
                if image_path:
                    meta["image_path"] = image_path
                blocks.append(_make_block(
                    BlockType.figure, "", next_index(), meta=meta, extractor="python-docx:image",
                    signals={"image_extraction": 0.95 if image_path else 0.7},
                ))
        elif tag == qn("w:tbl"):
            flush_list()
            from docx.table import Table
            table = Table(child, body)
            data, source_cells = _extract_table(table, table_index)
            blocks.append(_make_block(
                BlockType.table, data.model_dump(), next_index(),
                meta={"table_index": table_index, "cell_sources": source_cells,
                      "n_rows": data.n_rows, "n_cols": data.n_cols},
                extractor="python-docx:table",
                signals={"table_structure": 0.98 if data.n_rows and data.n_cols else 0.45},
            ))
            table_index += 1
        elif tag == qn("w:sectPr"):
            # Section properties are layout metadata, not a content block.
            continue
    flush_list()

    page = Page(page_number=_LOGICAL_PAGE, width=0.0, height=0.0, is_scanned=False,
                text_chars=sum(len(str(b.content)) for b in blocks if b.type in (BlockType.heading, BlockType.paragraph)))
    page.source = "digital"
    page.blocks = [b.id for b in blocks]
    document = Document(document_id=document_id, filename=filename, format="docx", page_count=1, pages=[page], blocks=blocks, errors=errors)
    return document, logical_order


def parse_docx(path: str, document_id: str | None = None, filename: str | None = None,
               out_root: Path | None = None) -> Document:
    """Parse a DOCX into the existing canonical Document model and outputs."""
    import time
    from app.core.config import PROCESSED_DIR
    from app.output.json_builder import build_json
    from app.output.markdown_builder import build_markdown
    from app.pipeline.confidence import add_confidence
    from app.pipeline.provenance import add_provenance
    from app.pipeline.failsafe import final_status
    from app.summary.summarizer import build_summary
    from app.utils.platform_utils import peak_memory_mb

    t0 = time.perf_counter()
    timer = StageTimer()
    document_id = document_id or __import__("uuid").uuid4().hex[:12]
    filename = filename or Path(path).name
    out_dir = (out_root or PROCESSED_DIR) / document_id
    out_dir.mkdir(parents=True, exist_ok=True)
    try:
        with timer.stage("ingestion"):
            doc, units = _extract_body(path, document_id, filename, out_dir)
        with timer.stage("assembly"):
            # DOCX order is already supplied by the body XML traversal. No PDF bbox
            # reading-order algorithm is applied.
            pass
        with timer.stage("validation"):
            add_confidence(doc)
            add_provenance(doc)
        doc.status = final_status(doc.errors, len(doc.blocks))
        with timer.stage("summary"):
            try:
                doc.summary = build_summary(doc)
            except Exception as exc:
                doc.summary = {}
                doc.errors.append(make_error("PARSING_FAILED", f"Summary generation failed: {exc}", severity="warning"))
        with timer.stage("output_generation"):
            payload = doc.model_dump(mode="json")
            (out_dir / "document.md").write_text(build_markdown(payload), encoding="utf-8", newline="\n")
        elapsed = time.perf_counter() - t0
        doc.processing_time = round(elapsed, 3)
        metrics = compute_metrics(elapsed, 0)
        doc.timing = {**metrics, "logical_units_processed": units, "unit_label": "logical document elements",
                      "stages": timer.as_dict()}
        doc.stats = {
            "pages_processed": 0,
            "logical_units_processed": units,
            "unit_label": "logical document elements",
            "seconds_per_page": metrics["seconds_per_page"],
            "peak_memory_mb": peak_memory_mb(),
            "scanned_pages": 0,
            "digital_pages": 1,
            "blocks_by_type": {k.value: sum(b.type == k for b in doc.blocks) for k in BlockType if any(b.type == k for b in doc.blocks)},
            "review_required": sum(b.status.value == "REVIEW_REQUIRED" for b in doc.blocks),
            "confidence_levels": {},
            "mean_confidence": round(sum(b.confidence for b in doc.blocks) / len(doc.blocks), 3) if doc.blocks else 0.0,
            "errors": sum(e.get("severity") == "error" for e in doc.errors),
            "warnings": sum(e.get("severity") == "warning" for e in doc.errors),
        }
        # Keep the canonical stats shape used by PDF while avoiding a fake physical page count.
        from collections import Counter
        doc.stats["confidence_levels"] = dict(Counter(b.confidence_level.value for b in doc.blocks))
        payload = doc.model_dump(mode="json")
        (out_dir / "document.json").write_text(build_json(payload), encoding="utf-8", newline="\n")
        return doc
    except Exception as exc:
        from app.pipeline.failsafe import make_error
        doc = Document(document_id=document_id, filename=filename, format="docx",
                       errors=[make_error("CORRUPT_DOCX" if isinstance(exc, (ValueError, OSError, RuntimeError)) else "PARSING_FAILED", str(exc))], status="FAILED")
        return doc


def handle_docx(path: str, **kw) -> Document:
    return parse_docx(path, **kw)
