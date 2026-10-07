// Terminal / session commands: help, clear, status, result, history, docs, use, open, attach.
import { API_BASE, getStatus } from "../../services/api";
import { L, link, plural, seg } from "../format";
import { CliError, COMMON_OPTIONS as O, ensureDoc, knownDocs, netCheck, resolveTarget } from "../session";
import { overviewLines } from "./document";

const ago = (ts) => { const s = Math.max(0, (Date.now() - ts) / 1000); return s < 5 ? "just now" : s < 60 ? `${Math.floor(s)}s ago` : s < 3600 ? `${Math.floor(s / 60)}m ago` : `${Math.floor(s / 3600)}h ago`; };

export function commandHelp(cmd) {
  const lines = [L.head(cmd.name), L.text(`  ${cmd.summary}`), L.blank(), L.line(seg("Usage  ", "dim"), seg(cmd.usage, "code"))];
  if (cmd.aliases?.length) lines.push(L.line(seg("Alias  ", "dim"), cmd.aliases.join(", ")));
  const opts = [...(cmd.options || []), { name: "help", short: "h", type: "boolean", desc: "Show this help" }];
  lines.push(L.blank(), L.head("Options"));
  for (const o of opts) {
    const flag = `${o.short ? `-${o.short}, ` : "    "}--${o.name}${o.type === "boolean" ? "" : o.values ? ` <${o.values.slice(0, 4).join("|")}${o.values.length > 4 ? "|…" : ""}>` : ` <${o.type}>`}`;
    lines.push(L.line(seg(flag.padEnd(34), "code"), o.desc));
  }
  if (cmd.examples?.length) { lines.push(L.blank(), L.head("Examples")); cmd.examples.forEach((e) => lines.push(L.line("  ", link.run(e, e.includes("→") ? e.split("→").pop().trim() : e)))); }
  return lines;
}

export const coreCommands = (registry) => [
  {
    name: "help", aliases: ["?"], summary: "Show all commands, or help for one command", usage: "help [command]", file: false, args: () => registry.names(),
    examples: ["help", "help tables"],
    async run(ctx, args) {
      const name = args.positional[0];
      if (name) {
        const c = registry.get(name);
        if (!c) throw new CliError(`No such command "${name}".`, "Type `help` for the full list.");
        return void ctx.print(commandHelp(c));
      }
      const groups = [["Parse & extract", ["parse", "ocr", "tables", "charts", "equations", "figures", "text", "pdf"]],
        ["Search & output", ["search", "summary", "markdown", "json", "result", "export"]], ["Session", ["status", "docs", "use", "open", "attach", "history", "clear", "help"]]];
      const lines = [L.head("ParseAnything terminal"), L.dim("Every command runs against the live backend. <file> = document id or filename; omit it to use the current document.")];
      for (const [title, names] of groups) {
        lines.push(L.blank(), L.head(title));
        for (const n of names) { const c = registry.get(n); if (c) lines.push(L.line("  ", link.run(c.name.padEnd(10), `help ${c.name}`), seg(c.usage.replace(/^\S+\s?/, "").padEnd(24), "dim"), c.summary)); }
      }
      const extra = registry.all().filter((c) => !groups.some(([, ns]) => ns.includes(c.name)));
      if (extra.length) { lines.push(L.blank(), L.head("More")); extra.forEach((c) => lines.push(L.line("  ", link.run(c.name.padEnd(10), `help ${c.name}`), seg(c.usage.replace(/^\S+\s?/, "").padEnd(24), "dim"), c.summary))); }
      lines.push(L.blank(), L.dim("Tab completes commands, options and filenames · ↑/↓ history · Ctrl+L clear · Ctrl+C cancel · Ctrl+` toggle terminal · `<cmd> --help` for options"));
      ctx.print(lines);
    },
  },
  { name: "clear", aliases: ["cls"], summary: "Clear the terminal", usage: "clear", file: false, async run(ctx) { ctx.clear(); } },
  {
    name: "status", summary: "Backend / parser status (and a document's job status)", usage: "status [file] [options]", file: true,
    options: [O.file, { name: "all-docs", type: "boolean", desc: "Show job status for every known document" }],
    examples: ["status", "status report.pdf", "status --all-docs"],
    async run(ctx, args) {
      const root = API_BASE.replace(/\/api\/?$/, ""), t0 = performance.now(), lines = [L.head("Backend")];
      let up = false;
      try { const r = await fetch(`${root}/health`); up = r.ok; lines.push(r.ok ? L.ok(`${root} is healthy (${Math.round(performance.now() - t0)} ms)`) : L.err(`${root}/health returned HTTP ${r.status}`)); }
      catch (e) { lines.push(L.err(`Backend unreachable at ${root}`), L.dim("Start it with `uvicorn app.main:app --reload` in backend/, and check VITE_API_BASE / CORS_ORIGINS.")); }
      lines.push(L.dim(`API base ${API_BASE}`));
      if (up) {
        const list = args.opts["all-docs"] ? knownDocs(ctx) : (args.positional[0] || args.opts.file || ctx.session.current || ctx.guiDocId) ? [resolveTarget(ctx, args.opts.file ?? args.positional[0])] : [];
        if (!list.length) lines.push(L.blank(), L.dim("No current document. `attach` a file or `docs` to list known ones."));
        for (const d of list) {
          lines.push(L.blank(), L.head(d.filename || d.id));
          try {
            const st = await getStatus(d.id), tm = st.timing || {};
            lines.push(L.line(seg("  job       ", "dim"), seg(st.status, st.status === "SUCCESS" ? "ok" : st.status === "FAILED" ? "err" : "warn"), seg(` · id `, "dim"), link.open(d.id, d.id)));
            if (st.page_count != null) lines.push(L.text(`  pages     ${st.page_count}`));
            if (st.processing_time != null) lines.push(L.text(`  time      ${Number(st.processing_time).toFixed(2)}s`));
            const stages = Object.entries(tm.stages || {}).filter(([, v]) => v > 0).map(([k, v]) => `${k} ${Number(v).toFixed(2)}s`);
            if (stages.length) lines.push(L.dim(`  stages    ${stages.join(" · ")}`));
            (st.errors || []).forEach((e) => lines.push(L.err(`${e.code}: ${e.message}`)));
            const rec = ctx.session.cache.get(d.id);
            if (rec) {
              const codes = new Set((rec.doc.errors || []).map((e) => e.code));
              const ocrErr = [...codes].find((c) => /OCR/i.test(c)), htrErr = [...codes].find((c) => /HTR|HANDWRIT/i.test(c));
              lines.push(ocrErr ? L.warn(`  OCR: reported ${ocrErr} during the last parse`) : L.text(`  OCR       no OCR errors in the last parse`));
              if (htrErr) lines.push(L.warn(`  Handwriting: reported ${htrErr}`));
            }
          } catch (e) { netCheck(e); lines.push(L.warn(`  ${e.message} (not uploaded/parsed on this backend?)`)); }
        }
      }
      lines.push(L.blank(), L.dim(`Session: ${plural(ctx.session.cache.size, "document")} loaded · ${plural(knownDocs(ctx).length, "known document")}`));
      ctx.print(lines);
    },
  },
  {
    name: "result", summary: "Display the latest result again (or --json for its data)", usage: "result [options]", file: false,
    options: [O.json],
    examples: ["result", "result --json"],
    async run(ctx, args) {
      const last = ctx.session.last;
      if (!last) {
        const id = ctx.session.current || ctx.guiDocId, rec = id && ctx.session.cache.get(id);
        if (rec) return void ctx.print([L.dim("No command result yet — showing the current document:"), ...overviewLines(rec)]);
        throw new CliError("No result yet.", "Run `parse <file>` or an extraction command such as `tables` first.");
      }
      if (args.opts.json) return void ctx.print(L.pre(JSON.stringify(last.data, null, 2)));
      ctx.print([L.dim(`Latest result: ${last.cmd} · ${last.filename} · ${ago(last.ts)}`), ...(last.lines || [])]);
    },
  },
  {
    name: "docs", aliases: ["ls"], summary: "List known documents (click one to select it)", usage: "docs", file: false,
    async run(ctx) {
      const list = knownDocs(ctx);
      if (!list.length) return void ctx.print(L.warn("No documents yet. Use `attach` to add one, or upload on the dashboard."));
      const cur = ctx.session.current || ctx.guiDocId;
      ctx.print([L.head(plural(list.length, "document")), ...list.map((d) => L.line(d.id === cur ? "▸ " : "  ", link.run(d.filename || d.id, `use ${d.id}`), seg(`  ${d.id}`, "dim"), ctx.session.cache.has(d.id) ? seg("  parsed", "ok") : "", d.ts ? seg(`  ${ago(d.ts)}`, "dim") : ""))]);
    },
  },
  {
    name: "use", summary: "Select the current document", usage: "use <file>", file: true,
    async run(ctx, args) {
      const e = resolveTarget(ctx, args.positional[0] || undefined);
      ctx.session.current = e.id;
      ctx.print(L.ok(`Current document: ${e.filename || e.id} (${e.id})`));
    },
  },
  {
    name: "open", summary: "Open a document in the GUI results view", usage: "open [file]", file: true,
    async run(ctx, args) {
      const e = resolveTarget(ctx, args.positional[0]);
      if (!ctx.session.cache.has(e.id)) { await ensureDoc(ctx, e); }
      ctx.openDoc(e.id);
      ctx.print(L.ok(`Opened ${ctx.session.cache.get(e.id)?.filename || e.id} in the results view`));
    },
  },
  {
    name: "attach", aliases: ["upload"], summary: "Upload a file from your computer (or drag one onto the terminal)", usage: "attach", file: false,
    async run(ctx) { ctx.print(L.dim("Choose a file in the dialog… (PDF, DOCX, PPTX, XLSX or image)")); ctx.attachFile(); },
  },
  {
    name: "history", summary: "Show command history (-c to clear)", usage: "history [options]", file: false,
    options: [{ name: "clear", short: "c", type: "boolean", desc: "Clear the history" }],
    async run(ctx, args) {
      if (args.opts.clear) { ctx.history.clear(); return void ctx.print(L.ok("History cleared")); }
      const h = ctx.history.list();
      if (!h.length) return void ctx.print(L.dim("History is empty."));
      ctx.print(h.slice(-50).map((c, i) => L.line(seg(String(h.length - Math.min(50, h.length) + i + 1).padStart(4) + "  ", "dim"), link.run(c, c))));
    },
  },
];
