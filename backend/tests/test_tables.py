from app.models.block import BlockType
from app.models.table import TableData


def test_merged_cells_and_multirow_headers(parsed):
    t = [b for b in parsed["digital"].blocks if b.type == BlockType.table][0]
    td = TableData(**t.content)
    assert td.header_rows == 2 and td.n_cols == 5
    assert td.headers[0][1] == "FY2024" and td.headers[1][1] == "Revenue"
    assert any(c.colspan == 2 for c in td.cells) and any(c.rowspan == 2 for c in td.cells)
    assert td.rows[0][:3] == ["North", "1,200", "12%"]
    assert t.confidence_level.value in ("HIGH", "MEDIUM")


def test_table_caption_linked(parsed):
    d = parsed["digital"]
    t = [b for b in d.blocks if b.type == BlockType.table][0]
    cap = [b for b in d.blocks if b.type == BlockType.caption][0]
    assert cap.parent_id == t.id and t.meta["caption"].startswith("Table 1")
