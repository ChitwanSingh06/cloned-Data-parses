from fastapi import APIRouter

from app.output.json_builder import build_json
from app.output.markdown_builder import build_markdown

router = APIRouter()


@router.post("/export/markdown")
def export_markdown(document: dict):
    return {"markdown": build_markdown(document)}


@router.post("/export/json")
def export_json(document: dict):
    return {"json": build_json(document)}
