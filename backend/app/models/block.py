from enum import Enum
from typing import Any, Optional
from pydantic import BaseModel, Field


class BlockType(str, Enum):
    heading = "heading"
    paragraph = "paragraph"
    list = "list"
    table = "table"
    figure = "figure"
    chart = "chart"
    equation = "equation"
    caption = "caption"
    header = "header"
    footer = "footer"
    footnote = "footnote"
    reference = "reference"


class Status(str, Enum):
    ok = "OK"
    review = "REVIEW_REQUIRED"
    failed = "FAILED"


class ConfidenceLevel(str, Enum):
    high = "HIGH"
    medium = "MEDIUM"
    low = "LOW"


class Provenance(BaseModel):
    document: str
    page: int
    bbox: Optional[list[float]] = None
    extractor: Optional[str] = None
    source_region_id: Optional[str] = None
    # Every original (page, bbox) that contributed to this block, kept through merges.
    sources: list[dict[str, Any]] = Field(default_factory=list)


class Block(BaseModel):
    id: str = ""
    type: BlockType
    content: Any = ""
    page: int
    bbox: Optional[list[float]] = None
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    confidence_level: ConfidenceLevel = ConfidenceLevel.low
    provenance: Optional[Provenance] = None
    extractor: Optional[str] = None
    status: Status = Status.ok
    level: Optional[int] = None  # heading level
    parent_id: Optional[str] = None
    meta: dict[str, Any] = Field(default_factory=dict)
    signals: dict[str, float] = Field(default_factory=dict)  # inputs to confidence
