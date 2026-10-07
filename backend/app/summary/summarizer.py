"""Deterministic, local, extractive summary built ONLY from the canonical Document.

No network, no API key, no model. Every sentence in the summary is copied verbatim from an extracted block (and carries
that block's id/page/confidence), so nothing is invented. Low-confidence blocks are kept out of the summary whenever
reliable content exists; if they are the only content they are used but flagged as uncertain.
"""
import re
from collections import Counter

from app.core.config import REVIEW_THRESHOLD
from app.models.block import Block, ConfidenceLevel, Status
from app.models.document import Document

METHOD = "extractive-local"
TEXT_TYPES = {"heading", "paragraph", "list", "caption", "footnote", "reference"}
BODY_TYPES = {"paragraph", "list"}
MAX_EXEC_SENTENCES = 3
MAX_KEY_POINTS = 6
MAX_SECTIONS = 20
MIN_WORDS, MAX_WORDS = 6, 60

STOP = set("""a an and are as at be been but by for from has have had he her his i if in into is it its of on or our she
that the their there these they this to was we were which will with you your not no can may also such than then so do does
did more most other some any each all both about over under between during after before while where when who whom what
""".split())
_SENT_SPLIT = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9\"'\u201c(\[])")
_WORD = re.compile(r"[A-Za-z][A-Za-z\-']{2,}")


def _is_low(b: Block) -> bool:
    return b.confidence_level == ConfidenceLevel.low or b.status in (Status.review, Status.failed) or b.confidence < REVIEW_THRESHOLD


def _text_of(b: Block) -> list[str]:
    c = b.content
    if b.type.value == "list" and isinstance(c, dict):
        return [str(x) for x in c.get("items", [])]
    return [c] if isinstance(c, str) else []


def _sentences(text: str) -> list[str]:
    out = []
    parts = _SENT_SPLIT.split(" ".join(text.split()))
    for i, s in enumerate(parts):
        s = s.strip()
        n = len(s.split())
        if not s or not (MIN_WORDS <= n <= MAX_WORDS) or sum(ch.isalpha() for ch in s) < 0.6 * len(s.replace(" ", "")):
            continue
        # a sentence must end like one; the very last piece of a block may be unterminated (text cut by the page)
        if s[-1] in ".!?\"')\u201d" or (i == len(parts) - 1 and n >= 2 * MIN_WORDS):
            out.append(s)
    return out


def _terms(s: str) -> list[str]:
    return [w.lower() for w in _WORD.findall(s) if w.lower() not in STOP]


def _title(headings: list[Block]) -> dict | None:
    if not headings:
        return None
    top = min((h.level or 1) for h in headings)
    h = next(h for h in headings if (h.level or 1) == top)
    return {"text": " ".join(str(h.content).split()), "block_id": h.id, "page": h.page, "uncertain": _is_low(h)}


def _stats(doc: Document) -> dict:
    cnt = Counter(b.type.value for b in doc.blocks)
    words = sum(len(t.split()) for b in doc.blocks if b.type.value in TEXT_TYPES for t in _text_of(b))
    return {
        "pages": doc.page_count,
        "text_blocks": sum(cnt[t] for t in TEXT_TYPES),
        "tables": cnt["table"], "figures": cnt["figure"], "charts": cnt["chart"], "equations": cnt["equation"],
        "words": words,
        "low_confidence_blocks": sum(b.confidence_level == ConfidenceLevel.low for b in doc.blocks),
        "review_required_blocks": sum(b.status == Status.review for b in doc.blocks),
        "total_blocks": len(doc.blocks),
    }


def _table_point(b: Block) -> str:
    c = b.content if isinstance(b.content, dict) else {}
    heads = [h for h in (c.get("headers") or [[]])[-1:] for h in h if str(h).strip()] if c.get("headers") else []
    cap = b.meta.get("caption")
    base = f"{cap}: " if cap else "Table: "
    shape = f"{c.get('n_rows', '?')} rows x {c.get('n_cols', '?')} columns"
    return base + shape + (f" (columns: {', '.join(str(h) for h in heads[:6])})" if heads else "")


def build_summary(doc: Document) -> dict:
    blocks = doc.blocks
    stats = _stats(doc)
    kinds = {"scanned" if p.is_scanned else "digital" for p in doc.pages}
    source = "mixed" if len(kinds) > 1 else (kinds.pop() if kinds else None)
    headings = [b for b in blocks if b.type.value == "heading" and isinstance(b.content, str) and b.content.strip()]
    title = _title(headings)
    overview = {"title": title, "filename": doc.filename, "page_count": doc.page_count,
                "unit_label": "logical document unit" if doc.format in {"docx", "xlsx"} else ("slides" if doc.format == "pptx" else "page"),
                "status": doc.status, "source_kind": source,  # digital / scanned / mixed, from page analysis
                "language": None, "document_type": None}  # not detected by the pipeline, so not claimed

    # sections: the top two heading levels present (largest headings first), in document order
    levels = sorted({h.level or 1 for h in headings})[:2]
    sections = [{"text": " ".join(str(h.content).split()), "level": h.level or 1, "page": h.page, "block_id": h.id,
                 "uncertain": _is_low(h)} for h in headings if (h.level or 1) in levels][:MAX_SECTIONS]

    if not blocks:
        return {"method": METHOD, "status": "empty", "overview": overview,
                "executive_summary": "No content was extracted from this document, so no summary can be given.",
                "executive_sources": [], "key_points": [], "sections": [], "statistics": stats,
                "warnings": [e["message"] for e in doc.errors if e.get("severity") == "error"][:3]}

    # candidate sentences from body text; reliable blocks first, low-confidence only as a flagged fallback
    def candidates(include_low: bool):
        out = []
        for order, b in enumerate(blocks):
            if b.type.value not in BODY_TYPES or (not include_low and _is_low(b)):
                continue
            for t in _text_of(b):
                for s in _sentences(t):
                    out.append({"text": s, "block": b, "order": order, "uncertain": _is_low(b)})
        return out

    cands = candidates(False)
    used_low_only = False
    if not cands:
        cands = candidates(True)
        used_low_only = bool(cands)
    heading_terms = {w for h in headings for w in _terms(str(h.content))}
    freq = Counter(w for c in cands for w in _terms(c["text"]))
    for i, c in enumerate(cands):
        ts = _terms(c["text"])
        base = sum(freq[w] for w in ts) / (len(ts) ** 0.7) if ts else 0.0
        c["score"] = base * (1 + 0.25 * len({w for w in ts if w in heading_terms}) / max(len(set(ts)), 1)) * (1.15 if i < 3 else 1.0)
    ranked, seen = [], set()
    for c in sorted(cands, key=lambda c: (-c["score"], c["order"])):
        if c["text"].lower() not in seen:
            seen.add(c["text"].lower()); ranked.append(c)
    exec_pick = sorted(ranked[:MAX_EXEC_SENTENCES], key=lambda c: c["order"])
    kp_pick = sorted(ranked[MAX_EXEC_SENTENCES:MAX_EXEC_SENTENCES + MAX_KEY_POINTS], key=lambda c: c["order"])

    def src(c):
        b = c["block"]
        return {"text": c["text"], "block_id": b.id, "page": b.page, "confidence": b.confidence, "uncertain": c["uncertain"]}

    key_points = [{**src(c), "kind": "sentence"} for c in kp_pick]
    for b in blocks:  # factual structure points taken straight from extracted tables/charts
        if len(key_points) >= MAX_KEY_POINTS + 2:
            break
        if b.type.value == "table":
            key_points.append({"text": _table_point(b), "block_id": b.id, "page": b.page, "confidence": b.confidence,
                               "uncertain": _is_low(b), "kind": "table"})
        elif b.type.value == "chart" and isinstance(b.content, dict) and b.content.get("chart_type"):
            t = b.content.get("title")
            key_points.append({"text": f"{b.content['chart_type'].capitalize()} chart" + (f": {t}" if t else "") +
                               ("" if b.content.get("data_extracted") else " (values not extracted)"),
                               "block_id": b.id, "page": b.page, "confidence": b.confidence, "uncertain": _is_low(b), "kind": "chart"})

    # executive summary = a templated sentence of counted facts + verbatim extracted sentences
    ttl = title["text"] if title and not title["uncertain"] else None
    parts = []
    head = f"{ttl}: " if ttl else ""
    head += f"{doc.page_count}-page {source + ' ' if source else ''}document"
    facts = [f"{n} {w}" for n, w in ((stats["tables"], "table(s)"), (stats["figures"] + stats["charts"], "figure(s)/chart(s)"),
                                     (stats["equations"], "equation(s)")) if n]
    head += " with " + ", ".join(facts) if facts else ""
    names = [s["text"] for s in sections if not s["uncertain"]][:5]
    head += (". Main sections: " + "; ".join(names) + ".") if names else "."
    parts.append(head)
    parts.extend(c["text"] for c in exec_pick)
    warnings = []
    n_low = stats["low_confidence_blocks"] + sum(1 for b in blocks if b.status == Status.review and b.confidence_level != ConfidenceLevel.low)
    if used_low_only:
        warnings.append("All extracted text is low confidence; the sentences shown may be inaccurate and need review.")
    elif n_low:
        warnings.append(f"{n_low} low-confidence or review-required block(s) were left out of the executive summary and key points.")
    if not cands:
        parts.append("No complete sentences were extracted, so no main-content sentences are shown.")
    return {"method": METHOD, "status": "uncertain" if used_low_only else "ok", "overview": overview,
            "executive_summary": " ".join(parts), "executive_sources": [src(c) for c in exec_pick],
            "key_points": key_points, "sections": sections, "statistics": stats, "warnings": warnings}
