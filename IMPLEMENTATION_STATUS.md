# ParseAnything — Implementation Status

Pipeline: `PDF → detect/route → extract → assemble → confidence → provenance → canonical Document → document.json + document.md`
Markdown is rendered **only** from the canonical document dict (`output/markdown_builder.py`); the PDF is never re-parsed.

## Audit of the starter (before this work)
Every backend/frontend file was a ~1-line stub (≈10 KB total): no extraction, no models beyond bare shells, empty `test_api/test_ocr/test_tables`, broken Dockerfile (`COPY ../data`), `build` script was `vite`. The folder structure was kept unchanged; every stub was filled in place.

## Verified working (100 backend tests pass: `cd backend && python -m pytest -q`; frontend build remains environment-unverified)
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
| Frontend: upload, parse, polling, stats, MD/JSON/blocks tabs, confidence badges, review flags, downloads, format-aware source navigation; PDF click-block → page + bbox highlight, PPTX → slide/element, XLSX → worksheet/range, DOCX → structural anchor | source-navigation code added; browser build remains environment-unverified | `frontend/src` |

## Update: handwriting HTR, chart extraction, equations (this iteration)
| Area | State | Where |
|---|---|---|
| Printed OCR (Tesseract/Paddle) + Windows `tesseract.exe` lookup (`TESSERACT_CMD` → PATH → Program Files → Program Files (x86)) | done, tested | `ocr_engine.py`, `utils/platform_utils.py` |
| Printed-vs-handwriting routing (baseline jitter + stroke-width variation **and** weak OCR confidence; confident printed lines are never re-routed) | done, tested on synthetic strokes | `ocr/handwriting.py` |
| Local HTR (TrOCR via torch+transformers, optional, `requirements-htr.txt`, `PARSE_HTR=auto|off`) | wired + tested with a mocked recognizer; **real TrOCR not run here (model not installed)** | `ocr/htr_engine.py`, `detector._ocr_regions` |
| HTR/OCR failure or no model | line/region kept and flagged `REVIEW_REQUIRED` with `review_reason`; unreadable handwriting blobs preserved as images; OCR engine failure preserves the whole page image | `detector.py` |
| Unified blocks carry `htr` or `ocr` signal, `meta.text_kind`, bbox in PDF points, provenance | done | |
| Charts (vector): candidate → group axis/tick/title/legend text → type → axis calibration (regression of printed ticks) → values → ONE chart block; bar, line, pie, scatter, histogram | done, tested on drawn PDFs | `charts/chart_extractor.py`, `detector._digital_regions` |
| Chart text (ticks, categories, titles, axis labels) is absorbed into the chart block and no longer emitted as paragraphs | done, tested | |
| Values only from printed data labels or tick calibration; no calibration ⇒ chart preserved, `data_extracted=false`, REVIEW_REQUIRED | done, tested | |
| Equations: span/char geometry → LaTeX (superscripts, subscripts, fractions, radicals, ∑/∏ limits, ∫, Greek, operators, `\tag`); Unicode super/subscripts; pix2tex fallback; otherwise preserved + flagged | done, tested | `equations/math_layout.py`, `equation_extractor.py` |
| Equation block: `content={raw_text, latex}`, bbox, confidence, provenance; Markdown `$$\n…\n$$` (never a heading) | done | `markdown_builder.py` |
| Frontend: react-markdown + KaTeX renderer (raw/rendered toggle), chart/equation previews | builds; not browser-tested | `MarkdownViewer.jsx` |

### Limits of this iteration
- Charts: **vector** charts only. Raster chart images are preserved and flagged (no pixel-level bar/line reading). Horizontal bar charts, log axes, dual axes, stacked bars and rotated/overlapping tick labels are not handled (flagged, values not extracted). Pie shares come from wedge angles (percent), not absolute values.
- Equations: structural LaTeX needs a text layer. Scanned equations need pix2tex (optional, not bundled). No matrices/cases/accents; nested scripts are flattened; unmapped Unicode symbols are kept verbatim and lower confidence.
- Handwriting: detection is heuristic; tested on synthetic strokes only, never on real handwriting or the real TrOCR model. Without the model, probable handwriting is flagged, not read.

## Update: processing time + performance metrics (this iteration)
| Area | State | Where |
|---|---|---|
| Real timing with `time.perf_counter()` (no fake values); total, pages, seconds/page, pages/second | done, tested | `pipeline/timing.py` (`compute_metrics`), `orchestrator.parse_pdf` |
| Division-safe: 0 pages, 0 s, negative, NaN, None, non-numeric all return zeros, never raise | done, tested | `compute_metrics` |
| Stage timing (exclusive, nested time not double counted): ingestion, ocr, layout_analysis, table_extraction, assembly, validation, output_generation | done, tested | `StageTimer`; hooks in `detector.py`, `router.py`, `orchestrator.py` |
| Added to the EXISTING `Document` model as `timing` (no new response model); also in `document.json`, `/api/result`, `/api/status` | done | `models/document.py`, `api/jobs.py` |
| Results page: pages processed, seconds, sec/page, pages/sec from backend values, plus per-stage line | builds; not browser-tested | `frontend/src/pages/Results.jsx`, `index.css` |

`timing` shape: `{processing_time_seconds, pages_processed, seconds_per_page, pages_per_second, stages: {ingestion, ocr, layout_analysis, table_extraction, assembly, validation, output_generation}}`. Existing `processing_time` and `stats.seconds_per_page` keep their old meaning and now come from the same measurement.

Timing notes: `layout_analysis` covers region detection and block routing, excluding OCR and table time. `output_generation` covers Markdown build/write and JSON serialisation; the final JSON file write happens after the total is fixed, so stage sum is slightly below total. Stages are summed across pages. 92 backend tests pass (`tests/test_timing.py` adds 15 cases); `npx vite build` succeeds.

## Update: bounding-box document search (this iteration)
| Area | State | Where |
|---|---|---|
| `POST /api/search` `{document_id, query, limit?}`; reads the saved canonical `document.json` and validates it with the existing `Document` model. The PDF is never re-parsed, no second document representation | done, tested | `api/search.py`, `search/engine.py`, `models/search.py` |
| Hit fields: `matched_text`, `block_id`, `page`, `bbox`, `block_type`, `confidence`, `confidence_level`, `status`, `reading_order` (1-based index in global order), `snippet`, `match_count`, `provenance` (existing `Provenance` model) | done | `SearchHit` |
| Matching: case-insensitive, partial (substring), phrase (whitespace in the query matches any whitespace run; quoted query = phrase), regex characters literal, one hit per block in reading order, `limit` + `truncated`, no-result `message`, blank query rejected (422), bad id 400, unparsed id 404 | done, tested | `build_pattern`, `search_document` |
| Searched text: paragraph, heading, caption, header/footer/footnote/reference, list items, table cells (each cell matched separately, so a phrase never spans two cells), equation raw text + LaTeX, chart title/axis labels/categories/series names, text embedded in figures. OCR and handwriting text are ordinary block text, so they are searchable | done, tested | `block_texts` |
| Results page: search box ("Search document..."), hit list (matched text, page, type, confidence, order, snippet). Clicking a hit sets the existing selected block and page, so the EXISTING `DocumentViewer` + `BoundingBox` navigate to the page and highlight the bbox; block info line shows type, page, confidence, extractor, bbox | `vite build` succeeds; **not browser-tested** | `SearchPanel.jsx`, `Results.jsx` |

Search limits: matches the extracted text only (no fuzzy/stemming/word-order-independent matching; a multi-word query must be a contiguous phrase). Highlight is the whole block bbox (table cell bboxes exist in the model but are not used). Numeric chart values are not searched. Search reads `document.json` from disk, so a document must be parsed first. 92 backend tests pass (`tests/test_search.py` adds 11).

## Update: automatic document summary (this iteration)
| Area | State | Where |
|---|---|---|
| Deterministic local summary built ONLY from the canonical blocks after parsing (no re-parse, no network, no API key, no LLM). Stored as `summary` on the existing `Document` model, so it is in `document.json`, `/api/result/{id}` and the JSON download; a summary error never fails a parse (stage time recorded as `summary` in `timing.stages`) | done, tested | `summary/summarizer.py`, `models/document.py`, `orchestrator.py` |
| Overview: title (first top-level heading, flagged if low confidence), filename, pages, `source_kind` (digital/scanned/mixed from page analysis). `language` and `document_type` are always `null` because the pipeline does not detect them (nothing is claimed) | done | `build_summary` |
| Executive summary: one templated sentence of counted facts (pages, tables, figures, equations, main sections) + up to 3 extractive sentences copied verbatim (frequency scoring, heading-term and early-position boost, de-duplicated); each sentence is returned with its `block_id`, page, confidence in `executive_sources` | done | |
| Key points: next-ranked sentences (up to 6) + factual table/chart points (caption, shape, column headers, chart type; "values not extracted" when so). Each has block id/page/confidence/`uncertain` | done | |
| Major sections: the top two heading levels present, document order, max 20, page + block id | done | |
| Statistics: pages, text blocks (heading/paragraph/list/caption/footnote/reference), tables, figures, charts, equations, words, low-confidence blocks (LOW level), review-required blocks, total blocks | done | |
| Hallucination safety: low-confidence / REVIEW_REQUIRED blocks are excluded from executive summary and key points whenever reliable text exists (warning states how many were left out); uncertain headings are listed but flagged and never used as the stated title/sections; if ALL text is low confidence it is used but `status="uncertain"` with a prominent warning; empty/failed documents get `status="empty"` and an honest message | done, tested | |
| Frontend: new default **Summary** tab (Document Overview, Executive Summary, Key Points, Major Sections, Statistics); key points and sections are clickable and reuse the existing viewer/bbox highlight; "low confidence" pills; old documents without a summary show a "parse again" note | `vite build` succeeds; **not browser-tested** | `SummaryPanel.jsx`, `Results.jsx` |

Summary limits: purely extractive (no paraphrase, no cross-sentence synthesis), English-oriented stopword list and sentence splitter, no document-type or language inference, table/chart key points describe structure only (not numeric findings). Sentence quality depends on extraction quality (e.g. the last sentence of a block may be cut by the page). No optional LLM provider exists in this codebase, so none was added. 92 backend tests pass (`tests/test_summary.py` adds 13).

## DOCX SUPPORT

| Area | State | Details |
|---|---|---|
| DOCX dependency | done | Added `python-docx` to `backend/requirements.txt`; no new DOCX-specific runtime dependency beyond the standard library package. |
| Format routing | done | `.pdf` continues through the existing PDF pipeline; `.docx` routes through `formats/docx_handler.py`; unsupported extensions return the existing structured `UNSUPPORTED_FORMAT` error. |
| Paragraphs/headings | done | Paragraph text, paragraph index, heading level, and basic Word style/run information are preserved. |
| Lists | done | Basic Word ordered/unordered list styles are grouped into canonical `list` blocks with ordered flag and item provenance. |
| Tables | done | Rows, columns, cell text, row/column positions, header row, and reliable `gridSpan` colspan information are preserved in the existing `TableData` model. |
| Embedded images | done | Embedded images are detected and saved under the existing processed document `figures/` directory; canonical `figure` blocks record image/paragraph provenance. |
| Canonical model | done | DOCX emits the existing `Document`, `Block`, `Page`, `TableData`, confidence, provenance, status, summary, timing, JSON and Markdown structures. |
| Reading order | done | Original Word body XML order is preserved. PDF coordinate-based reading-order logic is not applied. |
| Provenance | done | Structural metadata uses `source_type=docx` plus paragraph/table/image indices. PDF-style bounding boxes are never fabricated. |
| Confidence | done | Existing confidence engine is reused with structural extraction/classification signals; no arbitrary page-coordinate signals are introduced. |
| Timing | done | DOCX reports processing time plus `logical_units_processed`; physical page throughput is zero rather than a fabricated page count. |
| Source viewer | intentionally omitted | Existing PDF page/bbox viewer is disabled for DOCX; results still expose Markdown, JSON, blocks, search, confidence, provenance and downloads. |
| Tests | done | Full backend suite: **95 passed**. Dedicated DOCX tests cover upload, detection, parsing, headings, lists, tables, images, Markdown, JSON, provenance and unsupported-format behavior. |
| Frontend build | pending environment verification | `npm run build` could not run because Vite was absent; `npm ci` timed out in the execution environment. No frontend source-level build result is claimed. |

### DOCX provenance limitations
DOCX does not expose PDF-style page coordinates through `python-docx`. The canonical model still requires an integer page/location field, so DOCX uses `page=1` only as a **logical document unit**, with page dimensions set to zero and explicit `unit_label`/`logical_units_processed` metadata. No physical page number, bbox, or source highlight is claimed.

### Known DOCX limitations
- Word layout is not rendered into physical pages.
- Custom numbering definitions outside the common Word list styles are handled conservatively.
- Table `gridSpan` colspan is preserved where exposed; complex vertical merge geometry is not reconstructed when `python-docx` does not expose it reliably.
- Images are preserved as figures and extracted to the processed document directory, but DOCX drawing coordinates are not converted into fake bboxes.
- Existing PDF-only source highlighting remains unavailable for DOCX.

## Known limitations / not done
- **PDF remains the primary format. DOCX is now implemented.** XLSX/image inputs remain unsupported and return `UNSUPPORTED_FORMAT`; PPTX is now implemented.
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
4. Browser-test the frontend across the supported PDF/DOCX/PPTX/XLSX upload and results paths after installing the frontend dependencies.

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

## PPTX SUPPORT

| Area | State | Details |
|---|---|---|
| PPTX dependency | done | Added `python-pptx` to `backend/requirements.txt`; no XLSX or multilingual dependency/work was added. |
| Format routing | done | `.pptx` routes through `formats/pptx_handler.py`; PDF and DOCX routes remain unchanged. Unsupported extensions now report PDF/DOCX/PPTX as the supported document formats. |
| Slides | done | Each PPTX slide is represented as one logical canonical page with its slide number, slide dimensions, block IDs, and text character count. |
| Text/headings | done | Slide text is extracted from text frames; title/center-title placeholders become canonical `heading` blocks; other text becomes `paragraph` blocks with basic font/style metadata. |
| Lists | done | Explicit bullet and auto-number XML is detected and consecutive compatible list paragraphs are grouped into the existing canonical `list` block. |
| Tables | done | PPTX table shapes are converted into the existing `TableData`/`Cell` models with rows, columns, cell text and header-row information. |
| Images | done | Embedded picture shapes are extracted as PNGs under the existing processed-document `figures/` directory and emitted as canonical `figure` blocks. |
| Layout/provenance | done | Shape coordinates are converted from PPTX EMU to points and stored as slide-region bboxes. Provenance records `source_type=pptx`, `slide_number`, `shape_index`, and image/table indices where applicable. |
| Reading order | done | Native slide shape order is preserved. No PDF coordinate-reading-order algorithm is applied. |
| Confidence | done | Existing confidence engine is reused with real structural extraction/list/table/image signals. |
| Summary | done | Existing canonical-document summary generator is reused; no PPTX-specific summary system was created. |
| Output | done | PPTX produces the same `document.json` and `document.md` outputs as the other supported formats. |
| Timing/stats | done | Processing metrics use slides as the meaningful logical page unit; no physical PDF page count is fabricated. |
| Frontend | done | Upload accepts `.pptx`; Results treats PPTX as slide-based logical pages and disables the PDF source viewer rather than fabricating PDF images. |
| Tests | done | Dedicated PPTX fixture/tests cover slide text, heading, unordered/ordered lists, table, image, slide provenance, JSON/Markdown outputs, API upload/parse/download, and PDF-only source-viewer behavior. Full backend suite: **97 passed**. |
| Frontend build | pending environment verification | `npm run build` could not execute because the environment has no installed `vite` binary. No successful frontend build is claimed. |

### PPTX provenance/layout limitations
PPTX provides slide coordinates through `python-pptx`, so block bboxes are honest slide-region coordinates converted from EMU to points. They are **not PDF page coordinates**. Each slide is a logical page for the canonical model. The existing PDF page-image source viewer is intentionally unavailable for PPTX; slide rendering was not added just to imitate PDF behavior.

### Known PPTX limitations
- Text extraction follows PowerPoint text-frame/shape order; it does not attempt full visual reading-order reconstruction.
- Heading detection is conservative and primarily recognizes title/center-title placeholders.
- Lists rely on explicit PowerPoint bullet/numbering XML or indentation level; unusual inherited/custom list definitions may be classified conservatively.
- Tables preserve the normal PPTX grid structure; complex visual merge semantics are not reconstructed beyond what `python-pptx` exposes reliably.
- Embedded pictures are preserved as figures, but chart semantics/values inside raster or native chart objects are not separately interpreted.
- Grouped/complex SmartArt and other specialized PowerPoint objects are not converted into invented semantic content.
- Speaker notes, animations, transitions, comments, and other presentation metadata are not extracted because they are outside the requested slide-content scope.
- No PPTX-to-PDF rendering or slide-image viewer was introduced.

## XLSX SUPPORT

| Area | State | Details |
|---|---|---|
| XLSX dependency | done | Added `openpyxl` to `backend/requirements.txt`; no multilingual work was added. |
| Format routing | done | `.xlsx` routes through `formats/xlsx_handler.py`; PDF, DOCX and PPTX routes remain intact. |
| Worksheets | done | Each worksheet is represented as one logical canonical page, preserving worksheet order and sheet name. |
| Cell values | done | Non-empty worksheet cells are extracted with their native scalar values where JSON-safe; dates/times use ISO strings and formulas are preserved as formula strings. |
| Structured ranges | done | Each non-empty worksheet becomes a structured canonical `table` block with rows, columns, cells, inferred header row where conservative, and the used cell range. The spreadsheet is not flattened into one paragraph. |
| Excel tables | done | Existing worksheet table names and references are preserved in table metadata when `openpyxl` exposes them. |
| Row/column structure | done | Canonical `TableData` preserves row/column indices and `Cell` entries; worksheet metadata records start/end rows and columns. |
| Sheet names | done | Each worksheet emits a canonical `heading` block before its table block, so names are retained in JSON and Markdown. |
| Provenance | done | Worksheet/range provenance is attached to the block; `cell_provenance` records worksheet, cell address, row, column and column letter for individual cells. No PDF coordinates are invented. |
| Confidence | done | Existing confidence engine is reused with structural worksheet/cell extraction signals. |
| Summary | done | Existing canonical-document summary generator is reused; XLSX is treated as a logical-document format. |
| Output | done | XLSX produces the same `document.json` and `document.md` outputs as the other supported formats. |
| Timing/stats | done | Processing metrics use worksheets as the meaningful logical unit; no physical page count is fabricated. |
| Frontend | done | Upload accepts `.xlsx`; existing Results UI treats XLSX as a logical-unit format and does not expose the PDF source viewer. |
| Tests | done | Dedicated XLSX fixture/tests cover multiple worksheets, sheet names, structured cells/ranges, Excel table metadata, cell provenance, Markdown/JSON output, API upload/parse/download, and corrupt XLSX handling. Full backend suite: **100 passed**. |
| Frontend build | pending environment verification | The environment has no installed Vite binary, so no successful frontend build is claimed. |

### XLSX provenance/layout limitations
XLSX does not provide PDF-style page coordinates. Worksheet blocks therefore have `bbox=null`; worksheet number, name, used range, row/column positions, and cell addresses are the authoritative structural provenance. Logical page width/height use worksheet column/row counts only for the canonical `Page` shape and are not physical dimensions.

### Known XLSX limitations
- One structured table block is emitted per non-empty worksheet rather than attempting to infer multiple arbitrary disconnected visual regions.
- The first row is used as a Markdown header only when it conservatively looks like a label row; all original cells remain preserved regardless.
- Formula cells are preserved as formulas because the workbook is loaded with `data_only=False`; calculated cached results are not separately materialized.
- Charts, drawings, comments, formulas' calculated values, formatting semantics, and other spreadsheet presentation metadata are outside this requested extraction scope.
- Merged-cell visual layout is not reconstructed into invented PDF-style coordinates.

## FORMAT-AWARE SOURCE NAVIGATION

| Format | Navigation behavior | Exact highlighting | Fallback / limitations |
|---|---|---|---|
| **PDF** | Existing PDF page viewer; selected/search blocks navigate to the canonical page. | **Yes** — existing PDF-point bbox overlay is preserved unchanged. | Existing PDF behavior remains the authoritative visual source viewer. |
| **PPTX** | Format-aware slide preview uses the canonical slide/page number and existing shape provenance. Clicking a block or search hit moves the preview to the correct slide. | **Yes, when the parser has a reliable shape bbox** — the existing PPTX slide/shape coordinates are rendered as element regions and the selected element is highlighted. | No fake coordinates are created. If a block has no bbox, the UI identifies it as slide navigation only. The preview is a structural slide rendering rather than a PowerPoint-native renderer; unsupported visual objects are not reconstructed. |
| **XLSX** | Format-aware worksheet preview uses the canonical worksheet/page and existing worksheet/range provenance. Clicking a block or search hit moves to the correct worksheet and source range. | **Yes** — the canonical used range is rendered as a structured sheet grid and the source range is selected/highlighted. | XLSX provenance is structural (`worksheet`, `cell`/`range`); no PDF-style coordinates are invented. The preview uses canonical extracted cell values rather than opening arbitrary filesystem paths. |
| **DOCX** | Format-aware document preview uses stable structural anchors derived from existing paragraph/table/image provenance. Clicking a block or search hit scrolls to the corresponding paragraph, table, or image anchor. | **Structural highlight only** for paragraphs/tables/images; no pixel coordinates are fabricated. Table cell highlighting is shown when row/column provenance is available. | DOCX has no reliable PDF-style page coordinates in the current extraction path. The preview is a canonical structural rendering, not a Word layout renderer. |

### Shared source-navigation behavior
- The existing `Block.provenance.sources` structure remains the single source of truth; no duplicate provenance model was introduced.
- Search results continue to come from the saved canonical `document.json`. Clicking a search result selects the same block used by the normal block list, so search and parsed-content navigation share one source-navigation path.
- PDF continues to use the existing `DocumentViewer` and bbox overlay. DOCX, PPTX and XLSX use one format-aware `SourceViewer` within the existing Results-page layout rather than separate Results pages.
- Visual source labels are format-aware: PDF shows page/bbox, PPTX shows slide/element, XLSX shows worksheet/cell-or-range, and DOCX shows paragraph/table/image location.
- Missing or incomplete provenance falls back to the most reliable available structural location and never fabricates a bbox.
- Source navigation uses document IDs and canonical result data only; no arbitrary source filesystem paths are exposed by the frontend.

### Format-aware source-navigation tests
- Full backend regression suite: **102 passed** after the navigation changes; PDF, DOCX, PPTX and XLSX extraction/provenance tests remain green.
- Existing API tests continue to verify that PDF page rendering remains PDF-only and that non-PDF formats do not receive fabricated PDF page images.
- Existing format tests verify PPTX slide/bbox provenance, XLSX worksheet/range/cell provenance, and DOCX paragraph/table/image provenance with `bbox=None` where coordinates are unavailable.
- Frontend source navigation was added in `components/SourceViewer.jsx` and the existing `Results.jsx`/`SearchPanel.jsx` click path now selects canonical blocks for all four formats.
- A frontend production build could not be completed in this environment because `npm ci` timed out and the environment has no installed Vite binary; no successful build is claimed.

### PPTX preview rendering correction
- The PPTX source viewer was corrected to group paragraphs belonging to the same PowerPoint shape instead of absolutely rendering every paragraph block over the full shape region. This removes duplicated/overlapping text in the source preview.
- PPTX tables are rendered as structured tables inside their existing shape region.
- Extracted PPTX images are displayed through the existing document-scoped figure endpoint.
- Existing parser bboxes remain the only source of slide element geometry; no new coordinates are fabricated.
- Slide navigation controls now change the source preview page without changing the extraction model.

### Known source-navigation limitations
- PPTX preview is a browser-rendered structural slide view based on existing shape bboxes; it is not a PowerPoint-native rendering engine.
- XLSX preview is a structured worksheet grid based on canonical extracted cells; formulas retain their existing canonical representation and no arbitrary workbook path is opened in the browser.
- DOCX preview preserves structural order and anchors but does not claim Word's physical pagination or pixel geometry.
- Exact PDF bbox highlighting is unchanged from the existing implementation.

## Current supported input scope after this iteration
- **PDF:** primary and most complete format.
- **DOCX:** supported through the canonical document pipeline.
- **PPTX:** supported through the canonical document pipeline.
- **XLSX:** supported through the canonical document pipeline.
- **Image input:** not implemented.
- **Multilingual support:** not implemented.
