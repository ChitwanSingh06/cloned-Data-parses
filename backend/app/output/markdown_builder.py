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


def _chart_table(c: dict) -> str:
    ct, series = c["chart_type"], c.get("series", [])
    unit = (c.get("y_axis") or {}).get("unit")
    vlabel = f"Value ({unit})" if unit else "Value"
    if ct == "scatter":
        rows = ["| x | y |", "|---|---|"] + [f"| {_esc(p.get('x'))} | {_esc(p.get('value'))} |" for s in series for p in s["points"]]
        return "\n".join(rows)
    if ct == "pie":
        rows = ["| Category | Share (%) |", "|---|---|"] + [f"| {_esc(p.get('category'))} | {_esc(p.get('value'))} |" for p in series[0]["points"]]
        return "\n".join(rows)
    if ct == "histogram":
        rows = [f"| Bin | {vlabel} |", "|---|---|"]
        for p in series[0]["points"]:
            lo, hi = p.get("bin_start"), p.get("bin_end")
            rows.append(f"| {_esc(p.get('category') or (f'{lo}–{hi}' if lo is not None else '?'))} | {_esc(p.get('value'))} |")
        return "\n".join(rows)
    cats = [p.get("category") for p in series[0]["points"]]
    head = ["Category"] + [s.get("name") or vlabel for s in series]
    rows = ["| " + " | ".join(head) + " |", "|" + "|".join(["---"] * len(head)) + "|"]
    for i, cat in enumerate(cats):
        rows.append("| " + " | ".join([_esc(cat)] + [_esc(s["points"][i].get("value") if i < len(s["points"]) else "") for s in series]) + " |")
    return "\n".join(rows)


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
            if t == "chart" and isinstance(c, dict):
                alt = c.get("title") or meta.get("caption") or "Chart"
                parts = [f"**{c['title']}**"] if c.get("title") else []
                if meta.get("image_path"):
                    parts.append(f"![{_esc(alt)}]({meta['image_path']})")
                if c.get("data_extracted") and c.get("series"):
                    ylab = (c.get("y_axis") or {}).get("label")
                    parts.append(f"*{c['chart_type'].capitalize()} chart" + (f" — y-axis: {ylab}" if ylab else "") +
                                 ". Values read from axis ticks/printed labels.*")
                    parts.append(_chart_table(c))
                else:
                    parts.append("*Chart values were not extracted.*")
                out.append("\n\n".join(parts) + (("\n" + _review(b)) if _review(b) else ""))
                continue
            alt = meta.get("caption") or ("Chart" if t == "chart" else "Figure")
            chunk = f"![{_esc(alt)}]({meta['image_path']})" if meta.get("image_path") else f"*[{t} region on page {b['page']}]*"
            if t == "chart":
                chunk += "\n\n*Chart values were not extracted.*"
                if meta.get("visible_labels"):
                    chunk += " Printed labels: " + ", ".join(meta["visible_labels"][:40])
            elif meta.get("embedded_text"):
                chunk += "\n\n*Text inside figure:* " + " ".join(meta["embedded_text"][:40])
        elif t == "equation":
            raw = c.get("raw_text") if isinstance(c, dict) else c
            latex = (c.get("latex") if isinstance(c, dict) else None) or meta.get("latex")
            if latex:
                chunk = f"$$\n{latex}\n$$"  # never a heading: always a display-math block
            else:
                img = f"![equation]({meta['image_path']})\n\n" if meta.get("image_path") else ""
                chunk = f"{img}> Unrecognized equation (text layer): {raw}" if raw else img.strip()
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
