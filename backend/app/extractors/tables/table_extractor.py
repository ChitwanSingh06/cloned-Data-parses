"""Raw table detections -> structural TableData (cells, spans, multi-row headers)."""
import re
from typing import Optional

from app.extractors.tables.table_detector import NUM_RE, _cluster, _fill_and_numeric
from app.models.table import Cell, TableData


def _clean(t) -> str:
    t = re.sub(r"(^|\s)[|¦_\[\]]+(?=\s|$)", " ", str(t or ""))  # ruling lines misread as characters
    return re.sub(r"\s+", " ", t).strip()


def _idx(edges: list[float], v: float) -> int:
    return min(range(len(edges)), key=lambda i: abs(edges[i] - v))


def _from_pymupdf(raw: dict) -> TableData:
    texts = raw["text"]
    items = []  # (r_pos, c_pos, bbox)
    for r, row in enumerate(raw["row_cells"]):
        for c, bb in enumerate(row):
            if bb is not None:
                items.append((r, c, bb))
    col_edges = _cluster([v for _, _, b in items for v in (b[0], b[2])], 2.5)
    row_edges = _cluster([v for _, _, b in items for v in (b[1], b[3])], 2.5)
    cells = []
    for r, c, b in items:
        r0, r1, c0, c1 = _idx(row_edges, b[1]), _idx(row_edges, b[3]), _idx(col_edges, b[0]), _idx(col_edges, b[2])
        txt = _clean(texts[r][c]) if r < len(texts) and c < len(texts[r]) else ""
        cells.append(Cell(row=r0, col=c0, rowspan=max(1, r1 - r0), colspan=max(1, c1 - c0), text=txt,
                          bbox=[round(v, 2) for v in b]))
    return _assemble(cells, len(row_edges) - 1, len(col_edges) - 1, col_edges)


def _from_grid(raw: dict, words: list[dict]) -> TableData:
    re_, ce = raw["row_edges"], raw["col_edges"]
    cells = []
    for i in range(len(re_) - 1):
        for j in range(len(ce) - 1):
            box = [ce[j], re_[i], ce[j + 1], re_[i + 1]]
            inside = [w for w in words if box[0] <= (w["bbox"][0] + w["bbox"][2]) / 2 <= box[2]
                      and box[1] <= (w["bbox"][1] + w["bbox"][3]) / 2 <= box[3]]
            inside.sort(key=lambda w: (round(w["bbox"][1] / 6), w["bbox"][0]))
            cells.append(Cell(row=i, col=j, text=_clean(" ".join(w["text"] for w in inside)), bbox=[round(v, 2) for v in box]))
    return _assemble(cells, len(re_) - 1, len(ce) - 1, ce)


def _row_numeric_ratio(texts: list[str]) -> float:
    f = [t for t in texts if t]
    return sum(bool(NUM_RE.match(t)) for t in f) / len(f) if f else 0.0


def _assemble(cells: list[Cell], n_rows: int, n_cols: int, col_edges: list[float]) -> TableData:
    grid = [["" for _ in range(n_cols)] for _ in range(n_rows)]
    span_cells = [[None] * n_cols for _ in range(n_rows)]
    for c in cells:
        for r in range(c.row, min(n_rows, c.row + c.rowspan)):
            for k in range(c.col, min(n_cols, c.col + c.colspan)):
                grid[r][k] = c.text
                span_cells[r][k] = c
    # header detection: leading non-numeric rows; extra rows only if grouped by spans or followed by numbers
    header_rows = 0
    for r in range(min(3, n_rows - 1)):
        nonnum = _row_numeric_ratio(grid[r]) < 0.5 and any(grid[r])
        if not nonnum:
            break
        if r == 0:
            header_rows = 1
            continue
        prev_grouped = any(c is not None and c.colspan > 1 for c in span_cells[r - 1])
        next_numeric = _row_numeric_ratio(grid[r + 1]) >= 0.5
        if prev_grouped or next_numeric:
            header_rows = r + 1
        else:
            break
    for c in cells:
        c.is_header = c.row < header_rows
    return TableData(n_rows=n_rows, n_cols=n_cols, header_rows=header_rows,
                     headers=grid[:header_rows], rows=grid[header_rows:], cells=cells, col_edges=[round(e, 2) for e in col_edges])


def column_labels(t: TableData) -> list[str]:
    """Flatten multi-row headers into one label per column ('Group / Sub')."""
    labels = []
    for j in range(t.n_cols):
        parts: list[str] = []
        for hr in t.headers:
            if hr[j] and (not parts or parts[-1] != hr[j]):
                parts.append(hr[j])
        labels.append(" / ".join(parts))
    return labels


def extract_table(region: dict, words: Optional[list[dict]] = None) -> dict:
    """Return {'table': TableData, 'signals': {...}, 'meta': {...}}; raises on unusable input."""
    raw = region["raw"]
    td = _from_pymupdf(raw) if raw["kind"] == "pymupdf" else _from_grid(raw, words or [])
    if td.n_rows < 2 or td.n_cols < 2:
        raise ValueError("degenerate table grid")
    body = [c for r in td.rows for c in r]
    fill = sum(1 for c in body if c) / len(body) if body else 0.0
    pop = [sum(1 for c in r if c) for r in td.rows]
    consistency = (sum(1 for p in pop if p >= 0.6 * td.n_cols) / len(pop)) if pop else 0.0
    sig = {"table_detection": float(region.get("confidence", 0.7)), "table_fill": round(min(1.0, fill + 0.2), 2),
           "structure": round(0.5 + 0.5 * consistency, 2)}
    if region.get("ocr_conf") is not None:
        sig["ocr"] = region["ocr_conf"]
    return {"table": td, "signals": sig, "meta": {"strategy": region.get("strategy"), "n_rows": td.n_rows,
                                                   "n_cols": td.n_cols, "header_rows": td.header_rows,
                                                   "merged_cells": sum(1 for c in td.cells if c.rowspan > 1 or c.colspan > 1)}}
