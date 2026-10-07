"""Tiny in-process job registry (no queue/DB). Status is mirrored to data/processed/<id>/status.json."""
import json
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Optional

from app.core.config import PROCESSED_DIR, UPLOAD_DIR

ID_RE = re.compile(r"^[0-9a-f]{12}$")
_pool = ThreadPoolExecutor(max_workers=2)
_lock = threading.Lock()
_status: dict[str, dict] = {}


def valid_id(doc_id: str) -> bool:
    return bool(ID_RE.match(doc_id))


def upload_path(doc_id: str) -> Optional[Path]:
    hits = sorted(UPLOAD_DIR.glob(f"{doc_id}_*"))
    return hits[0] if hits else None


def doc_dir(doc_id: str) -> Path:
    return PROCESSED_DIR / doc_id


def set_status(doc_id: str, **kw) -> dict:
    with _lock:
        st = _status.setdefault(doc_id, {"document_id": doc_id})
        st.update(kw)
        d = doc_dir(doc_id)
        d.mkdir(parents=True, exist_ok=True)
        (d / "status.json").write_text(json.dumps(st), encoding="utf-8")
        return dict(st)


def get_status(doc_id: str) -> Optional[dict]:
    with _lock:
        if doc_id in _status:
            return dict(_status[doc_id])
    f = doc_dir(doc_id) / "status.json"
    if f.exists():
        return json.loads(f.read_text(encoding="utf-8"))
    return None


def run_job(doc_id: str, path: Path, filename: str) -> None:
    from app.pipeline.orchestrator import parse_document
    t0 = time.time()
    set_status(doc_id, status="PROCESSING", filename=filename, started=t0)
    try:
        doc = parse_document(str(path), document_id=doc_id, filename=filename)
        set_status(doc_id, status=doc.status, finished=time.time(), processing_time=doc.processing_time,
                   page_count=doc.page_count, timing=doc.timing, errors=[e for e in doc.errors if e["severity"] == "error"][:5])
    except Exception as exc:  # parse_pdf already guards; belt and braces
        set_status(doc_id, status="FAILED", finished=time.time(), errors=[{"code": "PARSING_FAILED", "message": str(exc)}])


def submit(doc_id: str, path: Path, filename: str) -> None:
    set_status(doc_id, status="QUEUED", filename=filename)
    _pool.submit(run_job, doc_id, path, filename)
