from typing import Optional
from pydantic import BaseModel, Field, field_validator

from app.models.block import BlockType, ConfidenceLevel, Provenance, Status


class SearchRequest(BaseModel):
    document_id: str
    query: str = Field(min_length=1, max_length=500)
    limit: int = Field(default=200, ge=1, le=1000)

    @field_validator("query")
    @classmethod
    def _not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("query must not be blank")
        return v


class SearchHit(BaseModel):
    """One matching block. Fields come straight from the canonical Block; nothing is re-extracted."""
    block_id: str
    block_type: BlockType
    page: int
    bbox: Optional[list[float]] = None
    confidence: float
    confidence_level: ConfidenceLevel
    status: Status
    reading_order: int  # 1-based position in the document's global reading order
    matched_text: str  # the matched span exactly as it appears in the block (original case)
    snippet: str  # short context around the first match
    match_count: int
    provenance: Optional[Provenance] = None


class SearchResponse(BaseModel):
    document_id: str
    query: str
    total_matches: int  # matching blocks before `limit` is applied
    returned: int
    truncated: bool = False
    results: list[SearchHit] = Field(default_factory=list)
    message: Optional[str] = None  # set when there are no results
