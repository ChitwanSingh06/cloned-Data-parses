import re
import uuid

from fastapi import APIRouter, File, HTTPException, UploadFile

from app.api.jobs import set_status
from app.core.config import MAX_UPLOAD_MB, UPLOAD_DIR
from app.formats.image_handler import image_to_pdf_bytes, is_image_name
from app.pipeline.failsafe import make_error

router = APIRouter()


@router.post("/upload")
async def upload_document(file: UploadFile = File(...)):
    data = await file.read()
    if len(data) > MAX_UPLOAD_MB * 1024 * 1024:
        raise HTTPException(413, detail=make_error("FILE_TOO_LARGE"))
    if not data:
        raise HTTPException(400, detail=make_error("CORRUPT_PDF", "Empty file"))
    doc_id = uuid.uuid4().hex[:12]
    safe = re.sub(r"[^A-Za-z0-9._-]", "_", file.filename or "upload.pdf")[-120:]
    if is_image_name(file.filename or ""):
        # Standalone image: wrap into a one-page PDF so the existing pipeline (OCR, tables, figures) runs on it.
        try:
            data = image_to_pdf_bytes(data)
        except ValueError as exc:
            raise HTTPException(400, detail=make_error("UNSUPPORTED_FORMAT", str(exc)))
        safe = re.sub(r"\.[A-Za-z0-9]+$", "", safe) + ".pdf"
    (UPLOAD_DIR / f"{doc_id}_{safe}").write_bytes(data)
    set_status(doc_id, status="UPLOADED", filename=file.filename)
    return {"file_id": doc_id, "document_id": doc_id, "filename": file.filename, "size_bytes": len(data)}
