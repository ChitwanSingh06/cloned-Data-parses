"""Route detected regions to specialised extractors and build typed Blocks."""
import logging
from pathlib import Path
from typing import Optional

import pymupdf

from app.extractors.charts.chart_extractor import extract_chart
from app.extractors.equations.equation_extractor import extract_equation
from app.extractors.figures.figure_extractor import extract_figure, save_crop
from app.extractors.tables.table_extractor import extract_table
from app.models.block import Block, BlockType
from app.pipeline.failsafe import make_error

log = logging.getLogger("parse-anything")


def _text_block(r: dict) -> Block:
    t = BlockType(r["hint"])
    content = r["text"]
    meta = dict(r.get("meta", {}))
    if t == BlockType.list:
        content = {"ordered": bool(meta.get("ordered")), "items": [meta.pop("text_without_marker", r["text"])]}
    return Block(id=r["id"], type=t, content=content, page=r["page"], bbox=r["bbox"], extractor=r["source"],
                 meta={**meta, "region_id": r["id"], "line_boxes": r.get("line_boxes", [])},
                 signals=dict(r.get("signals", {})))


def route_blocks(detected: dict, out_dir: Optional[Path] = None) -> dict:
    blocks: list[Block] = []
    errors: list[dict] = list(detected.get("errors", []))
    doc = None
    if detected.get("regions") and detected["format"] == "pdf":
        doc = pymupdf.open(detected["path"])
    try:
        for r in detected.get("regions", []):
            page = doc[r["page"] - 1] if doc is not None else None
            rid = r["id"]
            try:
                if r["type"] == "text":
                    blocks.append(_text_block(r))
                elif r["type"] == "table":
                    try:
                        res = extract_table(r, words=r.get("words"))
                        blocks.append(Block(id=rid, type=BlockType.table, content=res["table"].model_dump(), page=r["page"],
                                            bbox=r["bbox"], extractor=f"table:{r.get('strategy')}", signals=res["signals"],
                                            meta={**res["meta"], "region_id": rid}))
                    except Exception as exc:
                        errors.append(make_error("TABLE_EXTRACTION_FAILURE", f"{exc}", page=r["page"], block_id=rid))
                        meta = {"region_id": rid, "fallback_for": "table", "review_reason": "Table structure could not be extracted; region preserved as image."}
                        if page is not None and out_dir is not None:
                            meta["image_path"] = f"figures/{save_crop(page, r['bbox'], out_dir / 'figures' / f'{rid}.png')}"
                        blocks.append(Block(id=rid, type=BlockType.figure, content="", page=r["page"], bbox=r["bbox"],
                                            extractor="table:fallback", signals={"table_detection": 0.3}, meta=meta))
                elif r["type"] == "figure":
                    res = extract_figure(r, page, out_dir, rid)
                    blocks.append(Block(id=rid, type=BlockType.figure, content="", page=r["page"], bbox=r["bbox"],
                                        extractor=f"figure:{r.get('source')}", signals=res["signals"],
                                        meta={**res["meta"], "region_id": rid, "n_paths": r.get("n_paths", 0)}))
                elif r["type"] == "equation":
                    res = extract_equation(r, page, out_dir, rid)
                    latex = res["meta"].get("latex")
                    if r.get("signals"):
                        res["signals"].update({k: v for k, v in r["signals"].items() if k in ("ocr", "text_layer")})
                    if res["meta"].get("formula_error"):
                        errors.append(make_error("FORMULA_EXTRACTION_FAILURE", res["meta"]["formula_error"], page=r["page"], block_id=rid))
                    blocks.append(Block(id=rid, type=BlockType.equation, content=latex or r.get("text", ""), page=r["page"],
                                        bbox=r["bbox"], extractor=res["meta"].get("recognizer") or r["source"],
                                        signals=res["signals"], meta={**res["meta"], **r.get("meta", {}), "region_id": rid}))
            except Exception as exc:
                log.exception("region %s failed", rid)
                errors.append(make_error("PARSING_FAILED", f"Region {rid} failed: {exc}", page=r["page"], block_id=rid))
    finally:
        if doc is not None:
            doc.close()
    return {**detected, "blocks": blocks, "errors": errors}
