import json
import re

import pymupdf
from fastapi import APIRouter, HTTPException, Response
from fastapi.responses import FileResponse

from app.api import jobs
from app.pipeline.failsafe import make_error

router = APIRouter()


def _need(doc_id: str) -> str:
    if not jobs.valid_id(doc_id):
        raise HTTPException(400, detail=make_error("PARSING_FAILED", "Invalid document id"))
    return doc_id


@router.post("/parse")
def parse_document(file_id: str, wait: bool = False):
    """Start parsing an uploaded file. wait=true blocks until done (used by tests/CLI)."""
    _need(file_id)
    path = jobs.upload_path(file_id)
    if path is None:
        raise HTTPException(404, detail=make_error("PARSING_FAILED", "Unknown file_id; upload first"))
    filename = (jobs.get_status(file_id) or {}).get("filename") or path.name
    if wait:
        jobs.run_job(file_id, path, filename)
    else:
        jobs.submit(file_id, path, filename)
    return jobs.get_status(file_id)


@router.get("/status/{doc_id}")
def status(doc_id: str):
    st = jobs.get_status(_need(doc_id))
    if not st:
        raise HTTPException(404, detail="Unknown document")
    return st


@router.get("/result/{doc_id}")
def result(doc_id: str):
    f = jobs.doc_dir(_need(doc_id)) / "document.json"
    if not f.exists():
        raise HTTPException(404, detail="Result not ready")
    return Response(f.read_text(encoding="utf-8"), media_type="application/json")


@router.get("/download/{doc_id}/{fmt}")
def download(doc_id: str, fmt: str):
    names = {"json": ("document.json", "application/json"), "markdown": ("document.md", "text/markdown"), "md": ("document.md", "text/markdown")}
    if fmt not in names:
        raise HTTPException(404, detail="fmt must be json or markdown")
    f = jobs.doc_dir(_need(doc_id)) / names[fmt][0]
    if not f.exists():
        raise HTTPException(404, detail="Result not ready")
    return FileResponse(f, media_type=names[fmt][1], filename=names[fmt][0])


@router.get("/documents/{doc_id}/page/{page}.png")
def page_image(doc_id: str, page: int, dpi: int = 110):
    """Rendered page for the source viewer; block bboxes (PDF points) overlay on this image."""
    _need(doc_id)
    path = jobs.upload_path(doc_id)
    if path is None:
        raise HTTPException(404, detail="Source not found")
    if path.suffix.lower() != ".pdf":
        raise HTTPException(404, detail="Source page viewer is only available for PDF documents")
    try:
        with pymupdf.open(str(path)) as pdf:
            if not 1 <= page <= pdf.page_count:
                raise HTTPException(404, detail="Page out of range")
            png = pdf[page - 1].get_pixmap(dpi=max(40, min(dpi, 200))).tobytes("png")
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(422, detail=make_error("CORRUPT_PDF", str(exc)))
    return Response(png, media_type="image/png")


_FIGURE_NAME = re.compile(r"[A-Za-z0-9_-]+\.png")  # whitelist: no "/", "\\" (a path separator on Windows), ":" or ".."


@router.get("/documents/{doc_id}/figures/{name}")
def figure(doc_id: str, name: str):
    if not _FIGURE_NAME.fullmatch(name):
        raise HTTPException(404, detail="Not found")
    f = jobs.doc_dir(_need(doc_id)) / "figures" / name
    if not f.is_file():
        raise HTTPException(404, detail="Not found")
    return FileResponse(f, media_type="image/png")
