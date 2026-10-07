"""PPTX -> canonical Document extraction.

Each PowerPoint slide is treated as one logical page. python-pptx exposes slide
coordinates in EMU, which are converted to points for honest slide-region bboxes;
these are not PDF page coordinates.
"""
from __future__ import annotations

import re
import time
import uuid
from pathlib import Path
from typing import Any

from PIL import Image
from io import BytesIO
from pptx import Presentation
from pptx.enum.shapes import MSO_SHAPE_TYPE
from pptx.enum.text import PP_ALIGN
from pptx.oxml.ns import qn

from app.core.config import PROCESSED_DIR
from app.models.block import Block, BlockType
from app.models.document import Document, Page
from app.models.table import Cell, TableData
from app.output.json_builder import build_json
from app.output.markdown_builder import build_markdown
from app.pipeline.confidence import add_confidence
from app.pipeline.failsafe import final_status, make_error
from app.pipeline.provenance import add_provenance
from app.pipeline.timing import StageTimer, compute_metrics
from app.summary.summarizer import build_summary
from app.utils.platform_utils import peak_memory_mb

EMU_PER_POINT = 12700.0


def _pt(value: int | float | None) -> float:
    return round(float(value or 0) / EMU_PER_POINT, 2)


def _shape_bbox(shape) -> list[float] | None:
    try:
        return [_pt(shape.left), _pt(shape.top), _pt(shape.left + shape.width), _pt(shape.top + shape.height)]
    except Exception:
        return None


def _shape_meta(shape, slide_number: int, shape_index: int) -> dict[str, Any]:
    meta: dict[str, Any] = {
        "source_type": "pptx",
        "slide_number": slide_number,
        "shape_index": shape_index,
        "region_id": f"PX{slide_number:03d}_{shape_index:03d}",
    }
    try:
        meta["shape_type"] = str(shape.shape_type)
    except Exception:
        pass
    try:
        if shape.name:
            meta["shape_name"] = shape.name
    except Exception:
        pass
    return meta


def _has_bullet(paragraph) -> bool:
    """Detect explicit bullet/numbering XML without assuming visual glyphs."""
    try:
        ppr = paragraph._p.get_or_add_pPr()
        if ppr.find(qn("a:buChar")) is not None or ppr.find(qn("a:buAutoNum")) is not None:
            return True
        # Inherited theme/list styles can expose a level without a direct marker.
        return paragraph.level > 0
    except Exception:
        return False


def _list_ordered(paragraph) -> bool:
    try:
        ppr = paragraph._p.get_or_add_pPr()
        auto = ppr.find(qn("a:buAutoNum"))
        if auto is not None:
            return True
    except Exception:
        pass
    return False


def _font_info(paragraph) -> dict[str, Any]:
    runs = [r for r in paragraph.runs if r.text.strip()]
    sizes = [r.font.size.pt for r in runs if r.font.size is not None]
    return {
        "bold_ratio": round(sum(bool(r.font.bold) for r in runs) / len(runs), 3) if runs else 0.0,
        "italic_ratio": round(sum(bool(r.font.italic) for r in runs) / len(runs), 3) if runs else 0.0,
        "font_size_pt": round(max(sizes), 2) if sizes else None,
    }


def _is_title_shape(shape) -> bool:
    try:
        return bool(shape.is_placeholder and shape.placeholder_format.type in (1, 3))  # TITLE/CENTER_TITLE
    except Exception:
        return False


def _is_subtitle_shape(shape) -> bool:
    try:
        return bool(shape.is_placeholder and shape.placeholder_format.type == 4)  # SUBTITLE
    except Exception:
        return False


def _text_blocks(shape, slide_number: int, shape_index: int, block_counter: list[int]) -> list[Block]:
    paragraphs = [p for p in shape.text_frame.paragraphs if p.text.strip()]
    if not paragraphs:
        return []
    meta_base = _shape_meta(shape, slide_number, shape_index)
    bbox = _shape_bbox(shape)
    blocks: list[Block] = []
    pending: Block | None = None

    def flush() -> None:
        nonlocal pending
        if pending is not None:
            blocks.append(pending)
            pending = None

    for pi, paragraph in enumerate(paragraphs):
        text = paragraph.text.strip()
        is_list = _has_bullet(paragraph)
        ordered = _list_ordered(paragraph)
        if is_list:
            if pending is None or pending.content["ordered"] != ordered:
                flush()
                block_counter[0] += 1
                pending = Block(
                    id=f"PX{block_counter[0]:04d}", type=BlockType.list,
                    content={"ordered": ordered, "items": [text]}, page=slide_number,
                    bbox=bbox, extractor="python-pptx:text", meta={
                        **meta_base, "paragraph_index": pi,
                        "slide_region": "text", "item_sources": [{"paragraph_index": pi}],
                    }, signals={"structural_extraction": 0.98, "list_classification": 0.94},
                )
            else:
                pending.content["items"].append(text)
                pending.meta.setdefault("item_sources", []).append({"paragraph_index": pi})
            continue

        flush()
        block_counter[0] += 1
        heading = _is_title_shape(shape) or (_is_subtitle_shape(shape) and pi == 0)
        level = 1 if heading else None
        block_type = BlockType.heading if heading else BlockType.paragraph
        signals = {"structural_extraction": 0.98, "style_classification": 0.96 if heading else 0.9}
        blocks.append(Block(
            id=f"PX{block_counter[0]:04d}", type=block_type, content=text, page=slide_number,
            bbox=bbox, extractor="python-pptx:text", level=level,
            meta={**meta_base, "paragraph_index": pi, "slide_region": "text", **_font_info(paragraph)},
            signals=signals,
        ))
    flush()
    return blocks


def _table_block(shape, slide_number: int, shape_index: int, block_counter: list[int]) -> Block:
    table = shape.table
    n_rows, n_cols = len(table.rows), len(table.columns)
    cells: list[Cell] = []
    rows: list[list[str]] = []
    for ri, row in enumerate(table.rows):
        vals: list[str] = []
        for ci, cell in enumerate(row.cells):
            text = cell.text.strip()
            vals.append(text)
            cells.append(Cell(row=ri, col=ci, text=text, rowspan=1, colspan=1, is_header=ri == 0))
        rows.append(vals)
    data = TableData(
        n_rows=n_rows, n_cols=n_cols, header_rows=1 if rows else 0,
        headers=[rows[0]] if rows else [], rows=rows[1:] if len(rows) > 1 else [],
        cells=cells, page_span=[slide_number],
    )
    block_counter[0] += 1
    return Block(
        id=f"PX{block_counter[0]:04d}", type=BlockType.table, content=data.model_dump(),
        page=slide_number, bbox=_shape_bbox(shape), extractor="python-pptx:table",
        meta={**_shape_meta(shape, slide_number, shape_index), "table_index": shape_index},
        signals={"table_structure": 0.98 if n_rows and n_cols else 0.4},
    )


def _save_picture(shape, out_dir: Path, slide_number: int, shape_index: int, image_index: int) -> tuple[str | None, dict[str, Any]]:
    meta = _shape_meta(shape, slide_number, shape_index)
    meta.update({"image_index": image_index})
    try:
        image = shape.image
        blob = image.blob
        with Image.open(BytesIO(blob)) as im:
            if im.mode not in ("RGB", "RGBA"):
                im = im.convert("RGBA")
            image_dir = out_dir / "figures"
            image_dir.mkdir(parents=True, exist_ok=True)
            target = image_dir / f"pptx_image_{image_index:03d}.png"
            im.save(target, format="PNG")
            meta.update({"image_path": f"figures/{target.name}", "image_width_px": im.width, "image_height_px": im.height})
            return meta["image_path"], meta
    except Exception as exc:
        meta["review_reason"] = f"Embedded image could not be extracted: {exc}"
        return None, meta


def _extract_slide(slide, slide_number: int, slide_width: int, slide_height: int, out_dir: Path, block_counter: list[int], image_counter: list[int]) -> tuple[Page, list[Block], list[dict[str, Any]]]:
    blocks: list[Block] = []
    errors: list[dict[str, Any]] = []
    page_blocks: list[str] = []
    text_chars = 0

    # PowerPoint shape order is the document's native shape order. This preserves
    # authored order without pretending we can reconstruct a PDF-style reading order.
    for shape_index, shape in enumerate(slide.shapes):
        try:
            if shape.shape_type == MSO_SHAPE_TYPE.TABLE:
                block = _table_block(shape, slide_number, shape_index, block_counter)
                blocks.append(block)
                page_blocks.append(block.id)
                continue

            if shape.shape_type == MSO_SHAPE_TYPE.PICTURE:
                image_counter[0] += 1
                path, meta = _save_picture(shape, out_dir, slide_number, shape_index, image_counter[0])
                block_counter[0] += 1
                block = Block(
                    id=f"PX{block_counter[0]:04d}", type=BlockType.figure, content="",
                    page=slide_number, bbox=_shape_bbox(shape), extractor="python-pptx:image",
                    meta=meta, signals={"image_extraction": 0.97 if path else 0.6},
                )
                blocks.append(block)
                page_blocks.append(block.id)
                continue

            if getattr(shape, "has_text_frame", False):
                text_blocks = _text_blocks(shape, slide_number, shape_index, block_counter)
                for block in text_blocks:
                    text_chars += len(str(block.content)) if block.type != BlockType.list else sum(len(x) for x in block.content["items"])
                    blocks.append(block)
                    page_blocks.append(block.id)
        except Exception as exc:
            errors.append(make_error("PARSING_FAILED", f"Slide {slide_number}, shape {shape_index}: {exc}", page=slide_number, severity="warning"))

    page = Page(
        page_number=slide_number,
        width=_pt(slide_width),
        height=_pt(slide_height),
        is_scanned=False, text_chars=text_chars, source="digital", blocks=page_blocks,
    )
    return page, blocks, errors


def parse_pptx(path: str, document_id: str | None = None, filename: str | None = None,
               out_root: Path | None = None) -> Document:
    """Parse a PPTX into the existing canonical Document model and outputs."""
    t0 = time.perf_counter()
    timer = StageTimer()
    document_id = document_id or uuid.uuid4().hex[:12]
    filename = filename or Path(path).name
    out_dir = (out_root or PROCESSED_DIR) / document_id
    out_dir.mkdir(parents=True, exist_ok=True)
    try:
        with timer.stage("ingestion"):
            prs = Presentation(path)
            slide_count = len(prs.slides)
        blocks: list[Block] = []
        pages: list[Page] = []
        errors: list[dict[str, Any]] = []
        counter = [0]
        image_counter = [0]
        with timer.stage("layout_analysis"):
            for slide_number, slide in enumerate(prs.slides, start=1):
                page, slide_blocks, slide_errors = _extract_slide(slide, slide_number, prs.slide_width, prs.slide_height, out_dir, counter, image_counter)
                pages.append(page)
                blocks.extend(slide_blocks)
                errors.extend(slide_errors)

        doc = Document(document_id=document_id, filename=filename, format="pptx", page_count=slide_count,
                       pages=pages, blocks=blocks, errors=errors)
        with timer.stage("assembly"):
            # Slide/shape order is already the canonical reading order for this format.
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

        elapsed = time.perf_counter() - t0
        doc.processing_time = round(elapsed, 3)
        doc.timing = {**compute_metrics(elapsed, slide_count), "logical_units_processed": slide_count,
                      "unit_label": "slides", "stages": timer.as_dict()}
        from collections import Counter
        doc.stats = {
            "pages_processed": slide_count,
            "logical_units_processed": slide_count,
            "unit_label": "slides",
            "seconds_per_page": doc.timing["seconds_per_page"],
            "peak_memory_mb": peak_memory_mb(), "scanned_pages": 0, "digital_pages": slide_count,
            "blocks_by_type": dict(Counter(b.type.value for b in doc.blocks)),
            "review_required": sum(b.status.value == "REVIEW_REQUIRED" for b in doc.blocks),
            "confidence_levels": dict(Counter(b.confidence_level.value for b in doc.blocks)),
            "mean_confidence": round(sum(b.confidence for b in doc.blocks) / len(doc.blocks), 3) if doc.blocks else 0.0,
            "errors": sum(e.get("severity") == "error" for e in doc.errors),
            "warnings": sum(e.get("severity") == "warning" for e in doc.errors),
        }
        payload = doc.model_dump(mode="json")
        (out_dir / "document.md").write_text(build_markdown(payload), encoding="utf-8", newline="\n")
        payload = doc.model_dump(mode="json")
        (out_dir / "document.json").write_text(build_json(payload), encoding="utf-8", newline="\n")
        return doc
    except Exception as exc:
        doc = Document(document_id=document_id, filename=filename, format="pptx", status="FAILED",
                       errors=[make_error("CORRUPT_PPTX" if isinstance(exc, (ValueError, OSError, RuntimeError)) else "PARSING_FAILED", str(exc))])
        return doc


def handle_pptx(path: str, **kw) -> Document:
    return parse_pptx(path, **kw)
