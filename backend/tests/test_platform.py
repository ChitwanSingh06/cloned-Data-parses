"""Regression tests for Windows compatibility (no `resource` module, tesseract.exe lookup, path-safe figure URLs)."""
import os
import subprocess
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.core.config import PROCESSED_DIR
from app.main import app
from app.utils import platform_utils as pu

BACKEND_DIR = Path(__file__).resolve().parents[1]


def test_orchestrator_imports_without_resource_module(tmp_path):
    """The original bug: `import resource` crashed on Windows. Block the module in a fresh interpreter."""
    code = ("import sys; sys.modules['resource'] = None\n"
            "import app.pipeline.orchestrator as o\n"
            "m = o.peak_memory_mb(); assert isinstance(m, float) and m >= 0.0, m\n")
    env = {**os.environ, "PARSE_BASE_DIR": str(tmp_path)}
    r = subprocess.run([sys.executable, "-c", code], cwd=BACKEND_DIR, env=env, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr


def test_peak_memory_is_float_and_positive_where_supported():
    m = pu.peak_memory_mb()
    assert isinstance(m, float)
    try:
        import resource  # noqa: F401  (POSIX only)
        has_resource = True
    except ImportError:
        has_resource = False
    if sys.platform == "win32" or has_resource:
        assert m > 0


def test_peak_memory_never_raises_when_platform_call_fails(monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(pu, "_peak_memory_windows", lambda: (_ for _ in ()).throw(OSError("boom")))
    assert pu.peak_memory_mb() == 0.0


def test_stats_include_peak_memory(parsed):
    assert isinstance(parsed["digital"].stats["peak_memory_mb"], float)


@pytest.fixture
def clean_tesseract_cache():
    pu.find_tesseract.cache_clear()
    yield
    pu.find_tesseract.cache_clear()


def test_find_tesseract_env_override(monkeypatch, tmp_path, clean_tesseract_cache):
    exe = tmp_path / "tesseract.exe"
    exe.write_bytes(b"")
    monkeypatch.setenv("TESSERACT_CMD", str(exe))
    assert pu.find_tesseract() == str(exe)


def test_find_tesseract_windows_default_install_dir(monkeypatch, tmp_path, clean_tesseract_cache):
    exe = tmp_path / "Tesseract-OCR" / "tesseract.exe"
    exe.parent.mkdir()
    exe.write_bytes(b"")
    monkeypatch.delenv("TESSERACT_CMD", raising=False)
    # tesseract not on PATH, as on a typical Windows box (stubbed: real shutil.which needs Windows internals once platform is faked)
    monkeypatch.setattr(pu.shutil, "which", lambda *a, **k: None)
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setenv("ProgramFiles", str(tmp_path))
    assert Path(pu.find_tesseract()) == exe


def test_find_tesseract_none_when_missing(monkeypatch, tmp_path, clean_tesseract_cache):
    monkeypatch.delenv("TESSERACT_CMD", raising=False)
    monkeypatch.setenv("PATH", str(tmp_path / "empty"))
    monkeypatch.setattr(sys, "platform", "linux")
    assert pu.find_tesseract() is None


def test_figure_endpoint_rejects_traversal_and_backslashes(parsed):
    client = TestClient(app)
    doc_id = parsed["digital"].document_id
    secret = PROCESSED_DIR / doc_id / "document.json"  # a real file just outside figures/
    assert secret.exists()
    for name in ("..%5Cdocument.json", "..%2Fdocument.json", "..\\document.png", "a%5Cb.png",
                 "..%5C..%5Cdocument.png", "document.json", "C%3A%5Cwindows.png", "x.png:stream"):
        assert client.get(f"/api/documents/{doc_id}/figures/{name}").status_code == 404, name
