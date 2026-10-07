import { useEffect, useMemo, useState } from "react";
import ConfidenceBadge from "../components/ConfidenceBadge";
import DocumentViewer from "../components/DocumentViewer";
import DownloadButtons from "../components/DownloadButtons";
import MarkdownViewer from "../components/MarkdownViewer";
import OutputViewer from "../components/OutputViewer";
import SearchPanel from "../components/SearchPanel";
import SourceViewer from "../components/SourceViewer";
import SummaryPanel from "../components/SummaryPanel";
import { getMarkdown, getResult } from "../services/api";
import { rememberDocument } from "../lib/recent";

const STAGE_LABELS = { ingestion: "Ingestion", ocr: "OCR", layout_analysis: "Layout analysis", table_extraction: "Table extraction", assembly: "Assembly", validation: "Validation", output_generation: "Output generation" };
const num = (v, digits) => (typeof v === "number" && Number.isFinite(v) ? v.toFixed(digits) : "n/a");

const TABS = [["summary", "Summary"], ["blocks", "Extracted content"], ["tables", "Tables"], ["markdown", "Markdown"], ["json", "JSON"], ["metadata", "Metadata"]];

// Structured, read-only grid for an extracted table block (cells come straight from the block).
function TableGrid({ block }) {
  const cells = block.content?.cells || [];
  const rows = block.content?.n_rows || 0;
  const cols = block.content?.n_cols || 0;
  const byPos = new Map(cells.map((c) => [`${c.row},${c.col}`, c]));
  // grid positions covered by another cell's rowspan/colspan are skipped
  const covered = new Set();
  for (const c of cells) for (let r = c.row; r < c.row + (c.rowspan || 1); r++) for (let k = c.col; k < c.col + (c.colspan || 1); k++) if (r !== c.row || k !== c.col) covered.add(`${r},${k}`);
  return (
    <div className="grid-scroll">
      <table className="data-table"><tbody>
        {Array.from({ length: rows }, (_, r) => (
          <tr key={r}>{Array.from({ length: cols }, (_, c) => {
            if (covered.has(`${r},${c}`)) return null;
            const cell = byPos.get(`${r},${c}`);
            const Tag = cell?.is_header ? "th" : "td";
            return <Tag key={c} rowSpan={cell?.rowspan > 1 ? cell.rowspan : undefined} colSpan={cell?.colspan > 1 ? cell.colspan : undefined}>{cell?.text ?? ""}</Tag>;
          })}</tr>
        ))}
      </tbody></table>
    </div>
  );
}

const preview = (b) => {
  if (b.type === "table") return `table ${b.content.n_rows}×${b.content.n_cols}${b.content.page_span?.length > 1 ? ` (pages ${b.content.page_span.join("–")})` : ""}`;
  if (b.type === "list") return `${b.content.items.length} items: ${b.content.items[0]}`;
  if (b.type === "chart" && b.content?.chart_type) {
    const n = b.content.series?.[0]?.points?.length ?? 0;
    return `${b.content.chart_type} chart${b.content.title ? ": " + b.content.title : ""} (${n} points${b.content.data_extracted ? "" : ", values not extracted"})`;
  }
  if (b.type === "equation") return b.content?.latex ? `$ ${b.content.latex} $` : `unrecognised: ${b.content?.raw_text ?? ""}`;
  if (["figure", "chart"].includes(b.type)) return `${b.type}${b.meta?.caption ? ": " + b.meta.caption : ""}`;
  return String(b.content).slice(0, 110);
};

export default function Results({ docId, onReset }) {
  const [doc, setDoc] = useState(null);
  const [md, setMd] = useState("");
  const [tab, setTab] = useState("summary");
  const [selectedId, setSelectedId] = useState(null);
  const [page, setPage] = useState(1);
  const [error, setError] = useState("");

  useEffect(() => {
    Promise.all([getResult(docId), getMarkdown(docId)]).then(([d, m]) => { setDoc(d); setMd(m); }).catch((e) => setError(e.message));
  }, [docId]);

  useEffect(() => {
    if (!doc) return;
    rememberDocument({
      id: docId, filename: doc.filename, status: doc.status, format: doc.format || "pdf",
      pages: doc.page_count, tables: doc.blocks.filter((b) => b.type === "table").length,
      confidence: doc.stats?.mean_confidence, ts: Date.now(),
    });
  }, [doc, docId]);

  const selected = useMemo(() => doc?.blocks.find((b) => b.id === selectedId) || null, [doc, selectedId]);
  if (error) return <div className="status error">Error: {error}</div>;
  if (!doc) return <div className="status busy"><span className="spinner" /> Loading results…</div>;
  const s = doc.stats || {};
  const timing = doc.timing && Object.keys(doc.timing).length ? doc.timing : null;
  const hard = doc.errors.filter((e) => e.severity === "error");

  const isUnits = doc.format === "docx" || doc.format === "pptx" || doc.format === "xlsx";
  const select = (id, pg) => { setSelectedId(id); if (pg) setPage(pg); };
  const tableBlocks = doc.blocks.filter((b) => b.type === "table");

  return (
    <div className="results">
      <section className="card doc-header">
        <div className="doc-header-top">
          <div className="doc-title">
            <span className="label">Document · {(doc.format || "pdf").toUpperCase()}</span>
            <h1>{doc.filename} <span className={`pill ${doc.status.toLowerCase()}`}>{doc.status}</span></h1>
          </div>
          <div className="doc-actions">
            <DownloadButtons docId={docId} />
            <button className="btn" onClick={onReset}>Parse another</button>
          </div>
        </div>
        <div className="stats">
          <span>File type: {(doc.format || "pdf").toUpperCase()}</span>
          <span>{isUnits ? `${doc.timing?.logical_units_processed ?? s.logical_units_processed ?? doc.blocks.length} logical elements` : `${doc.page_count} pages (${s.scanned_pages} scanned)`}</span>
          <span>{doc.blocks.length} blocks</span>
          <span>mean confidence {Math.round((s.mean_confidence || 0) * 100)}%</span>
          <span>{s.review_required} need review</span>
          <span>{hard.length} errors</span>
        </div>
        {hard.length > 0 && (
          <ul className="errors">{hard.map((e, i) => <li key={i}><b>{e.code}</b> {e.page ? `(p.${e.page}) ` : ""}{e.message}</li>)}</ul>
        )}
      </section>

      <div className="split">
        <section className="card viewer-card">
          {doc.format === "pdf" ? <DocumentViewer docId={docId} doc={doc} page={page} onPageChange={setPage} selected={selected} /> : <SourceViewer doc={doc} selected={selected} onPageChange={setPage} />}
          {selected && (
            <p className="small selection-info">
              Selected {selected.id} · {selected.type} · {doc.format === "pdf" ? `Page ${selected.page} · bbox [${(selected.bbox || []).join(", ")}]` : doc.format === "pptx" ? `Slide ${selected.provenance?.sources?.[0]?.slide_number ?? selected.page}${selected.bbox ? " · element region" : ""}` : doc.format === "xlsx" ? `${selected.provenance?.sources?.[0]?.worksheet || "Worksheet"} · ${selected.provenance?.sources?.[0]?.range || selected.provenance?.sources?.[0]?.cell || "source range"}` : `Paragraph ${selected.provenance?.sources?.[0]?.paragraph_index ?? "—"}`} · confidence {selected.confidence.toFixed(2)} ({selected.confidence_level}) · extractor {selected.extractor}
            </p>
          )}
        </section>

        <section className="card panel-card">
          <SearchPanel docId={docId} selectedId={selectedId} onSelect={select} />
          <div className="tabs" role="tablist">
            {TABS.map(([t, label]) => <button key={t} role="tab" aria-selected={tab === t} className={tab === t ? "on" : ""} onClick={() => setTab(t)}>{label}</button>)}
          </div>
          <div className="panel-body">
            {tab === "summary" && <SummaryPanel summary={doc.summary} filename={doc.filename} onSelect={select} />}
            {tab === "markdown" && <MarkdownViewer markdown={md} docId={docId} />}
            {tab === "json" && <OutputViewer output={doc} />}
            {tab === "blocks" && (
              <ul className="blocks">
                {doc.blocks.map((b) => (
                  <li key={b.id} className={`${b.id === selectedId ? "sel" : ""} ${b.status === "REVIEW_REQUIRED" ? "review" : ""}`}
                      onClick={() => { setSelectedId(b.id); setPage(b.page); }}>
                    <div className="block-head"><span className="label">{b.id} · {b.type} · {isUnits ? `logical unit ${b.page}` : `p.${b.page}`}</span> <ConfidenceBadge confidence={b.confidence} level={b.confidence_level} status={b.status} /></div>
                    <div className="preview">{preview(b)}</div>
                  </li>
                ))}
              </ul>
            )}
            {tab === "tables" && (
              tableBlocks.length ? (
                <ul className="blocks table-blocks">
                  {tableBlocks.map((b) => (
                    <li key={b.id} className={`${b.id === selectedId ? "sel" : ""} ${b.status === "REVIEW_REQUIRED" ? "review" : ""}`} onClick={() => { setSelectedId(b.id); setPage(b.page); }}>
                      <div className="block-head"><span className="label">{b.id} · {isUnits ? `logical unit ${b.page}` : `p.${b.page}`} · {preview(b)}</span> <ConfidenceBadge confidence={b.confidence} level={b.confidence_level} status={b.status} /></div>
                      <TableGrid block={b} />
                    </li>
                  ))}
                </ul>
              ) : <p className="small">No tables were extracted from this document.</p>
            )}
            {tab === "metadata" && (
              <div className="metadata">
                {timing ? (
                  <div className="perf" data-testid="performance-metrics">
                    {isUnits ? (
                      <><div><b>{timing.logical_units_processed ?? s.logical_units_processed ?? 0}</b><span>logical elements</span></div>
                      <div><b>{num(timing.processing_time_seconds, 1)}</b><span>seconds</span></div></>
                    ) : (
                      <><div><b>{timing.pages_processed ?? doc.page_count}</b><span>pages processed</span></div>
                      <div><b>{num(timing.processing_time_seconds, 1)}</b><span>seconds</span></div>
                      <div><b>{num(timing.seconds_per_page, 2)}</b><span>sec/page</span></div>
                      <div><b>{num(timing.pages_per_second, 2)}</b><span>pages/sec</span></div></>
                    )}
                  </div>
                ) : <p className="small">No timing information stored for this document.</p>}
                {timing?.stages && (
                  <p className="small">
                    {Object.entries(timing.stages).filter(([, v]) => v > 0).map(([k, v]) => `${STAGE_LABELS[k] || k} ${num(v, 2)}s`).join(" · ")}
                  </p>
                )}
              </div>
            )}
          </div>
        </section>
      </div>
    </div>
  );
}
