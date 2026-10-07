import { timeAgo } from "../lib/recent";

const pct = (v) => (typeof v === "number" ? `${Math.round(v * 100)}%` : "—");

// Aggregates only values that were read from real parsed results.
export function StatCards({ docs }) {
  const n = docs.length;
  const pages = docs.reduce((a, d) => a + (d.pages || 0), 0);
  const tables = docs.reduce((a, d) => a + (d.tables || 0), 0);
  const withConf = docs.filter((d) => typeof d.confidence === "number");
  const conf = withConf.length ? withConf.reduce((a, d) => a + d.confidence, 0) / withConf.length : null;
  const items = [["Documents", n], ["Pages", pages], ["Tables", tables], ["Avg. confidence", pct(conf)]];
  return (
    <div className="stat-grid">
      {items.map(([k, v]) => (
        <div className="stat-card" key={k}><span className="label">{k}</span><b>{v}</b></div>
      ))}
    </div>
  );
}

export function RecentList({ docs, onOpen, onRemove, emptyText, timeline }) {
  if (!docs.length) return <div className="card empty">{emptyText}</div>;
  return (
    <ul className={`doc-list ${timeline ? "timeline" : ""}`}>
      {docs.map((d) => (
        <li key={d.id} className="doc-row">
          <button className="doc-open" onClick={() => onOpen(d.id)}>
            <span className="doc-ico">{(d.format || "pdf").toUpperCase()}</span>
            <span className="doc-main">
              <b>{d.filename}</b>
              <span className="label">{d.pages ?? "—"} pages · {d.tables ?? 0} tables · {pct(d.confidence)} confidence · {timeAgo(d.ts)}</span>
            </span>
            {d.status && <span className={`pill ${String(d.status).toLowerCase()}`}>{d.status}</span>}
          </button>
          {onRemove && <button className="link-btn" onClick={() => onRemove(d.id)} aria-label={`Remove ${d.filename} from list`}>Remove</button>}
        </li>
      ))}
    </ul>
  );
}
