"""Real wall-clock timing via time.perf_counter() (cross-platform, monotonic). No estimated values."""
import time
from contextlib import contextmanager
from typing import Optional

STAGES = ("ingestion", "ocr", "layout_analysis", "table_extraction", "assembly", "validation", "output_generation")


def compute_metrics(elapsed: float, pages: int) -> dict:
    """Throughput metrics from a measured duration. Never divides by zero; invalid input gives zeros."""
    try:
        elapsed = float(elapsed)
        pages = int(pages)
    except (TypeError, ValueError):
        elapsed, pages = 0.0, 0
    if not elapsed == elapsed or elapsed < 0:  # NaN or negative
        elapsed = 0.0
    pages = max(pages, 0)
    spp = elapsed / pages if pages > 0 else 0.0
    pps = pages / elapsed if pages > 0 and elapsed > 0 else 0.0
    return {"processing_time_seconds": round(elapsed, 3), "pages_processed": pages,
            "seconds_per_page": round(spp, 3), "pages_per_second": round(pps, 3)}


class StageTimer:
    """Accumulates exclusive time per stage: time in a nested stage is not also counted in its parent."""

    def __init__(self) -> None:
        self.totals: dict[str, float] = {}
        self._stack: list[list] = []  # [name, start, child_time]

    @contextmanager
    def stage(self, name: str):
        entry = [name, time.perf_counter(), 0.0]
        self._stack.append(entry)
        try:
            yield
        finally:
            self._stack.pop()
            dur = time.perf_counter() - entry[1]
            self.totals[name] = self.totals.get(name, 0.0) + max(dur - entry[2], 0.0)
            if self._stack:
                self._stack[-1][2] += dur

    def as_dict(self) -> dict[str, float]:
        out = {s: round(self.totals.get(s, 0.0), 3) for s in STAGES}
        out.update({k: round(v, 3) for k, v in self.totals.items() if k not in out})
        return out


def optional_stage(timer: Optional[StageTimer], name: str):
    return timer.stage(name) if timer is not None else _noop()


@contextmanager
def _noop():
    yield
