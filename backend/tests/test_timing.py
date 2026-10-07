import json
import time

import pytest

from app.core.config import PROCESSED_DIR
from app.pipeline.orchestrator import parse_pdf
from app.pipeline.timing import STAGES, StageTimer, compute_metrics


def test_metrics_calculated_correctly():
    m = compute_metrics(12.43, 15)
    assert m["processing_time_seconds"] == 12.43 and m["pages_processed"] == 15
    assert m["seconds_per_page"] == pytest.approx(12.43 / 15, abs=1e-3)
    assert m["pages_per_second"] == pytest.approx(15 / 12.43, abs=1e-3)


@pytest.mark.parametrize("elapsed,pages", [(1.0, 0), (0.0, 5), (0.0, 0), (-1.0, 3), (1.0, -2),
                                           (float("nan"), 3), (None, 3), ("x", "y")])
def test_zero_and_invalid_inputs_do_not_divide_by_zero(elapsed, pages):
    m = compute_metrics(elapsed, pages)
    assert all(isinstance(v, (int, float)) for v in m.values())
    assert m["pages_processed"] >= 0 and m["seconds_per_page"] >= 0 and m["pages_per_second"] >= 0
    if pages in (0, -2) or elapsed in (0.0, -1.0):
        assert m["pages_per_second"] == 0.0


def test_stage_timer_is_exclusive_and_real():
    t = StageTimer()
    with t.stage("layout_analysis"):
        time.sleep(0.05)
        with t.stage("ocr"):
            time.sleep(0.05)
    d = t.as_dict()
    assert set(STAGES) <= set(d)
    assert d["ocr"] >= 0.04
    assert 0.04 <= d["layout_analysis"] < 0.09  # nested OCR time is not double counted
    assert d["assembly"] == 0.0


def test_parse_returns_real_timing(pdfs):
    doc = parse_pdf(str(pdfs["mixed"]))
    t = doc.timing
    assert doc.page_count == 3 and t["pages_processed"] == 3
    assert t["processing_time_seconds"] > 0 and t["processing_time_seconds"] == doc.processing_time
    assert t["seconds_per_page"] == pytest.approx(t["processing_time_seconds"] / 3, abs=1e-3)
    assert t["pages_per_second"] == pytest.approx(3 / t["processing_time_seconds"], abs=1e-2)
    assert set(STAGES) <= set(t["stages"]) and t["stages"]["ingestion"] > 0 and t["stages"]["ocr"] > 0
    assert sum(t["stages"].values()) <= t["processing_time_seconds"] + 0.05
    js = json.loads((PROCESSED_DIR / doc.document_id / "document.json").read_text(encoding="utf-8"))
    assert js["timing"] == t and js["stats"]["seconds_per_page"] == t["seconds_per_page"]


def test_failed_document_has_safe_timing(pdfs):
    doc = parse_pdf(str(pdfs["corrupt"]))
    t = doc.timing
    assert t["pages_processed"] == 0 and t["seconds_per_page"] == 0.0 and t["pages_per_second"] == 0.0
    assert t["processing_time_seconds"] >= 0


def test_api_result_includes_timing(pdfs):
    from fastapi.testclient import TestClient
    from app.main import app
    c = TestClient(app)
    with open(pdfs["digital"], "rb") as fh:
        fid = c.post("/api/upload", files={"file": ("d.pdf", fh, "application/pdf")}).json()["file_id"]
    st = c.post(f"/api/parse?file_id={fid}&wait=true").json()
    res = c.get(f"/api/result/{fid}").json()
    assert res["timing"]["pages_processed"] == res["page_count"] > 0
    assert st["timing"]["processing_time_seconds"] == res["timing"]["processing_time_seconds"]
