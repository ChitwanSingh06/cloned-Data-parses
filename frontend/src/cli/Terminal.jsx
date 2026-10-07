import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import "./terminal.css";
import { uploadDocument } from "../services/api";
import { L, link, seg } from "./format";
import { complete, runCommand } from "./registry";
import { CliError, newSession } from "./session";

const HKEY = "parseanything.cli.history.v1", UKEY = "parseanything.cli.ui.v1", MAX_LINES = 1500;
const loadHistory = () => { try { const v = JSON.parse(localStorage.getItem(HKEY) || "[]"); return Array.isArray(v) ? v : []; } catch (_) { return []; } };
const saveHistory = (h) => { try { localStorage.setItem(HKEY, JSON.stringify(h.slice(-200))); } catch (_) { /* ignore */ } };
const loadUi = () => { try { return { open: false, height: 320, ...JSON.parse(localStorage.getItem(UKEY) || "{}") }; } catch (_) { return { open: false, height: 320 }; } };

function Part({ p, run, openDoc }) {
  if (p.run) return <button type="button" className={`cli-link ${p.cls || ""}`} title={`Run: ${p.run}`} onClick={() => run(p.run)}>{p.text}</button>;
  if (p.open) return <button type="button" className={`cli-link ${p.cls || ""}`} title="Open in results view" onClick={() => openDoc(p.open)}>{p.text}</button>;
  if (p.href) return <a className={`cli-link ${p.cls || ""}`} href={p.href} target="_blank" rel="noreferrer">{p.text}</a>;
  return <span className={p.cls}>{p.text}</span>;
}

function Line({ l, run, openDoc }) {
  if (l.echo) return <div className="cli-line cli-echo"><span className="cli-prompt">›</span> {l.echo}</div>;
  if (l.pre != null) return <pre className={`cli-line cli-pre ${l.cls || ""}`}>{l.pre}</pre>;
  if (l.img) return <div className="cli-line"><a href={l.href || l.img} target="_blank" rel="noreferrer"><img className="cli-thumb" src={l.img} alt={l.caption || "figure"} loading="lazy" /></a></div>;
  return <div className="cli-line">{(l.parts || []).map((p, i) => <Part key={i} p={p} run={run} openDoc={openDoc} />)}{!(l.parts || []).length && "\u00A0"}</div>;
}

export default function Terminal({ docId, onOpenDoc }) {
  const [ui, setUi] = useState(loadUi);
  const [lines, setLines] = useState([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [hints, setHints] = useState([]);
  const [drag, setDrag] = useState(false);
  const [curName, setCurName] = useState("");
  const session = useRef(newSession());
  const hist = useRef(loadHistory());
  const hIdx = useRef(-1), draft = useRef("");
  const pending = useRef(null), busyRef = useRef(false);
  const cancel = useRef(false), progId = useRef(null), seq = useRef(0), welcomed = useRef(false);
  const guiDoc = useRef(docId);
  const scroller = useRef(null), inputRef = useRef(null), fileRef = useRef(null);

  guiDoc.current = docId;
  useEffect(() => { if (docId) session.current.current = docId; }, [docId]);
  useEffect(() => { try { localStorage.setItem(UKEY, JSON.stringify(ui)); } catch (_) { /* ignore */ } }, [ui]);
  useEffect(() => { document.body.style.paddingBottom = ui.open ? `${ui.height}px` : ""; return () => { document.body.style.paddingBottom = ""; }; }, [ui.open, ui.height]);
  useEffect(() => { const el = scroller.current; if (el) el.scrollTop = el.scrollHeight; }, [lines, ui.open]);
  useEffect(() => { if (ui.open) inputRef.current?.focus(); }, [ui.open]);
  useEffect(() => {
    const onKey = (e) => { if ((e.ctrlKey || e.metaKey) && e.key === "`") { e.preventDefault(); setUi((u) => ({ ...u, open: !u.open })); } };
    window.addEventListener("keydown", onKey); return () => window.removeEventListener("keydown", onKey);
  }, []);

  const print = useCallback((x) => {
    const arr = (Array.isArray(x) ? x : [x]).filter(Boolean).map((l) => ({ ...l, id: ++seq.current }));
    setLines((p) => [...p, ...arr].slice(-MAX_LINES));
  }, []);
  const endProgress = useCallback(() => { const id = progId.current; progId.current = null; if (id) setLines((p) => p.filter((l) => l.id !== id)); }, []);
  const progress = useCallback((text) => {
    const l = { ...L.line(seg("⠿ ", "info"), seg(text, "dim")), id: progId.current || ++seq.current };
    if (!progId.current) { progId.current = l.id; setLines((p) => [...p, l]); } else setLines((p) => p.map((x) => (x.id === l.id ? l : x)));
  }, []);

  const execRef = useRef(null);
  const ctx = useMemo(() => ({
    session: session.current, print, progress, endProgress,
    get guiDocId() { return guiDoc.current; },
    cancelled: () => cancel.current,
    openDoc: (id) => onOpenDoc?.(id),
    run: (c) => execRef.current?.(c),
    clear: () => setLines([]),
    attachFile: () => fileRef.current?.click(),
    history: { list: () => hist.current, clear: () => { hist.current = []; saveHistory([]); } },
  }), [print, progress, endProgress, onOpenDoc]);

  const exec = useCallback(async (raw) => {
    const text = raw.trim();
    if (!text) return;
    if (busyRef.current) { print(L.warn("A command is still running. Press Ctrl+C to cancel it.")); return; }
    setInput(""); setHints([]); hIdx.current = -1; pending.current = null;
    if (hist.current[hist.current.length - 1] !== text) { hist.current = [...hist.current, text]; saveHistory(hist.current); }
    if (!/^(clear|cls)\b/.test(text)) print({ echo: text });
    busyRef.current = true; setBusy(true); cancel.current = false;
    try { await runCommand(text, ctx); }
    catch (e) {
      endProgress();
      if (e instanceof CliError && e.needsFile) {
        pending.current = { text, name: e.needsFile };
        print([L.warn(e.message), L.dim(`  Choose "${e.needsFile}" in the file dialog — the command will run automatically after the upload.`)]);
        ctx.attachFile();
      } else if (e instanceof CliError) print([L.err(e.message), e.hint ? L.dim(`  ${e.hint}`) : null]);
      else print([L.err(`Unexpected error: ${e?.message || e}`), L.dim("  Check the browser console and `status`.")]);
    } finally {
      endProgress(); busyRef.current = false; setBusy(false);
      const cur = session.current.cache.get(session.current.current);
      setCurName(cur?.filename || "");
      setTimeout(() => inputRef.current?.focus(), 0);
    }
  }, [ctx, print, endProgress]);
  execRef.current = exec;

  const attach = useCallback(async (files) => {
    for (const f of Array.from(files || [])) {
      busyRef.current = true; setBusy(true);
      try {
        progress(`Uploading ${f.name}…`);
        const up = await uploadDocument(f);
        endProgress();
        session.current.docs.set(up.file_id, { id: up.file_id, filename: f.name, ts: Date.now() });
        session.current.current = up.file_id; setCurName(f.name);
        print([L.ok(`Attached ${f.name} (${(up.size_bytes / 1024).toFixed(0)} KB) · id ${up.file_id}`), L.line(seg("  next: ", "dim"), link.run(`parse "${f.name}"`, `parse "${f.name}"`), "  ", link.run("pdf", "pdf"), "  ", link.run("ocr", "ocr"))]);
      } catch (e) {
        endProgress();
        print([L.err(`Upload failed: ${e instanceof TypeError ? "backend unreachable — run `status`" : e.message}`)]);
      } finally { busyRef.current = false; setBusy(false); }
    }
    const p = pending.current; pending.current = null;
    if (p && files?.length) { // re-run the command that asked for the file, pointing it at what was actually uploaded
      const f = files[0], quoted = /\s/.test(f.name) ? `"${f.name}"` : f.name;
      setTimeout(() => execRef.current?.(p.text.split(p.name).join(quoted)), 0);
    }
  }, [print, progress, endProgress]);

  // First open: banner.
  useEffect(() => {
    if (ui.open && !welcomed.current) {
      welcomed.current = true;
      print([L.head("ParseAnything terminal"), L.line(seg("Type ", "dim"), link.run("help", "help"), seg(" for commands · ", "dim"), link.run("status", "status"), seg(" checks the backend · ", "dim"), link.run("attach", "attach"), seg(" or drop a file here to add a document.", "dim"))]);
    }
  }, [ui.open, print]);

  const refreshHints = (v) => { const t = v.trimStart(); setHints(t ? complete(v, ctx).candidates.slice(0, 10).map((c) => ({ ...c, from: complete(v, ctx).from })) : []); };
  const applyHint = (h, value = input) => { const next = value.slice(0, h.from ?? complete(value, ctx).from) + h.insert + " "; setInput(next); refreshHints(next); inputRef.current?.focus(); };

  const onKeyDown = (e) => {
    if (e.key === "Enter") { e.preventDefault(); exec(input); }
    else if (e.key === "Tab") {
      e.preventDefault();
      const { candidates, from } = complete(input, ctx);
      if (!candidates.length) return;
      if (candidates.length === 1) return applyHint({ ...candidates[0], from });
      let pre = candidates[0].insert;
      for (const c of candidates) while (!c.insert.toLowerCase().startsWith(pre.toLowerCase())) pre = pre.slice(0, -1);
      const typed = input.slice(from);
      if (pre.length > typed.replace(/^["']/, "").length) { const next = input.slice(0, from) + pre; setInput(next); refreshHints(next); }
      else print(L.dim(candidates.map((c) => c.label).join("   ")));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      const h = hist.current; if (!h.length) return;
      if (hIdx.current === -1) { draft.current = input; hIdx.current = h.length - 1; } else hIdx.current = Math.max(0, hIdx.current - 1);
      setInput(h[hIdx.current]); setHints([]);
    } else if (e.key === "ArrowDown") {
      e.preventDefault();
      if (hIdx.current === -1) return;
      const h = hist.current; hIdx.current += 1;
      if (hIdx.current >= h.length) { hIdx.current = -1; setInput(draft.current); } else setInput(h[hIdx.current]);
      setHints([]);
    } else if (e.ctrlKey && e.key.toLowerCase() === "l") { e.preventDefault(); setLines([]); }
    else if (e.ctrlKey && e.key.toLowerCase() === "c") {
      if (busy) { e.preventDefault(); cancel.current = true; print(L.warn("Cancelling…")); }
      else if (!window.getSelection()?.toString()) { e.preventDefault(); print({ echo: `${input}^C` }); setInput(""); setHints([]); }
    } else if (e.key === "Escape") { setHints([]); }
  };

  const startResize = (e) => {
    e.preventDefault();
    const move = (ev) => setUi((u) => ({ ...u, height: Math.max(180, Math.min(window.innerHeight * 0.85, window.innerHeight - ev.clientY)) }));
    const up = () => { window.removeEventListener("mousemove", move); window.removeEventListener("mouseup", up); };
    window.addEventListener("mousemove", move); window.addEventListener("mouseup", up);
  };

  if (!ui.open) {
    return <button type="button" className="cli-fab" onClick={() => setUi((u) => ({ ...u, open: true }))} aria-label="Open terminal" title="Open terminal (Ctrl+`)"><span>›_</span> Terminal</button>;
  }
  return (
    <section className={`cli-panel ${drag ? "drag" : ""}`} style={{ height: ui.height }} aria-label="Terminal"
      onDragOver={(e) => { e.preventDefault(); setDrag(true); }} onDragLeave={() => setDrag(false)}
      onDrop={(e) => { e.preventDefault(); setDrag(false); if (e.dataTransfer?.files?.length) attach(e.dataTransfer.files); }}>
      <div className="cli-resize" onMouseDown={startResize} role="separator" aria-orientation="horizontal" aria-label="Resize terminal" />
      <header className="cli-bar">
        <span className="cli-title"><span className="cli-mark">›_</span> Terminal</span>
        <span className="cli-doc" title="Current document">{curName || (docId ? `doc ${docId}` : "no document")}</span>
        <span className="cli-bar-actions">
          <button type="button" onClick={() => fileRef.current?.click()} title="Attach a file">attach</button>
          <button type="button" onClick={() => setLines([])} title="Clear (Ctrl+L)">clear</button>
          <button type="button" onClick={() => setUi((u) => ({ ...u, open: false }))} title="Close (Ctrl+`)" aria-label="Close terminal">✕</button>
        </span>
      </header>
      <div className="cli-scroll" ref={scroller} onClick={() => { if (!window.getSelection()?.toString()) inputRef.current?.focus(); }}>
        {lines.map((l) => <Line key={l.id} l={l} run={exec} openDoc={(id) => { onOpenDoc?.(id); }} />)}
      </div>
      {hints.length > 0 && !busy && (
        <div className="cli-hints" role="listbox" aria-label="Suggestions">
          {hints.map((h) => <button type="button" key={h.label} onMouseDown={(e) => e.preventDefault()} onClick={() => applyHint(h)}>{h.label}</button>)}
          <span className="cli-hint-tip">Tab ↹</span>
        </div>
      )}
      <div className="cli-input-row">
        <span className="cli-prompt">{busy ? "…" : "›"}</span>
        <input ref={inputRef} className="cli-input" value={input} disabled={busy} spellCheck={false} autoComplete="off" autoCapitalize="off" autoCorrect="off"
          placeholder={busy ? "Running… (Ctrl+C to cancel)" : "Type a command — try `help`"}
          onChange={(e) => { setInput(e.target.value); hIdx.current = -1; refreshHints(e.target.value); }} onKeyDown={onKeyDown} aria-label="Terminal input" />
      </div>
      <input ref={fileRef} hidden type="file" multiple accept=".pdf,.docx,.pptx,.xlsx,.png,.jpg,.jpeg,.tif,.tiff,.bmp,.webp,.gif,image/*,application/pdf"
        onChange={(e) => { attach(e.target.files); e.target.value = ""; }} />
    </section>
  );
}
