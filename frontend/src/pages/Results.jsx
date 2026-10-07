import { useEffect, useMemo, useState } from "react";
import ConfidenceBadge from "../components/ConfidenceBadge";
import DocumentViewer from "../components/DocumentViewer";
import DownloadButtons from "../components/DownloadButtons";
import MarkdownViewer from "../components/MarkdownViewer";
import OutputViewer from "../components/OutputViewer";
import { getMarkdown, getResult } from "../services/api";

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
  const [tab, setTab] = useState("blocks");
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
  const hard = doc.errors.filter((e) => e.severity === "error");

  return (
    <div>
      <section className="card">
        <h2>{doc.filename} <span className={`pill ${doc.status.toLowerCase()}`}>{doc.status}</span></h2>
        <div className="stats">
          <span>{doc.page_count} pages ({s.scanned_pages} scanned)</span>
          <span>{doc.blocks.length} blocks</span>
          <span>{doc.processing_time}s ({s.seconds_per_page}s/page)</span>
          <span>mean confidence {Math.round((s.mean_confidence || 0) * 100)}%</span>
          <span>{s.review_required} need review</span>
          <span>{hard.length} errors</span>
        </div>
        <DownloadButtons docId={docId} />
        <button onClick={onReset}>Parse another</button>
        {hard.length > 0 && (
          <ul className="errors">{hard.map((e, i) => <li key={i}><b>{e.code}</b> {e.page ? `(p.${e.page}) ` : ""}{e.message}</li>)}</ul>
        )}
      </section>

      <div className="split">
        <section className="card">
          <div className="tabs">
            {["blocks", "markdown", "json"].map((t) => <button key={t} className={tab === t ? "on" : ""} onClick={() => setTab(t)}>{t}</button>)}
          </div>
          {tab === "markdown" && <MarkdownViewer markdown={md} docId={docId} />}
          {tab === "json" && <OutputViewer output={doc} />}
          {tab === "blocks" && (
            <ul className="blocks">
              {doc.blocks.map((b) => (
                <li key={b.id} className={`${b.id === selectedId ? "sel" : ""} ${b.status === "REVIEW_REQUIRED" ? "review" : ""}`}
                    onClick={() => { setSelectedId(b.id); setPage(b.page); }}>
                  <div><b>{b.id}</b> · {b.type} · p.{b.page} <ConfidenceBadge confidence={b.confidence} level={b.confidence_level} status={b.status} /></div>
                  <div className="preview">{preview(b)}</div>
                </li>
              ))}
            </ul>
          )}
        </section>
        <section className="card">
          <DocumentViewer docId={docId} doc={doc} page={page} onPageChange={setPage} selected={selected} />
          {selected && <p className="small">Selected {selected.id} · extractor {selected.extractor} · bbox [{selected.bbox.join(", ")}]</p>}
        </section>
      </div>
    </div>
  );
}
