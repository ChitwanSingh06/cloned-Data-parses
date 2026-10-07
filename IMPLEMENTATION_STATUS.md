# ParseAnything — Implementation Status

Pipeline: `PDF → detect/route → extract → assemble → confidence → provenance → canonical Document → document.json + document.md`
Markdown is rendered **only** from the canonical document dict (`output/markdown_builder.py`); the PDF is never re-parsed.

## Audit of the starter (before this work)
Every backend/frontend file was a ~1-line stub (≈10 KB total): no extraction, no models beyond bare shells, empty `test_api/test_ocr/test_tables`, broken Dockerfile (`COPY ../data`), `build` script was `vite`. The folder structure was kept unchanged; every stub was filled in place.

## Verified working (21 backend tests pass: `cd backend && python -m pytest -q`; frontend `npx vite build` succeeds)
| Area | State | Where |
|---|---|---|
| Canonical model (Document/Page/Block/Provenance/Table) | done | `models/` |
| PDF validation, corrupt/encrypted/unsupported → structured errors (<1 s) | done | `pipeline/detector.py`, `failsafe.py` |
| Digital text (spans→lines→paragraphs, font size/bold, dehyphenation, bullet gluing) | done | `extractors/text/pdf_text.py` |
| Classification: heading, paragraph, list, caption, footnote, header/footer, reference, equation candidate | done (heuristic) | `pdf_text.classify`, `assembler.py` |
| Scanned-page detection + OCR (render → OCR → pt-space bboxes + per-word confidence) | done, Tesseract tested | `ocr_engine.py`, `detector._ocr_regions` |
| Mixed digital/scanned documents | done, tested | same pipeline for both |
| Tables: ruled (PyMuPDF), merged cells (row/colspan), multi-row headers, flattened `A / B` labels in MD | done, tested | `tables/` |
| Tables on scanned pages (OpenCV ruling-line grid + OCR words per cell) | done, tested; **no spans** | `table_detector.detect_tables_image` |
| Cross-page table merge (col count, width, edge alignment, repeated header, vertical continuity; score + signals recorded) | done, tested (3-page, 79 rows) | `assembler._merge_tables` |
| Cross-page paragraph / column-jump merge, list merge across items/pages | done | `assembler.py` |
| Reading order: gutter detection, spanning blocks, columns, sidebars last, footnotes/footers at end, ambiguity warning | done, 2-col tested | `reading_order.py` |
| Repeated header/footer + page-number removal from MD (kept in JSON) | done, tested | `assembler._classify_margins` |
| Heading hierarchy (numbering depth, else font-size rank) + `parent_id`/`section_id` | done | `assembler._heading_levels` |
| Figures (embedded images + vector clusters + raster blobs), crops saved, caption linking | done, tested | `figures/figure_extractor.py` |
| Charts: detected via caption/vector heuristics, preserved as image, **values NOT extracted**, flagged REVIEW_REQUIRED | honest placeholder | `charts/` |
| Equations: detected heuristically, region image + raw text kept, `latex=null`, REVIEW_REQUIRED; optional `pix2tex` hook | LaTeX never invented | `equations/` |
| Confidence engine (0.6·mean + 0.4·min of real signals, HIGH ≥0.85 / MEDIUM ≥0.6 / LOW; REVIEW_REQUIRED below 0.6 or on explicit reason) | done | `pipeline/confidence.py` |
| Provenance (document, page, bbox, extractor, region id, all merged `sources`) | done | `pipeline/provenance.py` |
| Fail-safe: per-region try/except, `PARTIAL_SUCCESS`, error codes | done, tested | `failsafe.py`, `router.py` |
| Stats: time, pages, s/page, peak memory, block/confidence counts | done | `orchestrator._stats` |
| API: upload, async parse + status, result, JSON/MD download, page PNG, figure PNG | done, smoke-tested live | `api/` |
| Frontend: upload, parse, polling, stats, MD/JSON/blocks tabs, confidence badges, review flags, downloads, click-block → page + bbox highlight | builds; **not browser-tested** | `frontend/src` |

## Known limitations / not done
- **Only PDF is implemented.** `docx/pptx/xlsx/image` handlers are still stubs; those inputs return `UNSUPPORTED_FORMAT`.
- **PaddleOCR / PP-Structure not integrated or tested** (not installed here). `ocr_engine.py` auto-selects Paddle if importable (code path unverified); Tesseract is the tested engine. No learned layout model: layout = PyMuPDF geometry + heuristics.
- Scanned pages: no deskew (would require mapping boxes back), no bold info (headings by line height only), Tesseract misreads some bullets (`•` → `¢`/`e`) so scanned lists become paragraphs; scanned tables have no merged cells.
- Borderless tables: conservative text-alignment fallback (needs ≥3×3, numeric content), always low confidence → REVIEW_REQUIRED; not tested on real documents.
- Table header-row detection is heuristic (non-numeric leading rows).
- Equations: no recognizer bundled → no LaTeX. Charts: no data extraction (by design, no hallucination).
- Reading order: gutters computed once per page (not per band); complex magazine layouts untested.
- Tested only on synthetic reportlab PDFs, not real-world financial/legal documents. No benchmarking yet. Scanned page ≈3 s/page (Tesseract, 200 DPI, `OMP_THREAD_LIMIT=1`).
- Source highlighting is implemented client-side against server-rendered PNGs (no pdf.js dependency).

## Next steps (priority)
1. Run on real PDFs (financial statements, 2-column papers) and fix heuristics; add a benchmark script.
2. Install `requirements-paddle.txt`, validate the Paddle OCR path, consider PP-Structure for layout/table cells.
3. Add a formula model (pix2tex/UniMERNet) and a chart-to-table model; keep REVIEW_REQUIRED when unsure.
4. Non-PDF formats (docx/xlsx/pptx/image → reuse canonical model; images can go via `pymupdf.open(png).convert_to_pdf()`).
5. Browser-test the frontend; add a small Markdown renderer tab.

## Commands
```bash
# backend
cd backend && pip install -r requirements.txt && sudo apt-get install tesseract-ocr   # Windows: install Tesseract from UB-Mannheim (see README)
python -m pytest -q
uvicorn app.main:app --reload            # http://localhost:8000/docs
# frontend
cd frontend && npm install && npm run dev  # http://localhost:5173
# docker
docker compose up --build
```
Outputs land in `data/processed/<document_id>/{document.json,document.md,figures/}`; uploads in `data/uploads/`.
