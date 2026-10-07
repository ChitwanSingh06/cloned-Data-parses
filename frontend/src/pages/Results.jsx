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

const STAGE_LABELS = { ingestion: "Ingestion", ocr: "OCR", layout_analysis: "Layout analysis", table_extraction: "Table extraction", assembly: "Assembly", validation: "Validation", output_generation: "Output generation" };
const num = (v, digits) => (typeof v === "number" && Number.isFinite(v) ? v.toFixed(digits) : "n/a");

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

  const selected = useMemo(() => doc?.blocks.find((b) => b.id === selectedId) || null, [doc, selectedId]);
  if (error) return <div className="status error">Error: {error}</div>;
  if (!doc) return <div className="status busy"><span className="spinner" /> Loading results…</div>;
  const s = doc.stats || {};
  const timing = doc.timing && Object.keys(doc.timing).length ? doc.timing : null;
  const hard = doc.errors.filter((e) => e.severity === "error");

  return (
    <div>
      <section className="card">
        <h2>{doc.filename} <span className={`pill ${doc.status.toLowerCase()}`}>{doc.status}</span></h2>
        <div className="stats">
          <span>File type: {(doc.format || "pdf").toUpperCase()}</span>
          <span>{doc.format === "docx" || doc.format === "pptx" || doc.format === "xlsx" ? `${doc.timing?.logical_units_processed ?? s.logical_units_processed ?? doc.blocks.length} logical elements` : `${doc.page_count} pages (${s.scanned_pages} scanned)`}</span>
          <span>{doc.blocks.length} blocks</span>
          <span>mean confidence {Math.round((s.mean_confidence || 0) * 100)}%</span>
          <span>{s.review_required} need review</span>
          <span>{hard.length} errors</span>
        </div>
        {timing && (
          <div className="perf" data-testid="performance-metrics">
            {doc.format === "docx" || doc.format === "pptx" || doc.format === "xlsx" ? (
              <><div><b>{timing.logical_units_processed ?? s.logical_units_processed ?? 0}</b><span>logical elements</span></div>
              <div><b>{num(timing.processing_time_seconds, 1)}</b><span>seconds</span></div></>
            ) : (
              <><div><b>{timing.pages_processed ?? doc.page_count}</b><span>pages processed</span></div>
              <div><b>{num(timing.processing_time_seconds, 1)}</b><span>seconds</span></div>
              <div><b>{num(timing.seconds_per_page, 2)}</b><span>sec/page</span></div>
              <div><b>{num(timing.pages_per_second, 2)}</b><span>pages/sec</span></div></>
            )}
          </div>
        )}
        {timing?.stages && (
          <p className="small">
            {Object.entries(timing.stages).filter(([, v]) => v > 0).map(([k, v]) => `${STAGE_LABELS[k] || k} ${num(v, 2)}s`).join(" · ")}
          </p>
        )}
        <DownloadButtons docId={docId} />
        <button onClick={onReset}>Parse another</button>
        {hard.length > 0 && (
          <ul className="errors">{hard.map((e, i) => <li key={i}><b>{e.code}</b> {e.page ? `(p.${e.page}) ` : ""}{e.message}</li>)}</ul>
        )}
      </section>

      <div className="split">
        <section className="card">
          <SearchPanel docId={docId} selectedId={selectedId} onSelect={(id, pg) => { setSelectedId(id); if (pg) setPage(pg); }} />
          <div className="tabs">
            {["summary", "blocks", "markdown", "json"].map((t) => <button key={t} className={tab === t ? "on" : ""} onClick={() => setTab(t)}>{t}</button>)}
          </div>
          {tab === "summary" && <SummaryPanel summary={doc.summary} filename={doc.filename} onSelect={(id, pg) => { setSelectedId(id); if (pg) setPage(pg); }} />}
          {tab === "markdown" && <MarkdownViewer markdown={md} docId={docId} />}
          {tab === "json" && <OutputViewer output={doc} />}
          {tab === "blocks" && (
            <ul className="blocks">
              {doc.blocks.map((b) => (
                <li key={b.id} className={`${b.id === selectedId ? "sel" : ""} ${b.status === "REVIEW_REQUIRED" ? "review" : ""}`}
                    onClick={() => { setSelectedId(b.id); setPage(b.page); }}>
                  <div><b>{b.id}</b> · {b.type} · {doc.format === "docx" || doc.format === "pptx" || doc.format === "xlsx" ? `logical unit ${b.page}` : `p.${b.page}`} <ConfidenceBadge confidence={b.confidence} level={b.confidence_level} status={b.status} /></div>
                  <div className="preview">{preview(b)}</div>
                </li>
              ))}
            </ul>
          )}
        </section>
        <section className="card">
          {doc.format === "pdf" ? <DocumentViewer docId={docId} doc={doc} page={page} onPageChange={setPage} selected={selected} /> : <SourceViewer doc={doc} selected={selected} onPageChange={setPage} />}
          {selected && (
            <p className="small">
              Selected {selected.id} · {selected.type} · {doc.format === "pdf" ? `Page ${selected.page} · bbox [${(selected.bbox || []).join(", ")}]` : doc.format === "pptx" ? `Slide ${selected.provenance?.sources?.[0]?.slide_number ?? selected.page}${selected.bbox ? " · element region" : ""}` : doc.format === "xlsx" ? `${selected.provenance?.sources?.[0]?.worksheet || "Worksheet"} · ${selected.provenance?.sources?.[0]?.range || selected.provenance?.sources?.[0]?.cell || "source range"}` : `Paragraph ${selected.provenance?.sources?.[0]?.paragraph_index ?? "—"}`} · confidence {selected.confidence.toFixed(2)} ({selected.confidence_level}) · extractor {selected.extractor}
            </p>
          )}
        </section>
      </div>
    </div>
  );
}
