"""Search over the EXISTING canonical Document (no re-parsing, no second representation)."""
import re
from typing import Any, Iterable

from app.models.document import Document
from app.models.search import SearchHit, SearchResponse

SNIPPET_CONTEXT = 50


def _norm(text: Any) -> str:
    return " ".join(str(text).split())


def _flatten(value: Any) -> Iterable[str]:
    if value is None:
        return
    if isinstance(value, (list, tuple)):
        for v in value:
            yield from _flatten(v)
    elif isinstance(value, dict):
        for v in value.values():
            yield from _flatten(v)
    else:
        s = str(value)
        if s.strip():
            yield s


def _table_texts(c: dict) -> list[str]:
    cells = [x.get("text", "") for x in c.get("cells") or []]
    if any(t.strip() for t in cells):
        return cells
    return list(_flatten(c.get("headers"))) + list(_flatten(c.get("rows")))


def _chart_texts(c: dict) -> list[str]:
    out: list[Any] = [c.get("title"), (c.get("x_axis") or {}).get("label"), (c.get("y_axis") or {}).get("label"),
                      (c.get("x_axis") or {}).get("categories")]
    for s in c.get("series") or []:
        out.append(s.get("name"))
        out.extend(p.get("category") for p in s.get("points") or [])
    return list(_flatten(out))


def _search_units(block) -> list[tuple[str, dict | None]]:
    """Return searchable text plus the most specific existing source metadata for that unit."""
    c, t = block.content, block.type.value
    base = (block.provenance.sources[0] if block.provenance and block.provenance.sources else None)
    if t == "list" and isinstance(c, dict):
        item_sources = block.meta.get("item_sources") or []
        out = []
        for i, value in enumerate(c.get("items") or []):
            source = dict(base) if base else None
            if source and i < len(item_sources):
                source.update(item_sources[i])
            out.append((str(value), source))
        return out
    if t == "table" and isinstance(c, dict):
        cells = c.get("cells") or []
        if cells:
            cell_sources = block.meta.get("cell_provenance") or block.meta.get("cell_sources") or []
            out = []
            for i, cell in enumerate(cells):
                source = dict(base) if base else None
                if source and i < len(cell_sources):
                    source.update(cell_sources[i])
                out.append((str(cell.get("text", "")), source))
            return out
        return [(x, dict(base) if base else None) for x in _table_texts(c)]
    if t == "equation" and isinstance(c, dict):
        return [(x, dict(base) if base else None) for x in _flatten([c.get("raw_text"), c.get("latex")])]
    if t == "chart" and isinstance(c, dict):
        return [(x, dict(base) if base else None) for x in _chart_texts(c)]
    if t == "figure":
        return [(x, dict(base) if base else None) for x in _flatten(block.meta.get("embedded_text"))]
    return [(x, dict(base) if base else None) for x in _flatten(c)]


def block_texts(block) -> list[str]:
    """Searchable text units of a block. Each unit is matched separately, so a phrase never spans two table cells."""
    return [text for text, _ in _search_units(block)]


def build_pattern(query: str) -> re.Pattern:
    """Case-insensitive; whitespace in the query matches any whitespace run; a quoted query is a phrase."""
    q = query.strip()
    if len(q) >= 2 and q[0] == q[-1] and q[0] in "\"'\u201c\u201d":
        q = q[1:-1].strip()
    tokens = q.split()
    if not tokens:
        raise ValueError("query must not be blank")
    return re.compile(r"\s+".join(re.escape(t) for t in tokens), re.IGNORECASE)


def _snippet(text: str, start: int, end: int) -> str:
    a, b = max(0, start - SNIPPET_CONTEXT), min(len(text), end + SNIPPET_CONTEXT)
    return ("..." if a > 0 else "") + text[a:b] + ("..." if b < len(text) else "")


def search_document(doc: Document, query: str, limit: int = 200) -> SearchResponse:
    pat = build_pattern(query)
    hits: list[SearchHit] = []
    for order, b in enumerate(doc.blocks, start=1):
        first, count = None, 0
        for unit, source in _search_units(b):
            text = _norm(unit)
            for m in pat.finditer(text):
                count += 1
                if first is None:
                    first = (text, m, source)
        if first is None:
            continue
        text, m, source = first
        hit_provenance = b.provenance
        if hit_provenance is not None and source:
            # Put the most specific existing unit location first while retaining the
            # complete block provenance. No new coordinates are fabricated here.
            hit_provenance = hit_provenance.model_copy(deep=True)
            hit_provenance.sources = [source] + [s for s in hit_provenance.sources if s != source]
        hits.append(SearchHit(block_id=b.id, block_type=b.type, page=b.page, bbox=b.bbox, confidence=b.confidence,
                              confidence_level=b.confidence_level, status=b.status, reading_order=order,
                              matched_text=m.group(0), snippet=_snippet(text, m.start(), m.end()),
                              match_count=count, provenance=hit_provenance))
    total = len(hits)
    shown = hits[:limit]
    return SearchResponse(document_id=doc.document_id, query=query, total_matches=total, returned=len(shown),
                          truncated=total > len(shown), results=shown,
                          message=None if total else f"No matches for '{query.strip()}'.")
