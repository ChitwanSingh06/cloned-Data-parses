"""Stage 2 — assemble: header/footer removal, reading order, captions, cross-page merges, hierarchy."""
import math
import re
from collections import Counter, defaultdict
from typing import Optional

from app.extractors.charts.chart_detector import looks_like_chart
from app.extractors.charts.chart_extractor import extract_chart
from app.extractors.tables.table_extractor import column_labels
from app.extractors.text.pdf_text import PAGE_NUM_RE
from app.extractors.text.reading_order import sort_reading_order
from app.models.block import Block, BlockType
from app.models.document import Document, Page
from app.models.table import TableData
from app.pipeline.failsafe import make_error
from app.utils.bbox import union

TERMINAL = re.compile(r"[.!?:;\"”’)\]]$")
REF_HEAD = re.compile(r"^\s*(references|bibliography|works cited|citations)\s*$", re.I)
REF_ITEM = re.compile(r"^\s*(\[\d+\]|\d+\.|\(\d+\))\s+\S")
HEAD_NUM = re.compile(r"^\s*(\d+(?:\.\d+)*)[.)]?\s")


def _norm(t: str) -> str:
    return re.sub(r"\d+", "#", re.sub(r"\s+", " ", str(t).lower())).strip()


def _classify_margins(blocks: list[Block], n_pages: int) -> None:
    margin = [b for b in blocks if b.meta.get("margin") and isinstance(b.content, str)]
    keys: dict[str, set[int]] = defaultdict(set)
    for b in margin:
        keys[_norm(b.content)].add(b.page)
    need = max(2, math.ceil(0.4 * n_pages))
    for b in margin:
        k = _norm(b.content)
        is_pn = bool(PAGE_NUM_RE.match(b.content))
        if is_pn or (len(keys[k]) >= need and n_pages >= 2):
            b.type = BlockType.header if b.meta["margin"] == "top" else BlockType.footer
            b.meta["repeated"] = len(keys[k]) >= need
            b.meta["page_number_only"] = is_pn
            b.signals["classification"] = 0.95 if (is_pn or b.meta["repeated"]) else 0.7
        b.meta.pop("margin", None) if b.type not in (BlockType.header, BlockType.footer) else None


def _link_captions(page_blocks: list[Block]) -> None:
    targets = [b for b in page_blocks if b.type in (BlockType.figure, BlockType.table, BlockType.chart) and b.bbox]
    for c in (b for b in page_blocks if b.type == BlockType.caption and b.bbox):
        want_table = c.content.lower().startswith("table")
        best, best_d = None, 55.0
        for t in targets:
            if want_table != (t.type == BlockType.table) and (want_table or t.type == BlockType.table):
                continue
            ov = min(c.bbox[2], t.bbox[2]) - max(c.bbox[0], t.bbox[0])
            if ov < -30:  # captions are often left-aligned while the table/figure is centred
                continue
            d = min(abs(c.bbox[1] - t.bbox[3]), abs(t.bbox[1] - c.bbox[3]))
            if d < best_d and (c.bbox[1] >= t.bbox[3] - 3 or c.bbox[3] <= t.bbox[1] + 3):
                best, best_d = t, d
        if best is not None:
            c.parent_id = best.id
            c.meta["caption_for"] = best.id
            best.meta["caption"] = c.content
            best.meta["caption_id"] = c.id
            c.signals["caption_link"] = round(1 - best_d / 110, 2)
    for t in targets:
        if t.type == BlockType.figure and looks_like_chart({**t.meta, "n_paths": t.meta.get("n_paths", 0)}, t.meta.get("caption") or ""):
            res = extract_chart({"embedded_text": t.meta.get("embedded_text", []), "confidence": t.signals.get("figure_detection", 0.6)})
            t.type = BlockType.chart
            t.signals = {**res["signals"], **{k: v for k, v in t.signals.items() if k == "figure_detection"}}
            t.meta.update(res["meta"])


def _body_blocks(blocks: list[Block]) -> list[Block]:
    return [b for b in blocks if b.type not in (BlockType.header, BlockType.footer, BlockType.footnote)]


def _continues(prev: Block, nxt: Block, same_page: bool) -> bool:
    if prev.type != BlockType.paragraph or nxt.type != BlockType.paragraph:
        return False
    if not isinstance(prev.content, str) or not isinstance(nxt.content, str) or not prev.content or not nxt.content:
        return False
    if TERMINAL.search(prev.content) and not prev.content.endswith("-"):
        return False
    if not (nxt.content[0].islower() or prev.content.endswith("-")):
        return False
    if same_page:  # only a column-to-column jump
        return bool(prev.bbox and nxt.bbox and nxt.bbox[0] > prev.bbox[2] - 5 and nxt.bbox[1] < prev.bbox[1])
    return True


def _absorb(prev: Block, nxt: Block, signal: float) -> None:
    prev.meta.setdefault("sources", [{"page": prev.page, "bbox": prev.bbox, "region_id": prev.meta.get("region_id")}])
    prev.meta["sources"].extend(nxt.meta.get("sources") or [{"page": nxt.page, "bbox": nxt.bbox, "region_id": nxt.meta.get("region_id")}])
    prev.meta["pages"] = sorted({s["page"] for s in prev.meta["sources"]})
    prev.signals["cross_page"] = min(prev.signals.get("cross_page", 1.0), signal)
    for k, v in nxt.signals.items():
        prev.signals[k] = min(prev.signals.get(k, v), v)


def _merge_paragraphs(blocks: list[Block]) -> list[Block]:
    skip = (BlockType.header, BlockType.footer, BlockType.footnote)
    out: list[Block] = []
    for b in blocks:
        if b.type == BlockType.paragraph:
            prev = next((x for x in reversed(out) if x.type not in skip), None)
            if prev is not None:
                last_page = max(prev.meta.get("pages", [prev.page]))
                if _continues(prev, b, same_page=(last_page == b.page)):
                    prev.content = prev.content[:-1] + b.content if prev.content.endswith("-") else prev.content + " " + b.content
                    _absorb(prev, b, 0.9)
                    continue
        out.append(b)
    return out


def _merge_lists(blocks: list[Block]) -> list[Block]:
    out: list[Block] = []
    for b in blocks:
        prev = out[-1] if out else None
        if prev is None or b.type != BlockType.list or prev.type != BlockType.list or prev.content["ordered"] != b.content["ordered"]:
            if b.type == BlockType.list:
                b.meta["item_sources"] = [{"page": b.page, "bbox": b.bbox}]
            out.append(b)
            continue
        prev.content["items"].extend(b.content["items"])
        prev.meta.setdefault("item_sources", [{"page": prev.page, "bbox": prev.bbox}]).append({"page": b.page, "bbox": b.bbox})
        prev.meta.setdefault("sources", [{"page": prev.page, "bbox": prev.bbox, "region_id": prev.meta.get("region_id")}])
        prev.meta["sources"].append({"page": b.page, "bbox": b.bbox, "region_id": b.meta.get("region_id")})
        prev.meta["pages"] = sorted({s["page"] for s in prev.meta["sources"]})
        if b.page == prev.page:
            prev.bbox = union(prev.bbox, b.bbox)
        for k, v in b.signals.items():
            prev.signals[k] = min(prev.signals.get(k, v), v)
    return out


def _table_merge_score(a: Block, b: Block, page_h: dict[int, float]) -> tuple[float, dict]:
    ta, tb = TableData(**a.content), TableData(**b.content)
    sig: dict = {}
    if ta.n_cols != tb.n_cols:
        return 0.0, {"reason": "column count differs"}
    score = 0.3
    ha, hb = page_h.get(a.page, 792.0), page_h.get(b.page, 792.0)
    if a.bbox[3] > 0.7 * ha and b.bbox[1] < 0.3 * hb:
        score += 0.15
        sig["vertical_continuity"] = True
    wa, wb = a.bbox[2] - a.bbox[0], b.bbox[2] - b.bbox[0]
    if abs(wa - wb) / max(wa, wb) <= 0.1:
        score += 0.15
        sig["similar_width"] = True
    if abs(a.bbox[0] - b.bbox[0]) <= 8:
        score += 0.1
    ea = [e - ta.col_edges[0] for e in ta.col_edges]
    eb = [e - tb.col_edges[0] for e in tb.col_edges]
    if len(ea) == len(eb) and ea and sum(abs(x - y) for x, y in zip(ea, eb)) / len(ea) <= 6:
        score += 0.2
        sig["column_edges_aligned"] = True
    ha_txt = [[c.lower() for c in r] for r in ta.headers]
    first = [[c.lower() for c in r] for r in (tb.headers or tb.rows[:1])]
    if ha_txt and first and ha_txt[-1] == first[0]:
        score += 0.3
        sig["repeated_header"] = True
    elif not tb.headers:
        score += 0.15
        sig["no_new_header"] = True
    elif tb.headers and ha_txt:
        score -= 0.3
        sig["different_header"] = True
    return round(max(0.0, min(score, 1.0)), 2), sig


def _merge_tables(blocks: list[Block], page_h: dict[int, float]) -> list[Block]:
    out: list[Block] = []
    for b in blocks:
        if b.type != BlockType.table or not out:
            out.append(b)
            continue
        prev_idx = next((i for i in range(len(out) - 1, -1, -1) if out[i].type not in (BlockType.header, BlockType.footer, BlockType.footnote)), None)
        cand = out[prev_idx] if prev_idx is not None else None
        # a leading "(continued)" caption between the two parts does not break adjacency
        if cand is not None and cand.type == BlockType.caption and re.search(r"continued|cont['’]d", cand.content, re.I) and prev_idx:
            cand = next((x for x in reversed(out[:prev_idx]) if x.type not in (BlockType.header, BlockType.footer, BlockType.footnote)), None)
        if cand is None or cand.type != BlockType.table or max(cand.meta.get("pages", [cand.page])) + 1 != b.page:
            out.append(b)
            continue
        score, sig = _table_merge_score(cand, b, page_h)
        if score < 0.6:
            if score >= 0.4:
                b.meta["possible_continuation_of"] = cand.id
                b.meta["merge_score"] = score
            out.append(b)
            continue
        ta, tb = TableData(**cand.content), TableData(**b.content)
        body = list(tb.rows)
        if not sig.get("repeated_header"):
            body = tb.headers + body  # headers of part 2 are really data rows
        offset = ta.n_rows
        for c in tb.cells:
            if c.row >= tb.header_rows or not sig.get("repeated_header"):
                nc = c.model_copy(update={"row": c.row - (tb.header_rows if sig.get("repeated_header") else 0) + offset, "is_header": False})
                ta.cells.append(nc)
        ta.rows.extend(body)
        ta.n_rows = ta.header_rows + len(ta.rows)
        ta.continued_from_previous = True
        ta.page_span = sorted(set(ta.page_span or [cand.page]) | {b.page})
        cand.content = ta.model_dump()
        _absorb(cand, b, score)
        cand.meta.update(merge_score=score, merge_signals=sig, n_rows=ta.n_rows)
        # drop an adjacent "(continued)" caption that sat between the parts
        out = [x for x in out if not (x.type == BlockType.caption and x.page == b.page and re.search(r"continued|cont['’]d", x.content, re.I))]
    return out


def _heading_levels(blocks: list[Block]) -> None:
    heads = [b for b in blocks if b.type == BlockType.heading]
    sizes = sorted({round(b.meta.get("font_size", 0) * 2) / 2 for b in heads}, reverse=True)
    for h in heads:
        m = HEAD_NUM.match(h.content)
        if m:
            h.level = min(6, m.group(1).count(".") + 1)
        else:
            rank = sizes.index(round(h.meta.get("font_size", 0) * 2) / 2) if sizes else 0
            h.level = min(6, rank + 1)
    stack: list[Block] = []
    for b in blocks:
        if b.type == BlockType.heading:
            while stack and stack[-1].level >= b.level:
                stack.pop()
            b.parent_id = stack[-1].id if stack else None
            stack.append(b)
        elif stack:
            b.meta["section_id"] = stack[-1].id


def _mark_references(blocks: list[Block]) -> None:
    in_refs = False
    for b in blocks:
        if b.type == BlockType.heading:
            in_refs = bool(REF_HEAD.match(b.content))
            continue
        if in_refs and b.type == BlockType.paragraph and isinstance(b.content, str) and len(b.content) > 20:
            b.type = BlockType.reference
        elif in_refs and b.type == BlockType.list:
            b.type = BlockType.reference
            b.content = " ".join(b.content["items"]) if len(b.content["items"]) == 1 else b.content["items"]


def assemble_document(extracted: dict, document_id: str = "", filename: str = "") -> Document:
    pages_info = extracted.get("pages", [])
    n_pages = len(pages_info)
    blocks: list[Block] = list(extracted.get("blocks", []))
    errors = list(extracted.get("errors", []))
    for b in blocks:
        b.meta.setdefault("region_id", b.id)
    _classify_margins(blocks, n_pages)
    by_page: dict[int, list[Block]] = defaultdict(list)
    for b in blocks:
        by_page[b.page].append(b)
    page_h = {p["page_number"]: p["height"] for p in pages_info}
    page_w = {p["page_number"]: p["width"] for p in pages_info}
    ordered: list[Block] = []
    for pn in sorted(by_page):
        _link_captions(by_page[pn])
        o, ambiguous = sort_reading_order(by_page[pn], page_w.get(pn, 612.0), page_h.get(pn, 792.0))
        if ambiguous:
            errors.append(make_error("READING_ORDER_AMBIGUITY", "Column extents overlap vertically; order is a best guess.", page=pn))
            for b in o:
                b.signals["reading_order"] = 0.6
        ordered.extend(o)
    ordered = _merge_tables(ordered, page_h)
    ordered = _merge_paragraphs(ordered)
    _mark_references(ordered)
    ordered = _merge_lists(ordered)
    _heading_levels(ordered)
    # final ids in reading order, remapping relationships
    remap = {b.id: f"B{i:04d}" for i, b in enumerate(ordered, start=1)}
    for b in ordered:
        b.meta.setdefault("region_id", b.id)
        b.parent_id = remap.get(b.parent_id) if b.parent_id else None
        for k in ("caption_for", "caption_id", "section_id", "possible_continuation_of"):
            if k in b.meta:
                b.meta[k] = remap.get(b.meta[k], b.meta[k])
    for b in ordered:
        b.id = remap.get(b.id, b.id)
    for e in errors:
        if e.get("block_id") in remap:
            e["block_id"] = remap[e["block_id"]]
    pages = [Page(page_number=p["page_number"], width=p["width"], height=p["height"], is_scanned=p["is_scanned"],
                  text_chars=p["text_chars"], source=p["source"]) for p in pages_info]
    pmap = {p.page_number: p for p in pages}
    for b in ordered:
        for pg in b.meta.get("pages", [b.page]):
            if pg in pmap:
                pmap[pg].blocks.append(b.id)
    return Document(document_id=document_id, filename=filename, page_count=n_pages, pages=pages, blocks=ordered, errors=errors)
