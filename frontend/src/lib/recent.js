// Remembers documents parsed in this browser (id + real values read from the stored result).
// Purely presentational: used for the dashboard stats / recent list. No backend changes.
const KEY = "parseanything.recent.v1";

export function loadRecent() {
  try {
    const v = JSON.parse(localStorage.getItem(KEY) || "[]");
    return Array.isArray(v) ? v : [];
  } catch (_) { return []; }
}

export function rememberDocument(entry) {
  try {
    const list = loadRecent().filter((d) => d.id !== entry.id);
    const prev = loadRecent().find((d) => d.id === entry.id);
    list.unshift({ ...entry, ts: prev?.ts || entry.ts || Date.now() });
    localStorage.setItem(KEY, JSON.stringify(list.slice(0, 50)));
  } catch (_) { /* storage unavailable: ignore */ }
}

export function forgetDocument(id) {
  try { localStorage.setItem(KEY, JSON.stringify(loadRecent().filter((d) => d.id !== id))); } catch (_) { /* ignore */ }
}

export const timeAgo = (ts) => {
  const s = Math.max(0, (Date.now() - ts) / 1000);
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.floor(s / 60)} min ago`;
  if (s < 86400) return `${Math.floor(s / 3600)} h ago`;
  return new Date(ts).toLocaleDateString();
};
