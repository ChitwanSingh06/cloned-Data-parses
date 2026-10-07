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
from pptx.shapes.picture import Picture  # PlaceholderPicture subclasses Picture

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
OCR_MIN_PIXELS = 24          # ignore icons / bullets smaller than this
OCR_MIN_LONG_SIDE = 2000     # upscale small slide images so OCR (especially Devanagari) has enough detail
OCR_MIN_WORD_CONF = 0.25


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


def _text_blocks(shape, slide_number: int, shape_index: int, block_counter: list[int], bbox=None) -> list[Block]:
    paragraphs = [p for p in shape.text_frame.paragraphs if p.text.strip()]
    if not paragraphs:
        return []
    meta_base = _shape_meta(shape, slide_number, shape_index)
    bbox = bbox or _shape_bbox(shape)
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


def _table_block(shape, slide_number: int, shape_index: int, block_counter: list[int], bbox=None) -> Block:
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
        page=slide_number, bbox=bbox or _shape_bbox(shape), extractor="python-pptx:table",
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


def _is_picture(shape) -> bool:
    """Plain pictures and picture placeholders (which report shape_type PLACEHOLDER)."""
    return isinstance(shape, Picture) or getattr(shape, "shape_type", None) == MSO_SHAPE_TYPE.PICTURE


def _flatten_shapes(shapes, tx=None):
    """Yield (shape, bbox_pt) for every shape, recursing into groups and mapping child coordinates to slide space.

    tx = (ox, oy, sx, sy): x_slide = ox + x * sx. Group children live in the group's child coordinate space.
    """
    for shape in shapes:
        try:
            l, t, w, h = shape.left, shape.top, shape.width, shape.height
            if None in (l, t, w, h):
                raise ValueError("no geometry")
            if tx:
                ox, oy, sx, sy = tx
                l, t, w, h = ox + l * sx, oy + t * sy, w * sx, h * sy
            bbox = [round(l / EMU_PER_POINT, 2), round(t / EMU_PER_POINT, 2), round((l + w) / EMU_PER_POINT, 2), round((t + h) / EMU_PER_POINT, 2)]
        except Exception:
            bbox = None
        if getattr(shape, "shape_type", None) == MSO_SHAPE_TYPE.GROUP:
            try:
                xfrm = shape._element.grpSpPr.xfrm
                gl, gt, gw, gh = (shape.left, shape.top, shape.width, shape.height)
                cl, ct, cw, ch = xfrm.chOff.x, xfrm.chOff.y, xfrm.chExt.cx, xfrm.chExt.cy
                sx, sy = (gw / cw if cw else 1.0), (gh / ch if ch else 1.0)
                base = (0.0, 0.0, 1.0, 1.0) if not tx else tx
                # child -> group-local slide coords -> outer transform
                gx, gy = gl + (-cl) * sx, gt + (-ct) * sy
                if tx:
                    gx, gy = base[0] + gx * base[2], base[1] + gy * base[3]
                    sx, sy = sx * base[2], sy * base[3]
                inner = (gx, gy, sx, sy)
            except Exception:
                inner = tx
            yield from _flatten_shapes(shape.shapes, inner)
            continue
        yield shape, bbox


def _ocr_picture(img: Image.Image, shape_bbox: list[float] | None, slide_number: int, shape_index: int,
                 block_counter: list[int]) -> list[Block]:
    """OCR an embedded picture (English + Hindi + Tamil) and return text blocks positioned in slide coordinates."""
    from app.extractors.ocr.image_preprocessor import preprocess_image
    from app.extractors.ocr.ocr_engine import extract_ocr

    if img.width < OCR_MIN_PIXELS or img.height < OCR_MIN_PIXELS:
        return []
    rgb = Image.new("RGB", img.size, "white")
    rgb.paste(img.convert("RGBA"), mask=img.convert("RGBA").split()[-1])
    long_side = max(rgb.size)
    if long_side < OCR_MIN_LONG_SIDE:
        f = OCR_MIN_LONG_SIDE / long_side
        rgb = rgb.resize((int(rgb.width * f), int(rgb.height * f)), Image.LANCZOS)
    lines, engine = extract_ocr(preprocess_image(rgb))
    lines = [ln for ln in lines if ln["text"].strip() and ln["confidence"] >= OCR_MIN_WORD_CONF]
    if not lines:
        return []
    W, H = rgb.size
    x0, y0, x1, y1 = shape_bbox or [0.0, 0.0, float(W), float(H)]

    def to_slide(b):
        return [round(x0 + b[0] / W * (x1 - x0), 2), round(y0 + b[1] / H * (y1 - y0), 2),
                round(x0 + b[2] / W * (x1 - x0), 2), round(y0 + b[3] / H * (y1 - y0), 2)]

    heights = sorted(ln["height"] for ln in lines)
    median_h = heights[len(heights) // 2] or 1
    paragraphs: dict[tuple, list[dict]] = {}
    for ln in lines:
        paragraphs.setdefault((ln["block"], ln["par"]), []).append(ln)
    blocks: list[Block] = []
    for pi, group in enumerate(sorted(paragraphs.values(), key=lambda g: (min(l["bbox"][1] for l in g), min(l["bbox"][0] for l in g)))):
        text = " ".join(l["text"] for l in sorted(group, key=lambda l: l["bbox"][1])).strip()
        bb = [min(l["bbox"][0] for l in group), min(l["bbox"][1] for l in group),
              max(l["bbox"][2] for l in group), max(l["bbox"][3] for l in group)]
        conf = round(sum(l["confidence"] for l in group) / len(group), 3)
        heading = len(group) == 1 and group[0]["height"] >= 1.6 * median_h and len(text) <= 120
        block_counter[0] += 1
        blocks.append(Block(
            id=f"PX{block_counter[0]:04d}", type=BlockType.heading if heading else BlockType.paragraph, content=text,
            page=slide_number, bbox=to_slide(bb), extractor=f"ocr:{engine}", level=2 if heading else None,
            meta={**{"source_type": "pptx", "slide_number": slide_number, "shape_index": shape_index,
                     "region_id": f"PX{slide_number:03d}_{shape_index:03d}_ocr{pi}"},
                  "paragraph_index": pi, "slide_region": "image_text", "text_kind": "printed", "ocr_engine": engine,
                  "ocr_languages": "eng+hin+tam"},
            signals={"ocr": conf, "classification": 0.8 if heading else 0.85},
        ))
    return blocks


def _extract_slide(slide, slide_number: int, slide_width: int, slide_height: int, out_dir: Path, block_counter: list[int], image_counter: list[int]) -> tuple[Page, list[Block], list[dict[str, Any]]]:
    blocks: list[Block] = []
    errors: list[dict[str, Any]] = []
    page_blocks: list[str] = []
    text_chars = 0
    native_chars = 0
    ocr_chars = 0

    # PowerPoint shape order is the document's native shape order. This preserves
    # authored order without pretending we can reconstruct a PDF-style reading order.
    for shape_index, (shape, bbox) in enumerate(_flatten_shapes(slide.shapes)):
        try:
            if getattr(shape, "has_table", False) or shape.shape_type == MSO_SHAPE_TYPE.TABLE:
                block = _table_block(shape, slide_number, shape_index, block_counter, bbox)
                blocks.append(block)
                page_blocks.append(block.id)
                continue

            if _is_picture(shape):
                image_counter[0] += 1
                path, meta = _save_picture(shape, out_dir, slide_number, shape_index, image_counter[0])
                block_counter[0] += 1
                block = Block(
                    id=f"PX{block_counter[0]:04d}", type=BlockType.figure, content="",
                    page=slide_number, bbox=bbox, extractor="python-pptx:image",
                    meta=meta, signals={"image_extraction": 0.97 if path else 0.6},
                )
                blocks.append(block)
                page_blocks.append(block.id)
                # Text inside the picture (e.g. a slide pasted/exported as an image): OCR it, English + Hindi.
                if path:
                    try:
                        with Image.open(out_dir / path) as im:
                            im.load()
                            ocr_blocks = _ocr_picture(im, bbox, slide_number, shape_index, block_counter)
                        for ob in ocr_blocks:
                            text_chars += len(str(ob.content))
                            ocr_chars += len(str(ob.content))
                            blocks.append(ob)
                            page_blocks.append(ob.id)
                    except Exception as exc:
                        errors.append(make_error("OCR_FAILURE", f"Slide {slide_number}, image {shape_index}: {exc}", page=slide_number, severity="warning"))
                continue

            if getattr(shape, "has_text_frame", False):
                text_blocks = _text_blocks(shape, slide_number, shape_index, block_counter, bbox)
                for block in text_blocks:
                    text_chars += len(str(block.content)) if block.type != BlockType.list else sum(len(x) for x in block.content["items"])
                    native_chars += len(str(block.content)) if block.type != BlockType.list else sum(len(x) for x in block.content["items"])
                    blocks.append(block)
                    page_blocks.append(block.id)
        except Exception as exc:
            errors.append(make_error("PARSING_FAILED", f"Slide {slide_number}, shape {shape_index}: {exc}", page=slide_number, severity="warning"))

    page = Page(
        page_number=slide_number,
        width=_pt(slide_width),
        height=_pt(slide_height),
        is_scanned=False, text_chars=text_chars, source="ocr" if ocr_chars and not native_chars else "digital", blocks=page_blocks,
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
