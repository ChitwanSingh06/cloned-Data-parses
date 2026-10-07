import os
import sys
import tempfile
from pathlib import Path

_TMP = tempfile.mkdtemp(prefix="parseanything_")
os.environ["PARSE_BASE_DIR"] = _TMP  # must precede app imports
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import pymupdf  # noqa: E402
import pytest  # noqa: E402

import make_fixtures as fx  # noqa: E402


@pytest.fixture(scope="session")
def pdfs(tmp_path_factory):
    d = tmp_path_factory.mktemp("pdfs")
    out = {"digital": fx.digital_pdf(d / "digital.pdf"), "twocol": fx.twocol_pdf(d / "twocol.pdf"),
           "multitable": fx.multipage_table_pdf(d / "multitable.pdf")}
    out["scanned"] = fx.to_scanned(out["digital"], d / "scanned.pdf")
    mixed = pymupdf.open()
    for src in (out["digital"], out["scanned"], out["digital"]):
        mixed.insert_pdf(pymupdf.open(str(src)))
    mixed.save(str(d / "mixed.pdf"))
    out["mixed"] = d / "mixed.pdf"
    (d / "corrupt.pdf").write_bytes(b"%PDF-1.4\nthis is not really a pdf\n")
    (d / "notpdf.pdf").write_bytes(b"hello world")
    (d / "sheet.xlsx").write_bytes(b"PK\x03\x04")
    out.update(corrupt=d / "corrupt.pdf", notpdf=d / "notpdf.pdf", xlsx=d / "sheet.xlsx")
    return out


@pytest.fixture(scope="session")
def parsed(pdfs):
    from app.pipeline.orchestrator import parse_pdf
    return {k: parse_pdf(str(pdfs[k])) for k in ("digital", "twocol", "multitable", "scanned", "mixed")}
