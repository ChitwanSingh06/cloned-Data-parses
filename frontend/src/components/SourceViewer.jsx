import { useEffect, useMemo, useRef } from "react";
import { figureUrl } from "../services/api";

const esc = (value) => String(value ?? "");

function sourceRecords(block) {
  return block?.provenance?.sources?.length
    ? block.provenance.sources
    : [{ page: block?.page, bbox: block?.bbox }];
}

function firstSource(block, format) {
  const sources = sourceRecords(block);
  return sources.find((s) => s?.source_type === format) || sources[0] || {};
}

function formatLabel(block, format) {
  const s = firstSource(block, format);
  if (format === "pptx") return `Slide ${s.slide_number ?? block.page}${s.shape_name ? ` · ${s.shape_name}` : " · Element"}`;
  if (format === "xlsx") return `${s.worksheet || "Worksheet"}${s.range ? ` · ${s.range}` : s.cell ? ` · ${s.cell}` : ""}`;
  if (format === "docx") {
    if (s.table_index != null) return `Table ${s.table_index}${s.row != null ? ` · row ${s.row}, column ${s.column}` : ""}`;
    if (s.image_index != null) return `Image ${s.image_index}`;
    return `Paragraph ${s.paragraph_index ?? "—"}`;
  }
  return `Page ${s.page ?? block.page}`;
}

function textContent(block) {
  if (block?.type === "list") return (block.content?.items || []).join("\n");
  if (block?.type === "table") return "";
  if (typeof block?.content === "string") return block.content;
  return block?.content?.raw_text || "";
}

function PptxViewer({ doc, selected, onPageChange }) {
  const page = selected?.page || 1;
  const info = doc.pages.find((p) => p.page_number === page) || doc.pages[0];
  const slideBlocks = doc.blocks.filter((b) => b.page === info.page_number && b.bbox);
  const groups = useMemo(() => {
    const map = new Map();
    for (const block of slideBlocks) {
      const shapeIndex = block.meta?.shape_index ?? block.provenance?.sources?.[0]?.shape_index ?? block.id;
      if (!map.has(shapeIndex)) map.set(shapeIndex, []);
      map.get(shapeIndex).push(block);
    }
    return [...map.values()];
  }, [doc.blocks, info.page_number]);

  const goSlide = (delta) => {
    const next = Math.min(doc.page_count, Math.max(1, page + delta));
    const first = doc.blocks.find((b) => b.page === next);
    if (first) onPageChange?.(next);
  };

  return (
    <div className="source-viewer">
      <div className="source-toolbar slide-toolbar">
        <button type="button" onClick={() => goSlide(-1)} disabled={page <= 1}>‹</button>
        <b>Slide {info.page_number}</b> / {doc.page_count}
        <button type="button" onClick={() => goSlide(1)} disabled={page >= doc.page_count}>›</button>
      </div>
      <div className="slide-stage" style={{ aspectRatio: `${info.width || 16} / ${info.height || 9}` }}>
        {groups.map((group) => {
          const representative = group[0];
          const [x0, y0, x1, y1] = representative.bbox;
          const selectedInShape = group.some((b) => b.id === selected?.id);
          const style = {
            left: `${x0 / info.width * 100}%`,
            top: `${y0 / info.height * 100}%`,
            width: `${(x1 - x0) / info.width * 100}%`,
            height: `${(y1 - y0) / info.height * 100}%`,
          };
          const table = group.find((b) => b.type === "table");
          const figure = group.find((b) => b.type === "figure");
          if (table) {
            const cells = table.content?.cells || [];
            const rows = table.content?.n_rows || 0;
            const cols = table.content?.n_cols || 0;
            const byPos = new Map(cells.map((c) => [`${c.row},${c.col}`, c]));
            return <div key={table.id} className={`slide-shape slide-table ${selectedInShape ? "selected" : ""}`} style={style}>
              <table><tbody>{Array.from({ length: rows }, (_, r) => <tr key={r}>{Array.from({ length: cols }, (_, c) => <td key={c}>{esc(byPos.get(`${r},${c}`)?.text || "")}</td>)}</tr>)}</tbody></table>
            </div>;
          }
          if (figure) {
            const imagePath = figure.meta?.image_path;
            return <div key={figure.id} className={`slide-shape slide-figure ${selectedInShape ? "selected" : ""}`} style={style}>
              {imagePath ? <img src={figureUrl(doc.document_id, imagePath.split(/[\\/]/).pop())} alt="PPTX source element" /> : <span>Image</span>}
            </div>;
          }
          return <div key={representative.id} className={`slide-shape ${selectedInShape ? "selected" : ""}`} style={style}>
            {group.map((b) => {
              const text = textContent(b);
              const fontSize = b.meta?.font_size_pt ? `${Math.max(7, Math.min(40, b.meta.font_size_pt))}pt` : undefined;
              const weight = (b.meta?.bold_ratio || 0) >= 0.5 ? 700 : 400;
              const styleForText = { fontSize, fontWeight: weight, fontStyle: (b.meta?.italic_ratio || 0) >= 0.5 ? "italic" : "normal" };
              if (b.type === "list") return <div key={b.id} style={styleForText}>{b.content.items.map((item, i) => <div key={i}>• {item}</div>)}</div>;
              const Tag = b.type === "heading" ? "div" : "div";
              return <Tag key={b.id} style={styleForText}>{text}</Tag>;
            })}
          </div>;
        })}
      </div>
      {selected && <p className="small">{formatLabel(selected, "pptx")}{selected.bbox ? " · exact element region" : " · slide navigation only"}</p>}
    </div>
  );
}

function XlsxViewer({ doc, selected }) {
  const selectedSource = firstSource(selected, "xlsx");
  const sheet = selectedSource.worksheet || doc.pages[selected?.page ? selected.page - 1 : 0]?.page_number;
  const sheetIndex = selected?.page || 1;
  const blocks = doc.blocks.filter((b) => b.page === sheetIndex && b.type === "table");
  const active = blocks[0];
  const cells = active?.content?.cells || [];
  const nRows = active?.content?.n_rows || 0;
  const nCols = active?.content?.n_cols || 0;
  const wanted = selectedSource.range || selectedSource.cell || "";
  const rangeMatch = wanted.match(/^([A-Z]+)(\d+):([A-Z]+)(\d+)$/i);
  const startRow = rangeMatch ? Number(rangeMatch[2]) : 1;
  const startCol = rangeMatch ? columnNumber(rangeMatch[1]) : 1;
  const selectedCell = wanted.match(/^([A-Z]+)(\d+)$/i);
  const targetRow = selectedCell ? Number(selectedCell[2]) : null;
  const targetCol = selectedCell ? columnNumber(selectedCell[1]) : null;

  const byPos = new Map(cells.map((c) => [`${c.row},${c.col}`, c]));
  return (
    <div className="source-viewer">
      <div className="source-toolbar"><b>{sheet}</b>{wanted ? ` · ${wanted}` : ""}</div>
      {active ? (
        <div className="sheet-scroll">
          <table className="source-sheet"><tbody>
            {Array.from({ length: nRows }, (_, r) => <tr key={r}>
              {Array.from({ length: nCols }, (_, c) => {
                const cell = byPos.get(`${r},${c}`) || { text: "" };
                const absRow = startRow + r;
                const absCol = startCol + c;
                const selectedRange = rangeMatch ? absRow >= Number(rangeMatch[2]) && absRow <= Number(rangeMatch[4]) && absCol >= columnNumber(rangeMatch[1]) && absCol <= columnNumber(rangeMatch[3]) : false;
                const isSelected = (targetRow === absRow && targetCol === absCol) || selectedRange;
                return <td key={c} className={isSelected ? "source-cell-selected" : ""} data-cell={`${columnName(absCol)}${absRow}`}>{esc(cell.text)}</td>;
              })}
            </tr>)}
          </tbody></table>
        </div>
      ) : <p className="small">No populated worksheet cells.</p>}
      {selected && <p className="small">{formatLabel(selected, "xlsx")} · source selection</p>}
    </div>
  );
}

function columnNumber(name) {
  let n = 0;
  for (const ch of String(name).toUpperCase()) n = n * 26 + ch.charCodeAt(0) - 64;
  return n;
}
function columnName(n) {
  let s = "";
  while (n > 0) { const r = (n - 1) % 26; s = String.fromCharCode(65 + r) + s; n = Math.floor((n - 1) / 26); }
  return s;
}

function DocxViewer({ doc, selected }) {
  const ref = useRef(null);
  const selectedSource = firstSource(selected, "docx");
  useEffect(() => {
    if (ref.current) ref.current.scrollIntoView({ behavior: "smooth", block: "center" });
  }, [selected?.id]);
  return (
    <div className="source-viewer docx-source">
      <div className="source-toolbar"><b>DOCX source</b>{selected ? ` · ${formatLabel(selected, "docx")}` : ""}</div>
      <div className="docx-paper">
        {doc.blocks.map((b) => {
          const s = firstSource(b, "docx");
          const anchor = s.table_index != null ? `docx-table-${s.table_index}` : s.image_index != null ? `docx-image-${s.image_index}` : `docx-paragraph-${s.paragraph_index ?? b.id}`;
          const active = b.id === selected?.id;
          const cls = `docx-block ${active ? "selected" : ""}`;
          if (b.type === "table") {
            const cells = b.content?.cells || [];
            const rows = b.content?.n_rows || 0;
            const cols = b.content?.n_cols || 0;
            const byPos = new Map(cells.map((c) => [`${c.row},${c.col}`, c]));
            return <div key={b.id} id={anchor} ref={active ? ref : null} className={cls}>
              <table className="source-sheet"><tbody>{Array.from({ length: rows }, (_, r) => <tr key={r}>{Array.from({ length: cols }, (_, c) => <td key={c} className={s.row === r && s.column === c ? "source-cell-selected" : ""}>{byPos.get(`${r},${c}`)?.text || ""}</td>)}</tr>)}</tbody></table>
              <div className="small">Table {s.table_index ?? "—"}</div>
            </div>;
          }
          if (b.type === "figure") return <div key={b.id} id={anchor} ref={active ? ref : null} className={cls}><div className="source-image-placeholder">Image {s.image_index ?? "—"}</div><div className="small">Image {s.image_index ?? "—"}</div></div>;
          const text = textContent(b);
          const Tag = b.type === "heading" ? `h${Math.min(6, Math.max(1, b.level || 1))}` : "p";
          return <div key={b.id} id={anchor} ref={active ? ref : null} className={cls}><Tag>{text}</Tag></div>;
        })}
      </div>
      {selected && <p className="small">{formatLabel(selected, "docx")} · structural source navigation{selected.bbox ? " · exact region" : ""}</p>}
    </div>
  );
}

export default function SourceViewer({ doc, selected, onPageChange }) {
  if (!doc) return <div className="viewer">Source preview will appear here.</div>;
  if (doc.format === "pdf") return null;
  if (doc.format === "pptx") return <PptxViewer doc={doc} selected={selected} onPageChange={onPageChange} />;
  if (doc.format === "xlsx") return <XlsxViewer doc={doc} selected={selected} />;
  if (doc.format === "docx") return <DocxViewer doc={doc} selected={selected} />;
  return <div className="viewer"><p>Source location unavailable.</p></div>;
}
