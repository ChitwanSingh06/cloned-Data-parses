// Tokenizer + option parser for the terminal. Pure functions (no React, no network).

export function tokenize(input) {
  const out = [];
  let cur = "", q = null, has = false;
  for (let i = 0; i < input.length; i++) {
    const ch = input[i];
    if (q) {
      if (ch === q) q = null;
      else if (ch === "\\" && q === '"' && i + 1 < input.length) cur += input[++i];
      else cur += ch;
    } else if (ch === '"' || ch === "'") { q = ch; has = true; }
    else if (/\s/.test(ch)) { if (cur || has) out.push(cur); cur = ""; has = false; }
    else cur += ch;
  }
  if (cur || has) out.push(cur);
  return out;
}

// spec.options: [{ name, short?, type: "string" | "number" | "boolean", desc, values? }]
export function parseArgs(tokens, spec = {}) {
  const options = [...(spec.options || []), { name: "help", short: "h", type: "boolean", desc: "Show help for this command" }];
  const byName = new Map(options.map((o) => [o.name, o]));
  const byShort = new Map(options.filter((o) => o.short).map((o) => [o.short, o]));
  const positional = [], opts = {}, errors = [];
  for (let i = 0; i < tokens.length; i++) {
    const tok = tokens[i];
    if (tok === "--") { positional.push(...tokens.slice(i + 1)); break; }
    let def = null, inline;
    if (tok.startsWith("--") && tok.length > 2) {
      const [n, ...rest] = tok.slice(2).split("=");
      def = byName.get(n); inline = rest.length ? rest.join("=") : undefined;
      if (!def) { errors.push(`Unknown option --${n}`); continue; }
    } else if (/^-[A-Za-z]$/.test(tok)) {
      def = byShort.get(tok[1]);
      if (!def) { errors.push(`Unknown option ${tok}`); continue; }
    } else { positional.push(tok); continue; }
    if (def.type === "boolean") { opts[def.name] = inline === undefined ? true : !/^(false|0|no)$/i.test(inline); continue; }
    let val = inline;
    if (val === undefined) {
      const nxt = tokens[i + 1];
      if (nxt === undefined || (nxt.startsWith("-") && !/^-\d+$/.test(nxt))) { errors.push(`Option --${def.name} needs a value`); continue; }
      val = nxt; i++;
    }
    if (def.type === "number") {
      const n = Number(val);
      if (!Number.isFinite(n)) { errors.push(`Option --${def.name} expects a number, got "${val}"`); continue; }
      opts[def.name] = n;
    } else {
      if (def.values && !def.values.includes(val.toLowerCase())) { errors.push(`Option --${def.name} must be one of: ${def.values.join(", ")}`); continue; }
      opts[def.name] = def.values ? val.toLowerCase() : val;
    }
  }
  return { positional, opts, errors };
}

// "1-3,5" -> predicate(page). Returns null when the spec is invalid.
export function pagePredicate(spec) {
  if (spec == null || spec === "") return () => true;
  const ranges = [];
  for (const part of String(spec).split(",")) {
    const m = part.trim().match(/^(\d+)(?:-(\d+))?$/);
    if (!m) return null;
    const a = Number(m[1]), b = m[2] ? Number(m[2]) : a;
    ranges.push([Math.min(a, b), Math.max(a, b)]);
  }
  return (p) => ranges.some(([a, b]) => p >= a && p <= b);
}

export function closest(word, candidates) {
  const d = (a, b) => {
    const m = Array.from({ length: a.length + 1 }, (_, i) => [i, ...Array(b.length).fill(0)]);
    for (let j = 1; j <= b.length; j++) m[0][j] = j;
    for (let i = 1; i <= a.length; i++) for (let j = 1; j <= b.length; j++)
      m[i][j] = Math.min(m[i - 1][j] + 1, m[i][j - 1] + 1, m[i - 1][j - 1] + (a[i - 1] === b[j - 1] ? 0 : 1));
    return m[a.length][b.length];
  };
  let best = null, bd = 3;
  for (const c of candidates) { const x = d(word.toLowerCase(), c); if (x < bd) { bd = x; best = c; } }
  return best;
}
