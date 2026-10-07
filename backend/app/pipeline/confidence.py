"""Confidence engine: normalised 0-1 score from real extraction signals; no random values."""
from app.core.config import HIGH_THRESHOLD, REVIEW_THRESHOLD
from app.models.block import Block, ConfidenceLevel, Status
from app.models.document import Document
from app.pipeline.failsafe import make_error


def score(signals: dict[str, float]) -> float:
    vals = [max(0.0, min(1.0, float(v))) for v in signals.values()]
    if not vals:
        return 0.3  # no evidence at all -> low
    return round(0.6 * (sum(vals) / len(vals)) + 0.4 * min(vals), 3)


def level(conf: float) -> ConfidenceLevel:
    return ConfidenceLevel.high if conf >= HIGH_THRESHOLD else ConfidenceLevel.medium if conf >= REVIEW_THRESHOLD else ConfidenceLevel.low


def add_confidence(document: Document) -> Document:
    for b in document.blocks:
        _apply(b, document)
    return document


def _apply(b: Block, document: Document) -> None:
    if b.status == Status.failed:
        b.confidence, b.confidence_level = 0.0, ConfidenceLevel.low
        return
    b.confidence = score(b.signals)
    b.confidence_level = level(b.confidence)
    reason = b.meta.get("review_reason")
    if b.confidence < REVIEW_THRESHOLD or reason or b.meta.get("possible_continuation_of"):
        b.status = Status.review
        b.meta.setdefault("review_reason", reason or "Low confidence" if b.confidence < REVIEW_THRESHOLD else "Possible table continuation not merged")
        document.errors.append(make_error("LOW_CONFIDENCE", b.meta["review_reason"], page=b.page, block_id=b.id, severity="warning"))
