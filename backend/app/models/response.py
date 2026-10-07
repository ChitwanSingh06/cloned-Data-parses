from typing import Any
from pydantic import BaseModel, Field


class ParseResponse(BaseModel):
    status: str
    document_id: str
    summary: dict[str, Any] = Field(default_factory=dict)
    errors: list[dict[str, Any]] = Field(default_factory=list)
