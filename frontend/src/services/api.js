const API_BASE =
  import.meta.env.VITE_API_BASE || "http://localhost:8000/api";

async function json(response, fallback) {
  if (!response.ok) {
    let detail = fallback;
    try {
      const body = await response.json();
      detail = body?.detail?.message || body?.detail || fallback;
    } catch (_) { /* keep fallback */ }
    throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
  }
  return response.json();
}

export async function uploadDocument(file) {
  const formData = new FormData();
  formData.append("file", file);
  return json(await fetch(`${API_BASE}/upload`, { method: "POST", body: formData }), "Upload failed");
}

export async function startParse(fileId) {
  return json(await fetch(`${API_BASE}/parse?file_id=${fileId}`, { method: "POST" }), "Could not start parsing");
}

export async function getStatus(id) {
  return json(await fetch(`${API_BASE}/status/${id}`), "Status unavailable");
}

export async function getResult(id) {
  return json(await fetch(`${API_BASE}/result/${id}`), "Result not ready");
}

export async function getMarkdown(id) {
  const r = await fetch(`${API_BASE}/download/${id}/markdown`);
  if (!r.ok) throw new Error("Markdown not ready");
  return r.text();
}

export const downloadUrl = (id, fmt) => `${API_BASE}/download/${id}/${fmt}`;
export const pageImageUrl = (id, page) => `${API_BASE}/documents/${id}/page/${page}.png`;
export const figureUrl = (id, name) => `${API_BASE}/documents/${id}/figures/${name}`;

export async function waitForCompletion(id, onStatus, intervalMs = 800) {
  for (;;) {
    const st = await getStatus(id);
    onStatus?.(st);
    if (["SUCCESS", "PARTIAL_SUCCESS", "FAILED"].includes(st.status)) return st;
    await new Promise((r) => setTimeout(r, intervalMs));
  }
}

export async function searchDocument(documentId, query, limit = 200) {
  return json(await fetch(`${API_BASE}/search`, {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ document_id: documentId, query, limit }),
  }), "Search failed");
}
