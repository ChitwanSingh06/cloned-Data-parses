import json

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def _upload(path):
    with open(path, "rb") as fh:
        r = client.post("/api/upload", files={"file": (path.name, fh, "application/pdf")})
    assert r.status_code == 200
    return r.json()["file_id"]


def test_health():
    assert client.get("/health").json() == {"status": "ok"}


def test_upload_parse_status_results_downloads(pdfs):
    fid = _upload(pdfs["digital"])
    st = client.post(f"/api/parse?file_id={fid}&wait=true").json()
    assert st["status"] == "SUCCESS"
    assert client.get(f"/api/status/{fid}").json()["status"] == "SUCCESS"
    res = client.get(f"/api/result/{fid}").json()
    assert res["blocks"] and res["document_id"] == fid
    md = client.get(f"/api/download/{fid}/markdown")
    js = client.get(f"/api/download/{fid}/json")
    assert md.status_code == js.status_code == 200 and md.text.strip()
    assert json.loads(js.text)["document_id"] == fid
    png = client.get(f"/api/documents/{fid}/page/1.png")
    assert png.status_code == 200 and png.content[:4] == b"\x89PNG"
    assert client.get(f"/api/documents/{fid}/page/9.png").status_code == 404


def test_corrupt_upload_returns_structured_error(pdfs):
    fid = _upload(pdfs["corrupt"])
    st = client.post(f"/api/parse?file_id={fid}&wait=true").json()
    assert st["status"] == "FAILED" and st["errors"][0]["code"] == "CORRUPT_PDF"


def test_bad_ids_rejected():
    assert client.get("/api/status/../../etc").status_code in (400, 404)
    assert client.post("/api/parse?file_id=zzzz").status_code == 400
