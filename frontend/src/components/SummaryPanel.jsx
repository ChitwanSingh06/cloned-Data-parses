// Renders doc.summary (built by the backend from the extracted blocks; nothing is generated in the browser).
// Clicking an item selects its block, so the existing viewer jumps to the page and highlights the bbox.
const Item = ({ text, uncertain, meta, onClick }) => (
  <li className={onClick ? "clickable" : ""} onClick={onClick}>
    {text}
    {uncertain && <span className="pill failed uncertain-pill"> low confidence</span>}
    {meta && <span className="small"> {meta}</span>}
  </li>
);

export default function SummaryPanel({ summary, filename, onSelect }) {
  if (!summary || !summary.overview) {
    return <p className="small">No summary stored for this document. Parse it again to generate one.</p>;
  }
  const { overview: o, statistics: st } = summary;
  const go = (x) => (x.block_id ? () => onSelect(x.block_id, x.page) : undefined);
  const stat = [
    ["Pages", st.pages], ["Text blocks", st.text_blocks], ["Tables", st.tables], ["Figures", st.figures],
    ["Charts", st.charts], ["Equations", st.equations], ["Words", st.words], ["Low-confidence blocks", st.low_confidence_blocks],
  ];
  return (
    <div className="summary">
      {summary.status === "uncertain" && <p className="status error small">All extracted text is low confidence. Treat this summary as unverified.</p>}
      {(summary.warnings || []).filter(() => summary.status !== "uncertain").map((w, i) => <p key={i} className="small warn">{w}</p>)}

      <h3>Document Overview</h3>
      <table className="overview"><tbody>
        <tr><th>Title</th><td>{o.title ? <>{o.title.text}{o.title.uncertain && <span className="pill failed uncertain-pill"> low confidence</span>}</> : <i>not detected ({filename})</i>}</td></tr>
        <tr><th>Pages</th><td>{o.page_count}{o.source_kind ? ` (${o.source_kind})` : ""}</td></tr>
        <tr><th>Language</th><td>{o.language || <i>not detected</i>}</td></tr>
        <tr><th>Document type</th><td>{o.document_type || <i>not detected</i>}</td></tr>
      </tbody></table>

      <h3>Executive Summary</h3>
      <p>{summary.executive_summary}</p>
      {summary.method && <p className="small">Extractive summary built locally from the extracted content ({summary.method}); sentences are copied from the document, not generated.</p>}

      <h3>Key Points</h3>
      {summary.key_points?.length ? (
        <ul>{summary.key_points.map((k, i) => <Item key={i} text={k.text} uncertain={k.uncertain} meta={`· p.${k.page} · ${k.block_id}`} onClick={go(k)} />)}</ul>
      ) : <p className="small">No key points could be extracted.</p>}

      <h3>Major Sections</h3>
      {summary.sections?.length ? (
        <ul>{summary.sections.map((s, i) => <Item key={i} text={`${"\u00a0\u00a0".repeat(Math.max(0, s.level - (summary.sections[0].level || 1)))}${s.text}`} uncertain={s.uncertain} meta={`· p.${s.page}`} onClick={go(s)} />)}</ul>
      ) : <p className="small">No headings detected.</p>}

      <h3>Statistics</h3>
      <div className="perf">{stat.map(([k, v]) => <div key={k}><b>{v ?? 0}</b><span>{k}</span></div>)}</div>
    </div>
  );
}
