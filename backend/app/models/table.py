from typing import Any, Optional
from pydantic import BaseModel, Field


class Cell(BaseModel):
    row: int
    col: int
    text: str = ""
    rowspan: int = 1
    colspan: int = 1
    is_header: bool = False
    bbox: Optional[list[float]] = None


class TableData(BaseModel):
    """Structural table. `headers`/`rows` are a flat convenience view; `cells` carries spans."""
    n_rows: int = 0
    n_cols: int = 0
    header_rows: int = 0
    headers: list[list[str]] = Field(default_factory=list)  # one list per header row
    rows: list[list[Any]] = Field(default_factory=list)  # body rows
    cells: list[Cell] = Field(default_factory=list)
    col_edges: list[float] = Field(default_factory=list)
    continued_from_previous: bool = False
    page_span: list[int] = Field(default_factory=list)
