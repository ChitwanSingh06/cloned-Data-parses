import json

from fastapi import APIRouter, HTTPException

from app.api import jobs
from app.models.document import Document
from app.models.search import SearchRequest, SearchResponse
from app.pipeline.failsafe import make_error
from app.search.engine import search_document

router = APIRouter()


@router.post("/search", response_model=SearchResponse)
def search(req: SearchRequest):
    """Search the saved canonical document.json of an already-parsed document. The PDF is never re-parsed."""
    if not jobs.valid_id(req.document_id):
        raise HTTPException(400, detail=make_error("PARSING_FAILED", "Invalid document id"))
    f = jobs.doc_dir(req.document_id) / "document.json"
    if not f.is_file():
        raise HTTPException(404, detail=make_error("PARSING_FAILED", "Document has not been parsed yet"))
    try:
        doc = Document.model_validate(json.loads(f.read_text(encoding="utf-8")))
    except Exception as exc:
        raise HTTPException(500, detail=make_error("PARSING_FAILED", f"Stored document unreadable: {exc}"))
    return search_document(doc, req.query, req.limit)
