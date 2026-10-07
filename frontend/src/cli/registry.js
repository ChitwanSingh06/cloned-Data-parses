// Command registry + dispatcher + autocomplete. To add a command, create an object
//   { name, aliases?, summary, usage, file?, options?, args?, examples?, async run(ctx, {positional, opts}) }
// in any commands/*.js module and add that module's array to MODULES below.
import { closest, parseArgs, tokenize } from "./parseArgs";
import { L, link, seg } from "./format";
import { CliError, knownDocs } from "./session";
import { commandHelp, coreCommands } from "./commands/core";
import { documentCommands } from "./commands/document";
import { extractCommands } from "./commands/extract";
import { outputCommands } from "./commands/output";

const registry = {
  _map: new Map(), _list: [],
  register(cmd) { this._list.push(cmd); this._map.set(cmd.name, cmd); (cmd.aliases || []).forEach((a) => this._map.set(a, cmd)); },
  get(n) { return this._map.get(String(n).toLowerCase()); },
  all() { return this._list; },
  names() { return this._list.map((c) => c.name); },
};
[documentCommands, extractCommands, outputCommands, coreCommands(registry)].flat().forEach((c) => registry.register(c));
export default registry;

export async function runCommand(line, ctx) {
  const tokens = tokenize(line);
  if (!tokens.length) return;
  const cmd = registry.get(tokens[0]);
  if (!cmd) {
    const near = closest(tokens[0], [...registry._map.keys()]);
    throw new CliError(`Unknown command "${tokens[0]}".${near ? ` Did you mean \`${near}\`?` : ""}`, "Type `help` to list all commands.");
  }
  const args = parseArgs(tokens.slice(1), cmd);
  if (args.opts.help) return void ctx.print(commandHelp(cmd));
  if (args.errors.length) {
    ctx.print([...args.errors.map((e) => L.err(e)), L.line(seg("  usage: ", "dim"), seg(cmd.usage, "code"), seg("   ", ""), link.run(`help ${cmd.name}`, `help ${cmd.name}`))]);
    return;
  }
  await cmd.run(ctx, args);
}

// Returns { candidates:[{label, insert}], from } for the text before the cursor.
export function complete(input, ctx) {
  const m = input.match(/(?:^|\s)(\S*)$/), word = m ? m[1] : "", from = input.length - word.length;
  const before = tokenize(input.slice(0, from));
  const q = (s) => (/\s/.test(s) ? `"${s}"` : s);
  const lower = word.replace(/^["']/, "").toLowerCase();
  if (before.length === 0) {
    const names = [...registry._map.keys()].filter((n) => n.startsWith(lower) && !(registry.get(n).name !== n && n.length < 3 && !lower));
    return { from, candidates: [...new Set(names)].sort().map((n) => ({ label: n, insert: n })) };
  }
  const cmd = registry.get(before[0]);
  if (!cmd) return { from, candidates: [] };
  if (word.startsWith("-")) {
    const opts = [...(cmd.options || []), { name: "help", short: "h" }];
    const c = [];
    opts.forEach((o) => { if (`--${o.name}`.startsWith(word)) c.push({ label: `--${o.name}`, insert: `--${o.name}` }); if (o.short && word.length <= 2 && `-${o.short}`.startsWith(word) && word !== "-") c.push({ label: `-${o.short}`, insert: `-${o.short}` }); });
    return { from, candidates: c };
  }
  const prev = before[before.length - 1], prevOpt = (cmd.options || []).find((o) => prev === `--${o.name}` || (o.short && prev === `-${o.short}`));
  if (prevOpt?.values) return { from, candidates: prevOpt.values.filter((v) => v.startsWith(lower)).map((v) => ({ label: v, insert: v })) };
  if (prevOpt && prevOpt.type !== "boolean" && prevOpt.name !== "file") return { from, candidates: [] };
  const fileSlot = prevOpt?.name === "file" || (cmd.file && before.length === 1);
  if (fileSlot) {
    const docs = knownDocs(ctx).filter((d) => d.filename && d.filename.toLowerCase().includes(lower));
    return { from, candidates: [...new Map(docs.map((d) => [d.filename, d])).values()].map((d) => ({ label: d.filename, insert: q(d.filename) })) };
  }
  if (cmd.args) {
    const list = typeof cmd.args === "function" ? cmd.args() : cmd.args;
    if (before.length === 1) return { from, candidates: list.filter((v) => v.startsWith(lower)).map((v) => ({ label: v, insert: v })) };
  }
  return { from, candidates: [] };
}
