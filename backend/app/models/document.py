from typing import Any, Optional
from pydantic import BaseModel, Field
from app.models.block import Block


class ErrorInfo(BaseModel):
    code: str
    message: str
    page: Optional[int] = None
    block_id: Optional[str] = None
    recoverable: bool = True


class Page(BaseModel):
    page_number: int
    width: float
    height: float
    is_scanned: bool = False
    text_chars: int = 0
    source: str = "digital"  # digital | ocr
    blocks: list[str] = Field(default_factory=list)  # block ids, in reading order


class Document(BaseModel):
    document_id: str
    filename: str
    page_count: int = 0
    processing_time: float = 0.0
    status: str = "SUCCESS"  # SUCCESS | PARTIAL_SUCCESS | FAILED
    pages: list[Page] = Field(default_factory=list)
    blocks: list[Block] = Field(default_factory=list)  # global reading order
    errors: list[dict[str, Any]] = Field(default_factory=list)
    stats: dict[str, Any] = Field(default_factory=dict)
