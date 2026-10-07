// Output model for the terminal. A line is { parts:[{text,cls,run|open|href}] } | { pre, cls } | { img, caption, href }.
export const seg = (text, cls = "", extra = {}) => ({ text: String(text), cls, ...extra });
const toParts = (p) => p.flat().map((x) => (typeof x === "string" ? seg(x) : x));

export const L = {
  line: (...parts) => ({ parts: toParts(parts) }),
  text: (s, cls = "") => ({ parts: [seg(s, cls)] }),
  ok: (s) => L.text(`✓ ${s}`, "ok"),
  warn: (s) => L.text(`! ${s}`, "warn"),
  err: (s) => L.text(`✗ ${s}`, "err"),
  info: (s) => L.text(s, "info"),
  dim: (s) => L.text(s, "dim"),
  head: (s) => L.text(s, "head"),
  blank: () => L.text(""),
  pre: (s, cls = "") => ({ pre: String(s), cls }),
  img: (src, caption, href) => ({ img: src, caption, href }),
};
export const link = {
  run: (text, command) => seg(text, "link", { run: command }),
  open: (text, docId) => seg(text, "link", { open: docId }),
  url: (text, href) => seg(text, "link", { href }),
};

export const pct = (v) => (typeof v === "number" ? `${Math.round(v * 100)}%` : "n/a");
export const levelCls = (lvl) => (lvl === "HIGH" ? "ok" : lvl === "MEDIUM" ? "warn" : "err");
export const plural = (n, w, pl = w + "s") => `${n} ${n === 1 ? w : pl}`;
export const clip = (s, n) => { s = String(s ?? "").replace(/\s+/g, " ").trim(); return s.length > n ? s.slice(0, n - 1) + "…" : s; };

export function grid(rows, { maxCol = 30, headerRows = 0 } = {}) {
  const cells = rows.map((r) => r.map((c) => clip(c, maxCol)));
  const n = Math.max(0, ...cells.map((r) => r.length));
  const w = Array.from({ length: n }, (_, j) => Math.max(1, ...cells.map((r) => (r[j] ?? "").length)));
  const fmt = (r) => w.map((x, j) => (r[j] ?? "").padEnd(x)).join(" │ ").trimEnd();
  const out = [];
  cells.forEach((r, i) => { out.push(fmt(r)); if (i === headerRows - 1) out.push(w.map((x) => "─".repeat(x)).join("─┼─")); });
  return out;
}

export function toCsv(rows) {
  const q = (v) => { const s = String(v ?? ""); return /[",\n\r]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s; };
  return rows.map((r) => r.map(q).join(",")).join("\n");
}

export function tableMatrix(b) {
  const c = b.content || {};
  if ((c.headers && c.headers.length) || (c.rows && c.rows.length)) return { header: c.headers || [], body: c.rows || [] };
  const byPos = new Map((c.cells || []).map((x) => [`${x.row},${x.col}`, x.text]));
  const all = Array.from({ length: c.n_rows || 0 }, (_, r) => Array.from({ length: c.n_cols || 0 }, (_, k) => byPos.get(`${r},${k}`) ?? ""));
  const hr = c.header_rows || 0;
  return { header: all.slice(0, hr), body: all.slice(hr) };
}

// Where a block lives, per source format (mirrors the Results page wording).
export function where(doc, b) {
  const src = b.provenance?.sources?.[0] || b.meta || {};
  if (doc.format === "pptx") return `slide ${src.slide_number ?? b.page}`;
  if (doc.format === "xlsx") return `${src.worksheet || "sheet"}${src.cell ? `!${src.cell}` : ""}`;
  if (doc.format === "docx") return `unit ${b.page}`;
  return `p.${b.page}`;
}

export function blockHead(doc, b, extra = "") {
  const rev = b.status === "REVIEW_REQUIRED";
  return L.line(link.open(b.id, doc.document_id), seg(` · ${where(doc, b)}${extra ? " · " + extra : ""} · `, "dim"),
    seg(`${pct(b.confidence)} ${b.confidence_level}`, levelCls(b.confidence_level)), rev ? seg("  needs review", "warn") : "");
}

// Plain-text rendering of any block (used by export / text output).
export function blockPlain(b) {
  const c = b.content;
  switch (b.type) {
    case "list": return (c?.items || []).map((x) => `• ${x}`).join("\n");
    case "table": { const m = tableMatrix(b); return grid([...m.header, ...m.body], { maxCol: 60, headerRows: m.header.length }).join("\n"); }
    case "equation": return c?.latex ? `$$ ${c.latex} $$` : String(c?.raw_text ?? "");
    case "chart": return `${c?.chart_type || "chart"}${c?.title ? ": " + c.title : ""}`;
    case "figure": return b.meta?.caption ? `[figure] ${b.meta.caption}` : "[figure]";
    default: return typeof c === "string" ? c : JSON.stringify(c);
  }
}

export const linesToText = (lines) => lines.map((l) => (l.pre != null ? l.pre : l.img ? `[image ${l.img}]` : (l.parts || []).map((p) => p.text).join(""))).join("\n");
