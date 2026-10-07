"""Small cross-platform helpers so the backend runs unchanged on Windows, Linux and macOS.

- ``peak_memory_mb``: the stdlib ``resource`` module is POSIX-only, so Windows uses the Win32
  ``GetProcessMemoryInfo`` call through ``ctypes`` (stdlib, no extra dependency).
- ``find_tesseract``: on Windows the Tesseract installer does not add itself to PATH, so look in
  the standard install locations as well.
"""
import os
import shutil
import sys
from functools import lru_cache
from pathlib import Path
from typing import Optional

_MB = 1024 * 1024


def _peak_memory_windows() -> float:
    """Peak working set of this process in MB (the Windows equivalent of ru_maxrss)."""
    import ctypes
    from ctypes import wintypes

    class PROCESS_MEMORY_COUNTERS(ctypes.Structure):
        _fields_ = [
            ("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD),
            ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t),
            ("QuotaPeakPagedPoolUsage", ctypes.c_size_t), ("QuotaPagedPoolUsage", ctypes.c_size_t),
            ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t), ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
            ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t),
        ]

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    psapi = ctypes.WinDLL("psapi", use_last_error=True)
    kernel32.GetCurrentProcess.restype = wintypes.HANDLE  # explicit types: handles are 64-bit
    psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(PROCESS_MEMORY_COUNTERS), wintypes.DWORD]
    psapi.GetProcessMemoryInfo.restype = wintypes.BOOL
    counters = PROCESS_MEMORY_COUNTERS()
    counters.cb = ctypes.sizeof(counters)
    if not psapi.GetProcessMemoryInfo(kernel32.GetCurrentProcess(), ctypes.byref(counters), counters.cb):
        raise ctypes.WinError(ctypes.get_last_error())
    return counters.PeakWorkingSetSize / _MB


def peak_memory_mb() -> float:
    """Peak resident memory of this process in MB; 0.0 if the platform cannot report it. Never raises."""
    try:
        if sys.platform == "win32":
            return round(_peak_memory_windows(), 1)
        import resource  # POSIX only
        rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        return round(rss / (_MB if sys.platform == "darwin" else 1024), 1)  # macOS: bytes, Linux: KB
    except Exception:
        return 0.0


def _windows_tesseract_candidates() -> list[Path]:
    roots = [os.environ.get("ProgramFiles"), os.environ.get("ProgramW6432"), os.environ.get("ProgramFiles(x86)"),
             r"C:\Program Files", r"C:\Program Files (x86)"]
    cands = [Path(r) / "Tesseract-OCR" / "tesseract.exe" for r in roots if r]
    local = os.environ.get("LOCALAPPDATA")  # per-user installs
    if local:
        cands += [Path(local) / "Programs" / "Tesseract-OCR" / "tesseract.exe", Path(local) / "Tesseract-OCR" / "tesseract.exe"]
    return cands


@lru_cache(maxsize=1)
def find_tesseract() -> Optional[str]:
    """Path to the tesseract executable, or None. Order: $TESSERACT_CMD, PATH, standard Windows install dirs."""
    explicit = os.environ.get("TESSERACT_CMD")
    if explicit:
        hit = shutil.which(explicit) or (explicit if Path(explicit).is_file() else None)
        if hit:
            return str(hit)
    on_path = shutil.which("tesseract")
    if on_path:
        return on_path
    if sys.platform == "win32":
        for cand in _windows_tesseract_candidates():
            if cand.is_file():
                return str(cand)
    return None
