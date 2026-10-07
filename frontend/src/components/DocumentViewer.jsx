import BoundingBox from "./BoundingBox";
import { pageImageUrl } from "../services/api";

// Source viewer: rendered PDF page + highlight of the selected block (all its provenance sources on this page).
export default function DocumentViewer({ docId, doc, page, onPageChange, selected }) {
  if (!doc) return <div className="viewer">Document preview will appear here.</div>;
  const info = doc.pages.find((p) => p.page_number === page) || doc.pages[0];
  const sources = selected
    ? (selected.provenance?.sources?.length ? selected.provenance.sources : [{ page: selected.page, bbox: selected.bbox }])
        .filter((s) => s.page === info.page_number)
    : [];
  return (
    <div className="viewer">
      <div className="viewer-nav">
        <button disabled={page <= 1} onClick={() => onPageChange(page - 1)}>‹ Prev</button>
        <span>Page {info.page_number} / {doc.page_count} {info.is_scanned ? "(scanned → OCR)" : ""}</span>
        <button disabled={page >= doc.page_count} onClick={() => onPageChange(page + 1)}>Next ›</button>
      </div>
      <div className="page-wrap">
        <img src={pageImageUrl(docId, info.page_number)} alt={`Page ${info.page_number}`} />
        {sources.map((s, i) => (
          <BoundingBox key={i} bbox={s.bbox} pageWidth={info.width} pageHeight={info.height} label={selected.id} />
        ))}
      </div>
    </div>
  );
}
