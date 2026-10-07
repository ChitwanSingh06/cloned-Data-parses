// Block-level extraction commands. Each one reads the real parsed document from the backend and filters its blocks.
import { figureUrl } from "../../services/api";
import { L, blockHead, blockPlain, clip, grid, link, plural, seg, tableMatrix, toCsv, where } from "../format";
import { COMMON_OPTIONS as O, setLast, target } from "../session";

const TEXT_TYPES = new Set(["heading", "paragraph", "list", "caption", "footnote", "reference"]);
const OCR_RE = /ocr|tesseract|paddle|htr|trocr|handwrit/i;

export const isOcrBlock = (doc, b) => {
  const pg = doc.pages?.find((p) => p.page_number === b.page);
  return OCR_RE.test(b.extractor || "") || OCR_RE.test(b.provenance?.extractor || "") || b.meta?.kind === "handwritten" ||
    (pg?.source === "ocr" && (TEXT_TYPES.has(b.type) || b.type === "header" || b.type === "footer"));
};

function select(doc, inPage, args, pred) {
  const min = args.opts["min-conf"];
  return doc.blocks.filter((b) => pred(b) && inPage(b.page) && (min == null || b.confidence >= min));
}

// Common tail: store the latest result, honour --json / --open, print a footer with clickable follow-ups.
function finish(ctx, args, { cmd, rec, items, lines, footer }) {
  const doc = rec.doc;
  setLast(ctx, { cmd, docId: rec.id, filename: doc.filename, data: { command: cmd, document_id: rec.id, filename: doc.filename, count: items.length, items }, lines });
  if (args.opts.json) { ctx.print(L.pre(JSON.stringify(items, null, 2))); }
  else ctx.print(lines);
  if (footer) ctx.print(footer);
  if (args.opts.open) { ctx.openDoc(rec.id); }
}

function empty(ctx, args, rec, cmd, noun, hint) {
  const lines = [L.warn(`No ${noun} found in ${rec.filename}${args.opts.page ? ` (pages ${args.opts.page})` : ""}.`)];
  if (hint) lines.push(L.dim(hint));
  const errs = (rec.doc.errors || []).filter((e) => e.severity === "error");
  if (errs.length) lines.push(L.dim(`The parser reported ${plural(errs.length, "error")}: ${errs[0].code} ${errs[0].message}`));
  setLast(ctx, { cmd, docId: rec.id, filename: rec.filename, data: { command: cmd, document_id: rec.id, filename: rec.filename, count: 0, items: [] }, lines });
  ctx.print(lines);
}

const cap = (items, args, dflt) => (args.opts.all ? items : items.slice(0, args.opts.limit ?? dflt));
const more = (total, shown, cmd) => (total > shown ? L.line(seg(`… ${total - shown} more (use `, "dim"), link.run("--all", `${cmd} --all`), seg(" or --limit N)", "dim")) : null);
const base = (extra = []) => [O.file, O.page, O.json, O.force, O.open, ...extra];

export const extractCommands = [
  {
    name: "tables", summary: "Extract tables (cells, headers, rows)", usage: "tables [file] [options]", file: true,
    options: [...base([O.limit, O.all, O.minConf]), { name: "index", short: "i", type: "number", desc: "Show only the Nth table" },
      { name: "rows", short: "r", type: "number", desc: "Rows to show per table (default 12)" }, { name: "csv", type: "boolean", desc: "Print tables as CSV" }],
    examples: ["tables report.pdf", "tables --page 3 --csv", "tables report.pdf --index 2 --rows 50"],
    async run(ctx, args) {
      const { rec, doc, inPage } = await target(ctx, args);
      let all = select(doc, inPage, args, (b) => b.type === "table");
      if (args.opts.index) all = all.slice(args.opts.index - 1, args.opts.index);
      if (!all.length) return empty(ctx, args, rec, "tables", "tables", "Tables are detected from ruled lines and aligned text; try `figures` or `charts` if the content is graphical.");
      const items = cap(all, args, 10), rows = args.opts.all ? Infinity : args.opts.rows ?? 12, lines = [];
      lines.push(L.head(`${plural(all.length, "table")} in ${rec.filename}`));
      items.forEach((b, i) => {
        const m = tableMatrix(b), c = b.content || {};
        lines.push(L.blank(), blockHead(doc, b, `table ${args.opts.index || i + 1} · ${c.n_rows}×${c.n_cols}${c.page_span?.length > 1 ? ` · pages ${c.page_span.join("–")}` : ""}`));
        if (args.opts.csv) { lines.push(L.pre(toCsv([...m.header, ...m.body]))); return; }
        const shown = m.body.slice(0, rows);
        lines.push(L.pre(grid([...m.header, ...shown], { headerRows: m.header.length }).join("\n")));
        if (m.body.length > shown.length) lines.push(L.dim(`… ${m.body.length - shown.length} more rows (--rows N)`));
        if (b.meta?.review_reason) lines.push(L.warn(b.meta.review_reason));
      });
      finish(ctx, args, { cmd: "tables", rec, items, lines, footer: more(all.length, items.length, "tables") || L.dim("Export these with `export csv`.") });
    },
  },
  {
    name: "charts", summary: "Detect charts and extract their data series", usage: "charts [file] [options]", file: true,
    options: [...base([O.limit, O.all, O.minConf]), { name: "points", type: "number", desc: "Data points to show per series (default 12)" }],
    examples: ["charts report.pdf", "charts --page 4 --points 40"],
    async run(ctx, args) {
      const { rec, doc, inPage } = await target(ctx, args);
      const all = select(doc, inPage, args, (b) => b.type === "chart");
      if (!all.length) return empty(ctx, args, rec, "charts", "charts", "Charts are recognised from vector drawings; raster chart images appear under `figures`.");
      const items = cap(all, args, 8), lines = [L.head(`${plural(all.length, "chart")} in ${rec.filename}`)];
      for (const b of items) {
        const c = b.content || {};
        lines.push(L.blank(), blockHead(doc, b, `${c.chart_type || "chart"}${c.title ? ` “${clip(c.title, 50)}”` : ""}`));
        const series = c.series || [];
        if (!c.data_extracted || !series.length) { lines.push(L.warn(b.meta?.review_reason || "Chart detected, but values could not be extracted.")); continue; }
        const unit = c.y_axis?.unit ? ` (${c.y_axis.unit})` : "";
        for (const s of series) {
          const pts = s.points || [], max = args.opts.all ? Infinity : args.opts.points ?? 12;
          const rows = pts.slice(0, max).map((p) => [String(p.category ?? p.x ?? (p.bin_start != null ? `${p.bin_start}–${p.bin_end}` : "?")), String(p.value ?? "")]);
          lines.push(L.dim(`${s.name || "series"} · ${plural(pts.length, "point")}${unit}`), L.pre(grid([["Category", "Value"], ...rows], { headerRows: 1 }).join("\n")));
          if (pts.length > max) lines.push(L.dim(`… ${pts.length - max} more points (--points N)`));
        }
      }
      finish(ctx, args, { cmd: "charts", rec, items, lines, footer: more(all.length, items.length, "charts") });
    },
  },
  {
    name: "equations", summary: "Extract equations (LaTeX where recognised)", usage: "equations [file] [options]", file: true,
    options: [...base([O.limit, O.all, O.minConf]), { name: "raw", type: "boolean", desc: "Also show the raw text behind each equation" }],
    examples: ["equations paper.pdf", "equations --page 2 --raw"],
    async run(ctx, args) {
      const { rec, doc, inPage } = await target(ctx, args);
      const all = select(doc, inPage, args, (b) => b.type === "equation");
      if (!all.length) return empty(ctx, args, rec, "equations", "equations");
      const items = cap(all, args, 25), lines = [L.head(`${plural(all.length, "equation")} in ${rec.filename}`)];
      let unrec = 0;
      for (const b of items) {
        const c = b.content || {};
        lines.push(blockHead(doc, b, c.recognizer || ""));
        if (c.latex) lines.push(L.pre(`  ${c.latex}`, "code")); else { unrec++; lines.push(L.warn(`Not converted to LaTeX: ${clip(c.raw_text, 120)}`)); }
        if (args.opts.raw && c.latex && c.raw_text) lines.push(L.dim(`  raw: ${clip(c.raw_text, 120)}`));
      }
      if (unrec) lines.push(L.blank(), L.warn(`${plural(unrec, "equation")} could not be converted to LaTeX; the raw text is kept.`));
      finish(ctx, args, { cmd: "equations", rec, items, lines, footer: more(all.length, items.length, "equations") });
    },
  },
  {
    name: "figures", summary: "Extract figures / embedded images", usage: "figures [file] [options]", file: true,
    options: [...base([O.limit, O.all, O.minConf]), { name: "no-thumbs", type: "boolean", desc: "Do not render inline thumbnails" }],
    examples: ["figures report.pdf", "figures --page 5 --no-thumbs"],
    async run(ctx, args) {
      const { rec, doc, inPage } = await target(ctx, args);
      const all = select(doc, inPage, args, (b) => b.type === "figure");
      if (!all.length) return empty(ctx, args, rec, "figures", "figures", "Vector charts are listed by `charts`.");
      const items = cap(all, args, 12), lines = [L.head(`${plural(all.length, "figure")} in ${rec.filename}`)];
      for (const b of items) {
        const name = b.meta?.image_path ? String(b.meta.image_path).split(/[\\/]/).pop() : null;
        const url = name ? figureUrl(rec.id, name) : null;
        lines.push(L.blank(), blockHead(doc, b, b.meta?.image_width_px ? `${b.meta.image_width_px}×${b.meta.image_height_px}px` : ""));
        if (b.meta?.caption) lines.push(L.text(`  ${b.meta.caption}`));
        if (b.meta?.review_reason) lines.push(L.warn(b.meta.review_reason));
        if (url) { lines.push(L.line(seg("  file: ", "dim"), link.url(name, url))); if (!args.opts["no-thumbs"]) lines.push(L.img(url, name, url)); }
        else lines.push(L.warn("No image file was saved for this figure."));
      }
      finish(ctx, args, { cmd: "figures", rec, items, lines, footer: more(all.length, items.length, "figures") });
    },
  },
  {
    name: "text", summary: "Extract the text content in reading order", usage: "text [file] [options]", file: true,
    options: [...base([O.limit, O.all, O.minConf]), { name: "type", short: "t", type: "string", values: ["heading", "paragraph", "list", "caption", "footnote", "reference", "header", "footer"], desc: "Only this block type" }],
    examples: ["text report.pdf", "text --page 1-2 --type heading", "text report.pdf --all"],
    async run(ctx, args) {
      const { rec, doc, inPage } = await target(ctx, args);
      const t = args.opts.type;
      const all = select(doc, inPage, args, (b) => (t ? b.type === t : TEXT_TYPES.has(b.type)));
      if (!all.length) return empty(ctx, args, rec, "text", "text blocks");
      const items = cap(all, args, 30), lines = [L.head(`${plural(all.length, "text block")} in ${rec.filename}`)];
      for (const b of items) {
        const low = b.confidence_level === "LOW" || b.status === "REVIEW_REQUIRED";
        lines.push(L.line(link.open(`${where(doc, b)}`, rec.id), seg(` ${b.type === "heading" ? "#".repeat(b.level || 1) : b.type} `, "dim"), seg(blockPlain(b), b.type === "heading" ? "head" : low ? "warn" : "")));
      }
      finish(ctx, args, { cmd: "text", rec, items, lines, footer: more(all.length, items.length, "text") });
    },
  },
  {
    name: "ocr", summary: "Show text recovered by OCR / handwriting recognition", usage: "ocr [file] [options]", file: true,
    options: [...base([O.limit, O.all, O.minConf])],
    examples: ["ocr scan.pdf", "ocr scan.pdf --min-conf 0.8", "ocr photo.png --force"],
    async run(ctx, args) {
      const { rec, doc, inPage } = await target(ctx, args);
      const ocrPages = (doc.pages || []).filter((p) => p.source === "ocr" || p.is_scanned);
      const all = select(doc, inPage, args, (b) => isOcrBlock(doc, b) && b.type !== "figure");
      if (!all.length) {
        ctx.print(L.info(`${rec.filename}: no OCR was needed — ${plural(doc.page_count, "page")} had a digital text layer.`));
        return empty(ctx, args, rec, "ocr", "OCR text", "OCR runs automatically on scanned pages and images. Use --force to re-run the parser.");
      }
      const items = cap(all, args, 30), low = all.filter((b) => b.confidence_level === "LOW" || b.status === "REVIEW_REQUIRED").length;
      const lines = [L.head(`OCR · ${plural(all.length, "block")} on ${plural(ocrPages.length || new Set(all.map((b) => b.page)).size, "page")} of ${doc.page_count}`)];
      for (const b of items) lines.push(blockHead(doc, b, b.meta?.kind || b.extractor || ""), L.text(`  ${clip(blockPlain(b), 400)}`));
      if (low) lines.push(L.blank(), L.warn(`${low === 1 ? "1 block is" : `${low} blocks are`} low confidence or flagged for review — verify against the source.`));
      const errs = (doc.errors || []).filter((e) => /OCR/i.test(e.code));
      errs.slice(0, 3).forEach((e) => lines.push(L.warn(`${e.code}: ${e.message}`)));
      finish(ctx, args, { cmd: "ocr", rec, items, lines, footer: more(all.length, items.length, "ocr") });
    },
  },
];
