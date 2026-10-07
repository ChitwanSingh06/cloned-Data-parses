"""Layout-aware reading order: header -> bands split by full-width blocks -> columns -> top-to-bottom -> footnotes/footer."""
from typing import Sequence

import numpy as np

from app.models.block import Block, BlockType

GUTTER_MIN = 10.0  # pt of uncovered horizontal space that counts as a column gutter
SPAN_FRAC = 0.65


def _gutters(body: Sequence[Block]) -> list[tuple[float, float]]:
    """Vertical white-space channels: x-runs covered by (almost) no text height, between text on both sides."""
    x_min = int(min(b.bbox[0] for b in body))
    x_max = int(max(b.bbox[2] for b in body)) + 1
    cov = np.zeros(x_max - x_min + 1)
    for b in body:
        cov[int(b.bbox[0]) - x_min:int(b.bbox[2]) - x_min + 1] += b.bbox[3] - b.bbox[1]
    pos = cov[cov > 0]
    if pos.size == 0:
        return []
    low = cov <= 0.3 * float(np.median(pos))
    out, start = [], None
    for i, flag in enumerate(low):
        if flag and start is None:
            start = i
        if (not flag or i == len(low) - 1) and start is not None:
            end = i if not flag else i + 1
            if end - start >= GUTTER_MIN and start > 0 and end < len(low):
                out.append((start + x_min, end + x_min))
            start = None
    return out


def _columns(blocks: Sequence[Block], gutters: list[tuple[float, float]]) -> list[list[Block]]:
    if not blocks:
        return []
    edges = [-1e9] + [(g0 + g1) / 2 for g0, g1 in gutters] + [1e9]
    cols: list[list[Block]] = [[] for _ in range(len(edges) - 1)]
    for b in blocks:
        cx = (b.bbox[0] + b.bbox[2]) / 2
        for i in range(len(cols)):
            if edges[i] <= cx < edges[i + 1]:
                cols[i].append(b)
                break
    spans = [(edges[i] if i else min(b.bbox[0] for b in blocks), edges[i + 1] if i < len(cols) - 1 else max(b.bbox[2] for b in blocks)) for i in range(len(cols))]
    total = max(b.bbox[2] for b in blocks) - min(b.bbox[0] for b in blocks) or 1
    idx = [i for i in range(len(cols)) if cols[i]]
    widths = {i: max(b.bbox[2] for b in cols[i]) - min(b.bbox[0] for b in cols[i]) for i in idx}
    main = [i for i in idx if widths[i] / total >= 0.25]
    side = [i for i in idx if widths[i] / total < 0.25] if main else []   # sidebars read after main text
    return [sorted(cols[i], key=lambda b: (b.bbox[1], b.bbox[0])) for i in main + side]


def sort_reading_order(blocks: list[Block], page_width: float, page_height: float) -> tuple[list[Block], bool]:
    """Order blocks of ONE page. Returns (ordered, ambiguous)."""
    if not blocks:
        return [], False
    with_box = [b for b in blocks if b.bbox]
    no_box = [b for b in blocks if not b.bbox]
    headers = [b for b in with_box if b.type == BlockType.header]
    footers = [b for b in with_box if b.type == BlockType.footer]
    notes = [b for b in with_box if b.type == BlockType.footnote]
    body = [b for b in with_box if b.type not in (BlockType.header, BlockType.footer, BlockType.footnote)]
    if not body:
        return headers + notes + footers + no_box, False
    content_w = max(b.bbox[2] for b in body) - min(b.bbox[0] for b in body) or page_width
    gutters = _gutters(body)

    def straddles(b: Block) -> bool:
        return any(b.bbox[0] < g1 - 2 and b.bbox[2] > g0 + 2 for g0, g1 in gutters)

    spanning = sorted((b for b in body if (b.bbox[2] - b.bbox[0]) >= SPAN_FRAC * content_w or straddles(b)), key=lambda b: b.bbox[1])
    span_ids = {id(b) for b in spanning}
    rest = [b for b in body if id(b) not in span_ids]
    ordered: list[Block] = []
    ambiguous = False
    placed: set[int] = set()

    def flush(upto: float) -> None:
        nonlocal ambiguous
        band = [b for b in rest if id(b) not in placed and (b.bbox[1] + b.bbox[3]) / 2 < upto]
        placed.update(id(b) for b in band)
        cols = _columns(band, gutters)
        if len(cols) > 1 and min(c[-1].bbox[3] for c in cols) < max(c[0].bbox[1] for c in cols) - 1e-6 and False:
            ambiguous = True
        for c in cols:
            ordered.extend(c)

    for s_ in spanning:
        flush(s_.bbox[1] + 0.5 * (s_.bbox[3] - s_.bbox[1]))
        ordered.append(s_)
    flush(float("inf"))
    # Ambiguity: a block that overlaps horizontally with a different column's block while neither is spanning.
    for i, a in enumerate(rest):
        for b in rest[i + 1:]:
            ox = min(a.bbox[2], b.bbox[2]) - max(a.bbox[0], b.bbox[0])
            oy = min(a.bbox[3], b.bbox[3]) - max(a.bbox[1], b.bbox[1])
            if ox > 0 and oy > 2:
                ambiguous = True
    return (sorted(headers, key=lambda b: b.bbox[1]) + ordered + sorted(notes, key=lambda b: b.bbox[1])
            + sorted(footers, key=lambda b: b.bbox[1]) + no_box, ambiguous)
