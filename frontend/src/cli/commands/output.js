// export <format>: exports the current result (the latest command's data, or the whole document).
import { downloadUrl } from "../../services/api";
import { L, blockPlain, link, linesToText, seg, tableMatrix, toCsv } from "../format";
import { CliError, COMMON_OPTIONS as O, ensureDoc, getMd, netCheck, resolveTarget } from "../session";

export function download(blob, filename) {
  const url = URL.createObjectURL(blob), a = document.createElement("a");
  a.href = url; a.download = filename; document.body.appendChild(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 2000);
}

const FORMATS = ["json", "md", "markdown", "txt", "csv"];
const stem = (n) => String(n || "result").replace(/\.[^.]+$/, "");
const blockRows = (blocks) => [["id", "type", "page", "confidence", "content"], ...blocks.map((b) => [b.id, b.type, b.page, b.confidence, blockPlain(b).replace(/\n/g, " ⏎ ")])];

function mdOfItems(items) {
  return items.map((b) => {
    if (b.type === "table") {
      const m = tableMatrix(b), rows = [...m.header, ...m.body], n = rows[0]?.length || 0;
      const row = (r) => `| ${Array.from({ length: n }, (_, i) => String(r[i] ?? "").replace(/\|/g, "\\|").replace(/\n/g, " ")).join(" | ")} |`;
      return `### Table ${b.id} (p.${b.page})\n\n${row(rows[0] || [])}\n|${"---|".repeat(n)}\n${rows.slice(1).map(row).join("\n")}`;
    }
    if (b.type === "equation" && b.content?.latex) return `$$\n${b.content.latex}\n$$`;
    return `**${b.type} ${b.id} (p.${b.page})**\n\n${blockPlain(b)}`;
  }).join("\n\n");
}

export const outputCommands = [
  {
    name: "export", summary: "Export the current result (json, md, txt, csv)", usage: "export <format> [options]", file: false,
    options: [O.file, { name: "full", type: "boolean", desc: "Export the whole document instead of the latest command's result" }, { name: "name", type: "string", desc: "Output file name (without extension)" }],
    args: FORMATS,
    examples: ["tables report.pdf  →  export csv", "export json --full", "export md --name report-final"],
    async run(ctx, args) {
      const fmt = (args.positional[0] || "").toLowerCase();
      if (!fmt) throw new CliError("Missing format.", `Usage: export <${FORMATS.join("|")}>`);
      if (!FORMATS.includes(fmt)) throw new CliError(`Unsupported format "${fmt}".`, `Choose one of: ${FORMATS.join(", ")}`);
      let last = ctx.session.last;
      if (args.opts.full || args.opts.file || !last) {
        const id = args.opts.file ? (await ensureDoc(ctx, resolveTarget(ctx, args.opts.file))).id : last?.docId || ctx.session.current || ctx.guiDocId;
        if (!id) throw new CliError("Nothing to export yet.", "Run `parse <file>` (or any extraction command) first.");
        const rec = await ensureDoc(ctx, { id, filename: ctx.session.cache.get(id)?.filename });
        last = { cmd: "document", docId: id, filename: rec.filename, whole: true, data: rec.doc };
      }
      const rec = ctx.session.cache.get(last.docId);
      const base = args.opts.name || `${stem(last.filename)}${last.whole ? "" : `.${last.cmd}`}`;
      const items = Array.isArray(last.data?.items) ? last.data.items : null;
      const isBlocks = items && items.length && items[0] && typeof items[0] === "object" && "type" in items[0] && "id" in items[0];
      let blob, file, note;
      if (fmt === "json") {
        if (last.whole && rec) { // full document: the backend's own file
          const r = await fetch(downloadUrl(last.docId, "json")).catch((e) => { netCheck(e); throw e; });
          if (!r.ok) throw new CliError("The backend has no stored JSON for this document.");
          blob = await r.blob(); file = `${base}.json`; note = "full document JSON";
        } else { blob = new Blob([JSON.stringify(last.data, null, 2)], { type: "application/json" }); file = `${base}.json`; note = `${last.cmd} result`; }
      } else if (fmt === "md" || fmt === "markdown") {
        if (last.whole && rec) { blob = new Blob([await getMd(rec)], { type: "text/markdown" }); note = "full document Markdown"; }
        else if (isBlocks) { blob = new Blob([mdOfItems(items)], { type: "text/markdown" }); note = `${last.cmd} result`; }
        else if (last.data?.markdown) { blob = new Blob([last.data.markdown], { type: "text/markdown" }); note = "Markdown"; }
        else if (last.data?.summary) { const s = last.data.summary; blob = new Blob([`# ${s.overview?.title || last.filename}\n\n${s.executive_summary}\n\n## Key points\n\n${(s.key_points || []).map((k) => `- ${k.text}`).join("\n")}\n`], { type: "text/markdown" }); note = "summary"; }
        else throw new CliError(`The latest result (${last.cmd}) can't be exported as Markdown.`, "Try `export json` or `export txt`.");
        file = `${base}.md`;
      } else if (fmt === "csv") {
        let rows;
        if (isBlocks && items.every((b) => b.type === "table")) {
          rows = items.flatMap((b, i) => { const m = tableMatrix(b); return [...(i ? [[]] : []), [`# ${b.id} (p.${b.page})`], ...m.header, ...m.body]; });
        } else if (isBlocks) rows = blockRows(items);
        else if (last.whole && rec) rows = blockRows(rec.doc.blocks);
        else if (last.data?.command === "search") rows = [["document_id", "block_id", "page", "type", "confidence", "snippet"], ...items.map((h) => [h.document_id, h.block_id, h.page, h.block_type, h.confidence, h.snippet])];
        else if (items?.length && items[0] && typeof items[0] === "object") { const keys = Object.keys(items[0]).filter((k) => typeof items[0][k] !== "object"); rows = [keys, ...items.map((r) => keys.map((k) => r[k]))]; }
        else throw new CliError(`The latest result (${last.cmd}) has no tabular form.`, "Run `tables`, `text`, `search` … first, or use `export json`.");
        blob = new Blob(["\uFEFF" + toCsv(rows)], { type: "text/csv" }); file = `${base}.csv`; note = `${rows.length} rows`;
      } else {
        const text = last.lines ? linesToText(last.lines) : isBlocks ? items.map(blockPlain).join("\n\n") : rec ? rec.doc.blocks.map(blockPlain).join("\n\n") : "";
        if (!text.trim()) throw new CliError("Nothing to export as text.");
        blob = new Blob([text], { type: "text/plain" }); file = `${base}.txt`; note = `${last.cmd} output`;
      }
      download(blob, file);
      ctx.print([L.ok(`Exported ${note} → ${file} (${(blob.size / 1024).toFixed(1)} KB)`), L.line(seg("  again: ", "dim"), link.run(`export ${fmt}${args.opts.full ? " --full" : ""}`, `export ${fmt}${args.opts.full ? " --full" : ""}`))]);
    },
  },
];
