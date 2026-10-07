import { useState } from "react";
import BoundingBox from "./BoundingBox";
import { pageImageUrl } from "../services/api";

const ZOOMS = [50, 75, 100, 125, 150, 200];

// Source viewer: rendered PDF page + highlight of the selected block (all its provenance sources on this page).
// Zoom and the B-Box toggle are view-only state; the highlight logic itself is unchanged.
export default function DocumentViewer({ docId, doc, page, onPageChange, selected }) {
  const [zoom, setZoom] = useState(100);
  const [showBoxes, setShowBoxes] = useState(true);
  if (!doc) return <div className="viewer">Document preview will appear here.</div>;
  const info = doc.pages.find((p) => p.page_number === page) || doc.pages[0];
  const sources = selected
    ? (selected.provenance?.sources?.length ? selected.provenance.sources : [{ page: selected.page, bbox: selected.bbox }])
        .filter((s) => s.page === info.page_number)
    : [];
  const zi = ZOOMS.indexOf(zoom);
  return (
    <div className="viewer">
      <div className="viewer-nav toolbar">
        <div className="tool-group">
          <button className="icon-btn" disabled={page <= 1} onClick={() => onPageChange(page - 1)} aria-label="Previous page">‹</button>
          <span className="tool-label">Page {info.page_number} / {doc.page_count} {info.is_scanned ? <span className="pill neutral">scanned → OCR</span> : ""}</span>
          <button className="icon-btn" disabled={page >= doc.page_count} onClick={() => onPageChange(page + 1)} aria-label="Next page">›</button>
        </div>
        <div className="tool-group">
          <button className="icon-btn" disabled={zi <= 0} onClick={() => setZoom(ZOOMS[zi - 1])} aria-label="Zoom out">−</button>
          <span className="tool-label">{zoom}%</span>
          <button className="icon-btn" disabled={zi >= ZOOMS.length - 1} onClick={() => setZoom(ZOOMS[zi + 1])} aria-label="Zoom in">+</button>
          <button className={`chip-toggle ${showBoxes ? "on" : ""}`} aria-pressed={showBoxes} onClick={() => setShowBoxes(!showBoxes)}>B-Box</button>
        </div>
      </div>
      <div className="page-scroll">
        <div className="page-wrap" style={{ width: `${zoom}%` }}>
          <img src={pageImageUrl(docId, info.page_number)} alt={`Page ${info.page_number}`} />
          {showBoxes && sources.map((s, i) => (
            <BoundingBox key={i} bbox={s.bbox} pageWidth={info.width} pageHeight={info.height} label={selected.id} />
          ))}
        </div>
      </div>
    </div>
  );
}
