import io

import pytest
from fastapi.testclient import TestClient
from PIL import Image, ImageDraw, ImageFont

from app.main import app

client = TestClient(app)


def _font(size):
    for name in ("DejaVuSans-Bold.ttf", "DejaVuSans.ttf", "Arial.ttf", "Helvetica.ttc"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def _image(fmt="PNG"):
    im = Image.new("RGB", (1240, 900), "white")
    d = ImageDraw.Draw(im)
    d.text((80, 60), "Quarterly Report", fill="black", font=_font(54))
    d.text((80, 160), "Revenue grew strongly in the third quarter.", fill="black", font=_font(34))
    x0, y0, cw, ch = 80, 300, 300, 80
    rows = [["Region", "Q2", "Q3"], ["North", "10", "14"], ["South", "8", "9"]]
    for r, row in enumerate(rows):
        for c, txt in enumerate(row):
            d.rectangle([x0 + c * cw, y0 + r * ch, x0 + (c + 1) * cw, y0 + (r + 1) * ch], outline="black", width=3)
            d.text((x0 + c * cw + 20, y0 + r * ch + 20), txt, fill="black", font=_font(34))
    buf = io.BytesIO()
    im.save(buf, format=fmt)
    return buf.getvalue()


@pytest.mark.parametrize("name,fmt,mime", [("scan.png", "PNG", "image/png"), ("scan.jpg", "JPEG", "image/jpeg")])
def test_image_upload_is_parsed_with_ocr_and_tables(name, fmt, mime):
    up = client.post("/api/upload", files={"file": (name, _image(fmt), mime)})
    assert up.status_code == 200, up.text
    fid = up.json()["file_id"]
    assert up.json()["filename"] == name
    assert client.post(f"/api/parse?file_id={fid}&wait=true").status_code == 200
    res = client.get(f"/api/result/{fid}").json()
    assert res["status"] in ("SUCCESS", "PARTIAL_SUCCESS")
    assert res["filename"] == name
    assert res["page_count"] == 1 and res["pages"][0]["is_scanned"] is True
    text = " ".join(str(b["content"]) for b in res["blocks"] if isinstance(b["content"], str)).lower()
    assert "quarterly" in text or "revenue" in text
    assert client.get(f"/api/documents/{fid}/page/1.png").status_code == 200


def test_corrupt_image_rejected():
    r = client.post("/api/upload", files={"file": ("bad.png", b"not an image at all", "image/png")})
    assert r.status_code == 400
    assert r.json()["detail"]["code"] == "UNSUPPORTED_FORMAT"
