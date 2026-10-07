// Whole-document commands: parse, pdf, summary, markdown, json, search.
import { pageImageUrl, searchDocument } from "../../services/api";
import { L, clip, grid, levelCls, link, pct, plural, seg, where } from "../format";
import { CliError, COMMON_OPTIONS as O, ensureDoc, getMd, knownDocs, netCheck, resolveTarget, setLast, target } from "../session";
import { pagePredicate } from "../parseArgs";
import { download } from "./output";

const TYPES = ["heading", "paragraph", "list", "table", "figure", "chart", "equation", "caption", "header", "footer", "footnote", "reference"];

export function overviewLines(rec) {
  const d = rec.doc, s = d.stats || {}, t = d.timing || {};
  const counts = {};
  d.blocks.forEach((b) => { counts[b.type] = (counts[b.type] || 0) + 1; });
  const hard = (d.errors || []).filter((e) => e.severity === "error");
  const lines = [
    L.line(seg(d.status === "FAILED" ? "✗ " : d.status === "SUCCESS" ? "✓ " : "! ", d.status === "FAILED" ? "err" : d.status === "SUCCESS" ? "ok" : "warn"),
      seg(rec.filename, "head"), seg(` · ${(d.format || "pdf").toUpperCase()} · ${d.status}`, "dim")),
    L.line(seg("  id        ", "dim"), link.open(rec.id, rec.id)),
    L.text(`  pages     ${d.page_count}${s.scanned_pages != null ? ` (${s.scanned_pages} scanned)` : ""}`),
    L.text(`  blocks    ${d.blocks.length}${Object.keys(counts).length ? "  —  " + Object.entries(counts).map(([k, v]) => `${v} ${k}`).join(", ") : ""}`),
    L.line(seg("  quality   ", ""), seg(`mean confidence ${pct(s.mean_confidence)}`, s.mean_confidence >= 0.85 ? "ok" : s.mean_confidence >= 0.6 ? "warn" : "err"), seg(` · ${s.review_required ?? 0} need review`, "dim")),
  ];
  const secs = t.processing_time_seconds ?? d.processing_time;
  if (typeof secs === "number") lines.push(L.text(`  time      ${secs.toFixed(2)}s${t.seconds_per_page ? ` (${t.seconds_per_page.toFixed(2)} s/page)` : ""}`));
  hard.slice(0, 5).forEach((e) => lines.push(L.err(`${e.code}${e.page ? ` (p.${e.page})` : ""}: ${e.message}`)));
  (d.errors || []).filter((e) => e.severity !== "error").slice(0, 3).forEach((e) => lines.push(L.warn(`${e.code}: ${e.message}`)));
  return lines;
}

export const documentCommands = [
  {
    name: "parse", summary: "Parse a document (upload must exist; parses if not yet parsed)", usage: "parse [file] [options]", file: true,
    options: [O.file, O.force, O.open, O.json],
    examples: ["parse report.pdf", "parse report.pdf --force --open", "parse 3fa9c1d2e4b7"],
    async run(ctx, args) {
      const entry = resolveTarget(ctx, args.opts.file ?? args.positional[0]);
      const rec = await ensureDoc(ctx, entry, { force: !!args.opts.force });
      const lines = args.opts.json ? [L.pre(JSON.stringify({ document_id: rec.id, filename: rec.filename, status: rec.doc.status, stats: rec.doc.stats, timing: rec.doc.timing, errors: rec.doc.errors }, null, 2))] : overviewLines(rec);
      ctx.print(lines);
      if (!args.opts.json) {
        const n = (t) => rec.doc.blocks.filter((b) => b.type === t).length;
        ctx.print(L.line(seg("  next      ", "dim"), link.run("summary", "summary"), "  ", link.run(`tables (${n("table")})`, "tables"), "  ", link.run(`figures (${n("figure")})`, "figures"),
          "  ", link.run(`charts (${n("chart")})`, "charts"), "  ", link.run(`equations (${n("equation")})`, "equations"), "  ", link.run("text", "text")));
      }
      setLast(ctx, { cmd: "parse", docId: rec.id, filename: rec.filename, whole: true, data: rec.doc, lines });
      if (args.opts.open) ctx.openDoc(rec.id);
    },
  },
  {
    name: "pdf", summary: "Page-level processing report (digital vs OCR, text volume, blocks)", usage: "pdf [file] [options]", file: true,
    options: [O.file, O.page, O.force, O.open, O.json],
    examples: ["pdf report.pdf", "pdf report.pdf --page 1-5"],
    async run(ctx, args) {
      const { rec, doc, inPage } = await target(ctx, args);
      const pages = (doc.pages || []).filter((p) => inPage(p.page_number));
      if (!pages.length) throw new CliError("No matching pages in this document.", doc.format !== "pdf" ? `This is a ${(doc.format || "").toUpperCase()} file: it is split into logical units, not pages.` : undefined);
      const counts = {};
      doc.blocks.forEach((b) => { (counts[b.page] ||= {})[b.type] = (counts[b.page][b.type] || 0) + 1; });
      const rows = pages.map((p) => [String(p.page_number), `${Math.round(p.width)}×${Math.round(p.height)}`, p.source || "digital", String(p.text_chars ?? 0), String(p.blocks?.length ?? 0),
        Object.entries(counts[p.page_number] || {}).filter(([k]) => ["table", "figure", "chart", "equation"].includes(k)).map(([k, v]) => `${v} ${k}`).join(", ")]);
      if (args.opts.json) return void ctx.print(L.pre(JSON.stringify(pages, null, 2)));
      const lines = [L.head(`${rec.filename} · ${(doc.format || "pdf").toUpperCase()} · ${plural(doc.page_count, "page")} · ${doc.status}`),
        L.pre(grid([["Page", "Size (pt)", "Source", "Chars", "Blocks", "Special"], ...rows], { headerRows: 1 }).join("\n"))];
      const scanned = pages.filter((p) => p.source === "ocr" || p.is_scanned).length;
      lines.push(L.line(seg(`${scanned} scanned/OCR · ${pages.length - scanned} digital`, "dim"), doc.format === "pdf" ? seg("  ·  ", "dim") : "",
        doc.format === "pdf" ? link.url(`page ${pages[0].page_number} image`, pageImageUrl(rec.id, pages[0].page_number)) : ""));
      if (doc.format !== "pdf") lines.push(L.dim("Note: non-PDF sources are converted to logical units (slides, sheets, paragraphs)."));
      setLast(ctx, { cmd: "pdf", docId: rec.id, filename: rec.filename, data: { command: "pdf", document_id: rec.id, filename: rec.filename, count: pages.length, items: pages }, lines });
      ctx.print(lines);
      if (args.opts.open) ctx.openDoc(rec.id);
    },
  },
  {
    name: "summary", summary: "Show the document summary (extractive, from real blocks)", usage: "summary [file] [options]", file: true,
    options: [O.file, O.force, O.open, O.json, { name: "points", type: "number", desc: "Key points to show (default all)" }],
    examples: ["summary report.pdf", "summary --points 3"],
    async run(ctx, args) {
      const { rec, doc } = await target(ctx, args);
      const s = doc.summary;
      if (!s || !Object.keys(s).length) throw new CliError("This document has no stored summary.", "Re-parse with `parse --force`.");
      if (args.opts.json) return void ctx.print(L.pre(JSON.stringify(s, null, 2)));
      const lines = [L.head(s.overview?.title || rec.filename),
        L.dim(`${rec.filename} · ${(doc.format || "pdf").toUpperCase()} · ${plural(s.overview?.page_count ?? doc.page_count, s.overview?.unit_label || "page")} · ${s.overview?.source_kind || ""} · method ${s.method}`), L.blank(),
        L.text(s.executive_summary || "")];
      if (s.status === "uncertain") lines.push(L.warn("Summary is based on low-confidence content; verify against the source."));
      const kp = (s.key_points || []).slice(0, args.opts.points ?? Infinity);
      if (kp.length) { lines.push(L.blank(), L.head("Key points")); kp.forEach((k) => lines.push(L.line("  • ", seg(clip(k.text, 220), k.uncertain ? "warn" : ""), seg(` (${where(doc, { page: k.page, meta: {} })})`, "dim")))); }
      if (s.sections?.length) { lines.push(L.blank(), L.head("Sections")); s.sections.forEach((x) => lines.push(L.line("  " + "  ".repeat(Math.max(0, (x.level || 1) - 1)) + "§ ", seg(clip(x.text, 90)), seg(` p.${x.page}`, "dim")))); }
      const st = s.statistics || {};
      lines.push(L.blank(), L.dim(`${st.words ?? 0} words · ${st.tables ?? 0} tables · ${st.figures ?? 0} figures · ${st.charts ?? 0} charts · ${st.equations ?? 0} equations · ${st.review_required_blocks ?? 0} need review`));
      (s.warnings || []).forEach((w) => lines.push(L.warn(w)));
      setLast(ctx, { cmd: "summary", docId: rec.id, filename: rec.filename, data: { command: "summary", document_id: rec.id, filename: rec.filename, summary: s }, lines });
      ctx.print(lines);
      if (args.opts.open) ctx.openDoc(rec.id);
    },
  },
  {
    name: "markdown", aliases: ["md"], summary: "Show / save the Markdown rendering", usage: "markdown [file] [options]", file: true,
    options: [O.file, O.force, O.open, { name: "head", type: "number", desc: "Lines to preview (default 60)" }, O.all, { name: "save", short: "s", type: "boolean", desc: "Download the .md file" }],
    examples: ["markdown report.pdf", "markdown report.pdf --all", "markdown report.pdf --save"],
    async run(ctx, args) {
      const { rec, doc } = await target(ctx, args);
      const md = await getMd(rec);
      const rows = md.split("\n"), n = args.opts.all ? rows.length : args.opts.head ?? 60;
      const lines = [L.head(`Markdown · ${rec.filename} · ${rows.length} lines · ${md.length.toLocaleString()} chars`), L.pre(rows.slice(0, n).join("\n"))];
      if (rows.length > n) lines.push(L.line(seg(`… ${rows.length - n} more lines (`, "dim"), link.run("--all", "markdown --all"), seg(" or ", "dim"), link.run("--save", "markdown --save"), seg(")", "dim")));
      if (args.opts.save) { const name = `${doc.filename.replace(/\.[^.]+$/, "")}.md`; download(new Blob([md], { type: "text/markdown" }), name); lines.push(L.ok(`Saved ${name}`)); }
      setLast(ctx, { cmd: "markdown", docId: rec.id, filename: rec.filename, whole: true, md, data: { command: "markdown", document_id: rec.id, filename: rec.filename, markdown: md }, lines });
      ctx.print(lines);
      if (args.opts.open) ctx.openDoc(rec.id);
    },
  },
  {
    name: "json", summary: "Show / save the canonical JSON output", usage: "json [file] [options]", file: true,
    options: [O.file, O.force, O.open, { name: "path", type: "string", desc: "Drill into a value, e.g. stats or blocks.0.content" }, { name: "head", type: "number", desc: "Lines to preview (default 60)" }, O.all, { name: "save", short: "s", type: "boolean", desc: "Download the .json file" }],
    examples: ["json report.pdf --path stats", "json report.pdf --path blocks.0", "json report.pdf --save"],
    async run(ctx, args) {
      const { rec, doc } = await target(ctx, args);
      let v = doc;
      if (args.opts.path) {
        for (const k of args.opts.path.split(".").filter(Boolean)) {
          if (v == null || typeof v !== "object" || !(k in v)) throw new CliError(`Path "${args.opts.path}" not found at "${k}".`, `Top-level keys: ${Object.keys(doc).join(", ")}`);
          v = v[k];
        }
      }
      const text = JSON.stringify(v, null, 2), rows = text.split("\n"), n = args.opts.all ? rows.length : args.opts.head ?? 60;
      const lines = [L.head(`JSON · ${rec.filename}${args.opts.path ? ` · ${args.opts.path}` : ""} · ${rows.length} lines`), L.pre(rows.slice(0, n).join("\n"), "code")];
      if (rows.length > n) lines.push(L.line(seg(`… ${rows.length - n} more lines (`, "dim"), link.run("--all", `json${args.opts.path ? ` --path ${args.opts.path}` : ""} --all`), seg(" or ", "dim"), link.run("--save", "json --save"), seg(")", "dim")));
      if (args.opts.save) { download(new Blob([JSON.stringify(doc, null, 2)], { type: "application/json" }), `${doc.filename.replace(/\.[^.]+$/, "")}.json`); lines.push(L.ok("Saved full JSON")); }
      setLast(ctx, { cmd: "json", docId: rec.id, filename: rec.filename, whole: !args.opts.path, data: v, lines });
      ctx.print(lines);
      if (args.opts.open) ctx.openDoc(rec.id);
    },
  },
  {
    name: "search", aliases: ["find"], summary: "Search extracted content (uses the backend search API)", usage: "search <query> [options]", file: false,
    options: [O.file, O.limit, O.page, O.json, O.open, { name: "type", short: "t", type: "string", values: TYPES, desc: "Only this block type" },
      { name: "all-docs", type: "boolean", desc: "Search every known parsed document" }],
    examples: ["search revenue", "search \"net income\" --file report.pdf --type table", "search budget --all-docs"],
    async run(ctx, args) {
      const query = args.positional.join(" ").trim();
      if (!query) throw new CliError("Missing search query.", "Usage: search <query> [--file f] [--type table] [--page 2] [--limit 20]");
      const inPage = pagePredicate(args.opts.page);
      if (!inPage) throw new CliError(`Invalid --page value "${args.opts.page}".`);
      const targets = args.opts["all-docs"] ? knownDocs(ctx) : [resolveTarget(ctx, args.opts.file)];
      if (!targets.length) throw new CliError("No documents to search.", "Parse a document first.");
      const limit = args.opts.limit ?? 20, lines = [], hitsOut = [];
      let total = 0, searched = 0;
      for (const t of targets) {
        if (ctx.cancelled()) break;
        if (!args.opts["all-docs"]) await ensureDoc(ctx, t); // parse first when needed so single-file search always works
        let res;
        try { res = await searchDocument(t.id, query, 1000); } catch (e) { netCheck(e); if (args.opts["all-docs"]) continue; throw new CliError(`Search failed: ${e.message}`); }
        searched++;
        let hits = res.results.filter((h) => inPage(h.page) && (!args.opts.type || h.block_type === args.opts.type));
        total += hits.length;
        if (!hits.length) continue;
        if (args.opts["all-docs"]) lines.push(L.blank(), L.head(t.filename || t.id));
        for (const h of hits.slice(0, limit)) {
          hitsOut.push({ document_id: t.id, ...h });
          const i = h.snippet.toLowerCase().indexOf(h.matched_text.toLowerCase());
          lines.push(L.line(link.open(`${h.block_id}`, t.id), seg(` p.${h.page} · ${h.block_type} · `, "dim"), seg(pct(h.confidence), levelCls(h.confidence_level)), h.match_count > 1 ? seg(` · ${h.match_count} matches`, "dim") : ""),
            i < 0 ? L.text(`  ${h.snippet}`) : L.line("  ", h.snippet.slice(0, i), seg(h.snippet.slice(i, i + h.matched_text.length), "hit"), h.snippet.slice(i + h.matched_text.length)));
        }
        if (hits.length > limit) lines.push(L.dim(`… ${hits.length - limit} more in this document (--limit N)`));
      }
      const name = args.opts["all-docs"] ? `${searched} documents` : targets[0].filename || targets[0].id;
      if (!total) {
        const l = [L.warn(`No matches for “${query}” in ${name}.`)];
        setLast(ctx, { cmd: "search", docId: targets[0].id, filename: name, data: { command: "search", query, count: 0, items: [] }, lines: l });
        return void ctx.print(l);
      }
      const all = [L.head(`${plural(total, "matching block")} for “${query}” in ${name}`), ...lines];
      setLast(ctx, { cmd: "search", docId: targets[0].id, filename: name, data: { command: "search", query, count: total, items: hitsOut }, lines: all });
      if (args.opts.json) ctx.print(L.pre(JSON.stringify(hitsOut, null, 2))); else ctx.print(all);
      if (args.opts.open && !args.opts["all-docs"]) ctx.openDoc(targets[0].id);
    },
  },
];
