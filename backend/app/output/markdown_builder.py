"""Markdown is rendered ONLY from the canonical document dict (no re-parsing of the PDF)."""
from typing import Any

SKIP = {"header", "footer"}


def _esc(c: Any) -> str:
    return str(c if c is not None else "").replace("|", "\\|").replace("\n", " ").strip()


def _table_md(t: dict) -> str:
    n = t["n_cols"]
    if not n or not (t["headers"] or t["rows"]):
        return ""
    if t["headers"]:
        labels = []
        for j in range(n):
            parts: list[str] = []
            for hr in t["headers"]:
                if hr[j] and (not parts or parts[-1] != hr[j]):
                    parts.append(hr[j])
            labels.append(" / ".join(parts))
    else:
        labels = [""] * n
    lines = ["| " + " | ".join(_esc(x) for x in labels) + " |", "|" + "|".join(["---"] * n) + "|"]
    for r in t["rows"]:
        lines.append("| " + " | ".join(_esc(x) for x in r) + " |")
    return "\n".join(lines)


def _review(b: dict) -> str:
    if b.get("status") == "REVIEW_REQUIRED":
        return f"<!-- REVIEW_REQUIRED {b['id']} p.{b['page']}: {b.get('meta', {}).get('review_reason', 'low confidence')} -->"
    return ""


def build_markdown(document: dict) -> str:
    out: list[str] = []
    for b in document.get("blocks", []):
        t, c, meta = b["type"], b.get("content"), b.get("meta", {})
        if t in SKIP:
            continue
        chunk = ""
        if t == "heading":
            chunk = "#" * max(1, min(6, b.get("level") or 1)) + " " + str(c)
        elif t in ("paragraph", "reference"):
            chunk = "\n".join(f"- {x}" for x in c) if isinstance(c, list) else str(c)
        elif t == "list":
            chunk = "\n".join((f"{i}. " if c["ordered"] else "- ") + x for i, x in enumerate(c["items"], start=1))
        elif t == "table":
            chunk = _table_md(c)
        elif t in ("figure", "chart"):
            alt = meta.get("caption") or ("Chart" if t == "chart" else "Figure")
            chunk = f"![{_esc(alt)}]({meta['image_path']})" if meta.get("image_path") else f"*[{t} region on page {b['page']}]*"
            if t == "chart":
                chunk += "\n\n*Chart values were not extracted.*"
                if meta.get("visible_labels"):
                    chunk += " Printed labels: " + ", ".join(meta["visible_labels"][:40])
            elif meta.get("embedded_text"):
                chunk += "\n\n*Text inside figure:* " + " ".join(meta["embedded_text"][:40])
        elif t == "equation":
            if meta.get("latex"):
                chunk = f"$$\n{meta['latex']}\n$$"
            else:
                img = f"![equation]({meta['image_path']})\n\n" if meta.get("image_path") else ""
                chunk = f"{img}> Unrecognized equation (text layer): {c}" if c else img.strip()
        elif t == "caption":
            chunk = f"*{c}*"
        elif t == "footnote":
            chunk = f"> {c}"
        else:
            chunk = str(c)
        if not chunk:
            continue
        rv = _review(b)
        out.append(chunk + (("\n" + rv) if rv else ""))
    return "\n\n".join(out).strip() + "\n"
