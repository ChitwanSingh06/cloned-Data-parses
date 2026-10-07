import { useState } from "react";
import { searchDocument } from "../services/api";

const label = (t) => t.charAt(0).toUpperCase() + t.slice(1);

// Searches the saved canonical document on the backend (no re-parse). Clicking a hit selects the
// canonical block; the format-aware source viewer uses that block's existing provenance.
export default function SearchPanel({ docId, selectedId, onSelect }) {
  const [query, setQuery] = useState("");
  const [res, setRes] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const run = async (e) => {
    e.preventDefault();
    const q = query.trim();
    if (!q) { setRes(null); setError(""); return; }
    setBusy(true); setError("");
    try { setRes(await searchDocument(docId, q)); } catch (err) { setError(err.message); setRes(null); }
    setBusy(false);
  };
  const clear = () => { setQuery(""); setRes(null); setError(""); };

  return (
    <div className="search">
      <form onSubmit={run} className="search-form">
        <input type="search" value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Search document..." aria-label="Search document" />
        <button type="submit" disabled={busy || !query.trim()}>{busy ? "Searching…" : "Search"}</button>
        {(res || error) && <button type="button" onClick={clear}>Clear</button>}
      </form>
      {error && <p className="status error small">{error}</p>}
      {res && res.total_matches === 0 && <p className="small">{res.message || "No matches."}</p>}
      {res && res.total_matches > 0 && (
        <>
          <p className="small">{res.total_matches} matching block{res.total_matches === 1 ? "" : "s"}{res.truncated ? ` (showing first ${res.returned})` : ""}</p>
          <ul className="search-results">
            {res.results.map((h) => (
              <li key={h.block_id} className={h.block_id === selectedId ? "sel" : ""} onClick={() => onSelect(h.block_id, h.page)}
                  tabIndex={0} onKeyDown={(e) => { if (e.key === "Enter") onSelect(h.block_id, h.page); }}>
                <div><b>{h.matched_text}</b>{h.match_count > 1 ? ` (×${h.match_count})` : ""}</div>
                <div className="small">{h.provenance?.sources?.[0]?.source_type === "pptx" ? `Slide ${h.provenance.sources[0].slide_number ?? h.page}` : h.provenance?.sources?.[0]?.source_type === "xlsx" ? `${h.provenance.sources[0].worksheet || "Worksheet"} · ${h.provenance.sources[0].range || h.provenance.sources[0].cell || "source"}` : h.provenance?.sources?.[0]?.source_type === "docx" ? (h.provenance.sources[0].table_index != null ? `Table ${h.provenance.sources[0].table_index}` : `Paragraph ${h.provenance.sources[0].paragraph_index ?? "—"}`) : `Page ${h.page} · bbox`} · {label(h.block_type)} · Confidence: {h.confidence.toFixed(2)} · order #{h.reading_order} · {h.block_id}</div>
                <div className="preview">{h.snippet}</div>
              </li>
            ))}
          </ul>
        </>
      )}
    </div>
  );
}
