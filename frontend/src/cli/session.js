// Document resolution + backend access for the terminal. Everything goes through the existing API client.
import { API_BASE, getMarkdown, getResult, getStatus, startParse } from "../services/api";
import { loadRecent, rememberDocument } from "../lib/recent";
import { pagePredicate } from "./parseArgs";

export class CliError extends Error {
  constructor(message, hint, extra = {}) { super(message); this.hint = hint; Object.assign(this, extra); }
}
export const ID_RE = /^[0-9a-f]{12}$/;
const DONE = ["SUCCESS", "PARTIAL_SUCCESS", "FAILED"];
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

export const newSession = () => ({ current: null, docs: new Map(), cache: new Map(), last: null });

export function netCheck(e) {
  if (e instanceof TypeError) {
    throw new CliError(`Backend unreachable at ${API_BASE}`, "Start it with `uvicorn app.main:app --reload` (backend/) and check VITE_API_BASE / CORS_ORIGINS. Run `status` to re-check.");
  }
}

export function knownDocs(ctx) {
  const m = new Map();
  for (const d of loadRecent()) m.set(d.id, { id: d.id, filename: d.filename || d.id, ts: d.ts || 0 });
  for (const d of ctx.session.docs.values()) m.set(d.id, { ...m.get(d.id), ...d });
  for (const c of ctx.session.cache.values()) m.set(c.id, { ...m.get(c.id), id: c.id, filename: c.filename, ts: m.get(c.id)?.ts || 0 });
  return [...m.values()].sort((a, b) => (b.ts || 0) - (a.ts || 0));
}

const entryFor = (ctx, id) => knownDocs(ctx).find((d) => d.id === id) || { id, filename: id };

export function resolveTarget(ctx, arg) {
  if (arg == null || arg === "" || arg === ".") {
    const id = ctx.session.current || ctx.guiDocId;
    if (!id) throw new CliError("No document selected.", "Use `attach` to add a file (or drop one onto this terminal), or pass a document id/filename. `docs` lists known documents.");
    return entryFor(ctx, id);
  }
  if (ID_RE.test(arg)) return entryFor(ctx, arg);
  const docs = knownDocs(ctx), q = arg.toLowerCase();
  let hits = docs.filter((d) => d.filename?.toLowerCase() === q);
  if (!hits.length) hits = docs.filter((d) => d.filename?.toLowerCase().includes(q));
  const names = new Set(hits.map((h) => h.filename));
  if (hits.length && names.size === 1) return hits[0]; // same name uploaded twice -> most recent
  if (names.size > 1) throw new CliError(`"${arg}" matches several documents: ${[...names].slice(0, 5).join(", ")}`, "Use a longer name or the 12-character id from `docs`.");
  // needsFile: the terminal reacts by opening the file picker and re-running the command once the file is uploaded.
  throw new CliError(`"${arg}" has not been uploaded in this browser yet.`, "A browser terminal can't read your disk, so choose the file in the dialog (or drag it onto this panel). `docs` lists known documents.", { needsFile: arg });
}

export async function ensureDoc(ctx, entry, { force = false } = {}) {
  const id = entry.id, name = entry.filename || id;
  if (!force && ctx.session.cache.has(id)) { ctx.session.current = id; return ctx.session.cache.get(id); }
  let doc = null;
  if (!force) { try { doc = await getResult(id); } catch (e) { netCheck(e); } }
  if (!doc) {
    ctx.progress(`Parsing ${name}…`);
    try { await startParse(id); } catch (e) {
      netCheck(e);
      throw new CliError(`Cannot parse ${name}: ${e.message}`, "The upload may no longer exist on the backend. Re-add the file with `attach`.");
    }
    let st;
    for (;;) {
      if (ctx.cancelled()) throw new CliError("Cancelled (the backend job keeps running; re-run the command later to pick up the result).");
      try { st = await getStatus(id); } catch (e) { netCheck(e); throw new CliError(e.message); }
      ctx.progress(`Parsing ${name}… ${String(st.status).toLowerCase()}${st.page_count ? ` · ${st.page_count} pages` : ""}`);
      if (DONE.includes(st.status)) break;
      await sleep(700);
    }
    ctx.endProgress();
    try { doc = await getResult(id); } catch (e) {
      throw new CliError(`Parsing ended with status ${st.status} but no result was stored.`, st.errors?.[0]?.message);
    }
  }
  const rec = { id, doc, filename: doc.filename || name, md: null };
  ctx.session.cache.set(id, rec);
  ctx.session.current = id;
  rememberDocument({
    id, filename: doc.filename, status: doc.status, format: doc.format || "pdf", pages: doc.page_count,
    tables: doc.blocks.filter((b) => b.type === "table").length, confidence: doc.stats?.mean_confidence, ts: Date.now(),
  });
  return rec;
}

export async function getMd(rec) {
  if (rec.md == null) {
    try { rec.md = await getMarkdown(rec.id); } catch (e) { netCheck(e); throw new CliError("Markdown is not available for this document yet."); }
  }
  return rec.md;
}

// Shared by the extraction commands: resolve the file argument, parse if needed, build the page filter.
export async function target(ctx, args, { fileArg = args.positional[0] } = {}) {
  const entry = resolveTarget(ctx, args.opts.file ?? fileArg);
  const rec = await ensureDoc(ctx, entry, { force: !!args.opts.force });
  const inPage = pagePredicate(args.opts.page);
  if (!inPage) throw new CliError(`Invalid --page value "${args.opts.page}".`, "Use e.g. --page 2, --page 1-3 or --page 1,4-6.");
  return { rec, doc: rec.doc, inPage };
}

export function setLast(ctx, last) { ctx.session.last = { ...last, ts: Date.now() }; }

export const COMMON_OPTIONS = {
  file: { name: "file", short: "f", type: "string", desc: "Document id or filename (default: current document)" },
  page: { name: "page", short: "p", type: "string", desc: "Only these pages, e.g. 2 or 1-3,5" },
  limit: { name: "limit", short: "n", type: "number", desc: "Maximum items to show" },
  all: { name: "all", short: "a", type: "boolean", desc: "Show everything (no limit)" },
  json: { name: "json", type: "boolean", desc: "Print the raw JSON of the result" },
  force: { name: "force", type: "boolean", desc: "Re-parse the document instead of using the stored result" },
  open: { name: "open", short: "o", type: "boolean", desc: "Open the document in the GUI afterwards" },
  minConf: { name: "min-conf", type: "number", desc: "Only items with confidence >= this (0-1)" },
};
