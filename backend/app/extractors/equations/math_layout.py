"""Spatial math reconstruction: characters + positions (text layer) -> LaTeX.

Evidence used (never guessed): glyph size relative to the equation's base size, baseline offset (origin y),
Unicode super/subscript code points, horizontal rules (fractions / radicals), stacked limits above/below
big operators. Anything not covered is kept verbatim and reported in `unmapped` so confidence drops.
"""
import re
from typing import Optional

GREEK = {c: "\\" + n for c, n in zip("αβγδεζηθικλμνξπρστυφχψωΓΔΘΛΞΠΣΦΨΩ",
         "alpha beta gamma delta epsilon zeta eta theta iota kappa lambda mu nu xi pi rho sigma tau upsilon phi chi psi omega "
         "Gamma Delta Theta Lambda Xi Pi Sigma Phi Psi Omega".split())}
GREEK.update({"ϕ": "\\varphi", "ϵ": "\\varepsilon", "ϑ": "\\vartheta"})
OPS = {"×": "\\times", "÷": "\\div", "·": "\\cdot", "∙": "\\cdot", "⋅": "\\cdot", "−": "-", "–": "-", "±": "\\pm", "∓": "\\mp",
       "≤": "\\leq", "≥": "\\geq", "≠": "\\neq", "≈": "\\approx", "≡": "\\equiv", "∼": "\\sim", "∝": "\\propto", "∞": "\\infty",
       "→": "\\to", "←": "\\leftarrow", "⇒": "\\Rightarrow", "⇔": "\\Leftrightarrow", "∂": "\\partial", "∇": "\\nabla",
       "∈": "\\in", "∉": "\\notin", "⊂": "\\subset", "⊆": "\\subseteq", "∪": "\\cup", "∩": "\\cap", "∀": "\\forall",
       "∃": "\\exists", "∑": "\\sum", "∏": "\\prod", "∫": "\\int", "∬": "\\iint", "∮": "\\oint", "°": "^{\\circ}",
       "′": "'", "ℝ": "\\mathbb{R}", "ℕ": "\\mathbb{N}", "ℤ": "\\mathbb{Z}", "ℚ": "\\mathbb{Q}", "…": "\\ldots", "⋯": "\\cdots",
       "%": "\\%", "&": "\\&", "#": "\\#", "_": "\\_", "{": "\\{", "}": "\\}", "$": "\\$", "√": "\\surd"}
SUP_CHARS = dict(zip("⁰¹²³⁴⁵⁶⁷⁸⁹⁺⁻⁼⁽⁾ⁿⁱ", "0123456789+-=()ni"))
SUB_CHARS = dict(zip("₀₁₂₃₄₅₆₇₈₉₊₋₌₍₎ₐₑₒₓₙᵢⱼ", "0123456789+-=()aeoxnij"))
BIG_OPS = {"∑", "∏"}


def _sym(ch: str, unmapped: list) -> str:
    if ch in GREEK:
        return GREEK[ch] + " "
    if ch in OPS:
        return OPS[ch] + (" " if OPS[ch].startswith("\\") and OPS[ch][-1].isalpha() else "")
    if ord(ch) > 127:
        unmapped.append(ch)
    return ch


def get_chars(page, bbox: list[float], pad: float = 1.5) -> list[dict]:
    """Per-character records inside bbox (PDF points, y down)."""
    import pymupdf
    clip = pymupdf.Rect(bbox[0] - pad, bbox[1] - pad, bbox[2] + pad, bbox[3] + pad)
    out = []
    for b in page.get_text("rawdict", clip=clip)["blocks"]:
        if b["type"] != 0:
            continue
        for ln in b["lines"]:
            for sp in ln["spans"]:
                for c in sp["chars"]:
                    bb = c["bbox"]
                    cx, cy = (bb[0] + bb[2]) / 2, (bb[1] + bb[3]) / 2
                    if clip.x0 <= cx <= clip.x1 and clip.y0 <= cy <= clip.y1 and c["c"] != "\u00a0":
                        out.append({"c": c["c"], "x0": bb[0], "x1": bb[2], "y0": bb[1], "y1": bb[3], "oy": c["origin"][1],
                                    "ox": c["origin"][0], "size": sp["size"], "font": sp["font"]})
    return out


def get_hrules(page, bbox: list[float]) -> list[tuple[float, float, float]]:
    """Horizontal rules (x0, x1, y) inside bbox: drawn lines or very thin filled rectangles."""
    rules = []
    for d in page.get_drawings():
        for it in d["items"]:
            if it[0] == "l" and abs(it[1].y - it[2].y) < 0.8 and abs(it[1].x - it[2].x) >= 5:
                x0, x1, y = min(it[1].x, it[2].x), max(it[1].x, it[2].x), it[1].y
            elif it[0] == "re" and it[1].height <= 1.6 and it[1].width >= 5:
                x0, x1, y = it[1].x0, it[1].x1, (it[1].y0 + it[1].y1) / 2
            else:
                continue
            if x0 >= bbox[0] - 3 and x1 <= bbox[2] + 3 and bbox[1] - 3 <= y <= bbox[3] + 3:
                rules.append((x0, x1, y))
    return rules


def _base(chars: list[dict]) -> tuple[float, float]:
    vis = [c for c in chars if c["c"].strip()]
    sizes: dict[float, int] = {}
    for c in vis:
        sizes[round(c["size"] * 2) / 2] = sizes.get(round(c["size"] * 2) / 2, 0) + 1
    size = max(sizes, key=sizes.get)
    ys = sorted(c["oy"] for c in vis if c["size"] >= 0.9 * size)
    return size, ys[len(ys) // 2]


def _row(chars: list[dict], unmapped: list, ctx: dict) -> str:
    """Linearise one baseline row (scripts via size/offset evidence)."""
    chars = sorted(chars, key=lambda c: c["x0"])
    chars = [c for c in chars if c["c"].strip() or True]
    if not chars:
        return ""
    size, base_y = _base(chars) if any(c["c"].strip() for c in chars) else (chars[0]["size"], chars[0]["oy"])
    out: list[str] = []
    cur_level, buf = 0, []
    last_base_x1: Optional[float] = None

    def flush():
        nonlocal buf, cur_level
        if buf:
            txt = "".join(buf)
            out.append(("^{%s}" if cur_level > 0 else "_{%s}") % txt)
            ctx["scripts"] += 1
        buf, cur_level = [], 0

    for c in chars:
        ch = c["c"]
        if not ch.strip():
            flush(); out.append(" "); continue
        dy = base_y - c["oy"]
        small = c["size"] <= 0.85 * size
        level = 0
        if ch in SUP_CHARS:
            level, ch = 1, SUP_CHARS[ch]
        elif ch in SUB_CHARS:
            level, ch = -1, SUB_CHARS[ch]
        elif last_base_x1 is not None and c["x0"] - last_base_x1 < 0.6 * size:  # must be attached to a base glyph
            if small and dy >= 0.22 * size:
                level = 1
            elif small and dy <= -0.12 * size:
                level = -1
            elif not small and abs(dy) >= 0.35 * size:
                level = 1 if dy > 0 else -1
        sym = _sym(ch, unmapped) if ch not in "()[]" else ch
        if level != 0:
            if level != cur_level:
                flush(); cur_level = level
            buf.append(sym.strip() if sym.strip() else sym)
            last_base_x1 = max(last_base_x1 or 0, c["x1"]) if False else last_base_x1
        else:
            flush()
            out.append(sym)
            last_base_x1 = c["x1"]
    flush()
    s = "".join(out)
    s = re.sub(r"\\surd\s*\(([^()]*)\)", r"\\sqrt{\1}", s)
    s = re.sub(r"\\surd\s*([A-Za-z0-9.]+)", r"\\sqrt{\1}", s)
    return re.sub(r"[ \t]+", " ", s).strip()


def _in_x(c: dict, x0: float, x1: float, tol: float = 2.0) -> bool:
    return x0 - tol <= (c["x0"] + c["x1"]) / 2 <= x1 + tol


def chars_to_latex(chars: list[dict], rules: list[tuple[float, float, float]]) -> dict:
    """Return {'latex', 'unmapped', 'structures'}; structures lists what spatial evidence was used."""
    unmapped: list[str] = []
    ctx = {"scripts": 0}
    structures: list[str] = []
    if not chars:
        return {"latex": None, "unmapped": [], "structures": []}
    size, base_y = _base(chars)
    remaining = list(chars)
    placeholders: dict[float, str] = {}  # x position -> latex for fractions / radicals / limits
    # --- radicals: overline whose left end touches a radical sign --------------------------------------
    for x0, x1, y in sorted(rules, key=lambda r: r[2]):
        root = next((c for c in remaining if c["c"] == "√" and abs(c["x1"] - x0) <= 0.4 * size and abs(c["y0"] - y) <= 0.8 * size), None)
        if not root:
            continue
        under = [c for c in remaining if c is not root and _in_x(c, x0, x1, 0.5) and y - 0.2 * size <= c["y0"] + 0.6 * size and c["y0"] >= y - 0.5 * size and c["y1"] <= y + 1.6 * size]
        if under:
            placeholders[root["x0"]] = "\\sqrt{%s}" % _row(under, unmapped, ctx)
            remaining = [c for c in remaining if c is not root and c not in under]
            structures.append("radical")
    # --- fractions: numerator above / denominator below a rule -----------------------------------------
    for x0, x1, y in sorted(rules, key=lambda r: -(r[1] - r[0])):
        num = [c for c in remaining if c["c"].strip() and _in_x(c, x0, x1) and c["y1"] <= y + 0.5 and c["y1"] >= y - 2.4 * size]
        den = [c for c in remaining if c["c"].strip() and _in_x(c, x0, x1) and c["y0"] >= y - 0.5 and c["y0"] <= y + 2.4 * size]
        if num and den:
            placeholders[x0] = "\\frac{%s}{%s}" % (_row(num, unmapped, ctx), _row(den, unmapped, ctx))
            remaining = [c for c in remaining if c not in num and c not in den]
            structures.append("fraction")
    # --- big operators with stacked limits ----------------------------------------------------------------
    for op in [c for c in remaining if c["c"] in BIG_OPS]:
        oh = op["y1"] - op["y0"]
        cyc = lambda c: (c["y0"] + c["y1"]) / 2
        up = [c for c in remaining if c is not op and _in_x(c, op["x0"], op["x1"], 3) and c["size"] < op["size"] and cyc(c) < op["y0"] + 0.4 * oh and cyc(c) >= op["y0"] - 2.2 * size]
        lo = [c for c in remaining if c is not op and _in_x(c, op["x0"], op["x1"], 3) and c["size"] < op["size"] and cyc(c) > op["y1"] - 0.4 * oh and cyc(c) <= op["y1"] + 2.2 * size]
        if up or lo:
            tex = OPS[op["c"]] + (("_{%s}" % _row(lo, unmapped, ctx)) if lo else "") + (("^{%s}" % _row(up, unmapped, ctx)) if up else "")
            placeholders[op["x0"]] = tex
            remaining = [c for c in remaining if c is not op and c not in up and c not in lo]
            structures.append("limits")
    # --- main row, with placeholders spliced in at their x position -------------------------------------
    marks = [{"c": "\u0001", "x0": x, "x1": x + 0.1, "y0": base_y - size, "y1": base_y, "oy": base_y, "ox": x, "size": size, "font": "", "tex": t}
             for x, t in placeholders.items()]
    row = _row(remaining + marks, unmapped, ctx)
    for m in marks:
        row = row.replace("\u0001", " " + m["tex"] + " ", 1)
    row = re.sub(r"[ \t]+", " ", row).strip()
    if ctx["scripts"]:
        structures.append("scripts")
    if any(c["c"] in "∫∬∮" for c in chars):
        structures.append("integral")
    row = re.sub(r"\s*\((\d{1,3}(?:\.\d+)?)\)\s*$", r" \\tag{\1}", row) if re.search(r"\s{1}\(\d{1,3}(\.\d+)?\)\s*$", row) and "=" in row else row
    return {"latex": row.strip() or None, "unmapped": sorted(set(unmapped)), "structures": sorted(set(structures))}


def page_region_to_latex(page, bbox: list[float]) -> dict:
    chars = get_chars(page, bbox)
    if not any(c["c"].strip() for c in chars):
        return {"latex": None, "unmapped": [], "structures": [], "reason": "no text layer"}
    return chars_to_latex(chars, get_hrules(page, bbox))


def group_stacked_math(page, lines: list[dict]) -> tuple[list[dict], list[dict]]:
    """Merge text lines that only make sense together: fraction numerator/denominator around a rule, and
    stacked limits around a big operator. Returns (groups[{bbox,text}], remaining_lines)."""
    from app.utils.bbox import union
    W = page.rect.width
    groups: list[dict] = []
    taken: set[int] = set()
    rules = [r for r in get_hrules(page, [0, 0, W, page.rect.height]) if r[1] - r[0] <= 0.5 * W]

    def row_neighbours(core: list[int]) -> list[int]:
        box = None
        for i in core:
            box = union(box, lines[i]["bbox"])
        changed = True
        while changed:
            changed = False
            for k, l in enumerate(lines):
                if k in core or k in taken:
                    continue
                if min(l["bbox"][3], box[3]) - max(l["bbox"][1], box[1]) > 0.3 * (l["bbox"][3] - l["bbox"][1]) and 0 <= max(l["bbox"][0] - box[2], box[0] - l["bbox"][2]) <= 36 \
                        and len(l["text"]) <= 40:
                    core = core + [k]
                    box = union(box, l["bbox"])
                    changed = True
        return core

    def emit(idx: list[int], extra: Optional[list[float]] = None) -> None:
        box = extra
        for i in idx:
            box = union(box, lines[i]["bbox"])
        txt = " ".join(lines[i]["text"] for i in sorted(idx, key=lambda i: (lines[i]["bbox"][0], lines[i]["bbox"][1])))
        groups.append({"bbox": box, "text": txt, "n_lines": len(idx)})
        taken.update(idx)

    for x0, x1, y in rules:
        num = [i for i, l in enumerate(lines) if i not in taken and len(l["text"]) <= 30 and x0 - 3 <= (l["bbox"][0] + l["bbox"][2]) / 2 <= x1 + 3 and y - 2.6 * (l["bbox"][3] - l["bbox"][1]) <= l["bbox"][1] and l["bbox"][3] <= y + 0.5]
        den = [i for i, l in enumerate(lines) if i not in taken and len(l["text"]) <= 30 and x0 - 3 <= (l["bbox"][0] + l["bbox"][2]) / 2 <= x1 + 3 and l["bbox"][1] >= y - 0.5 and l["bbox"][1] <= y + 2.6 * (l["bbox"][3] - l["bbox"][1])]
        if num and den:
            core = row_neighbours(num + den)
            emit(core, [x0, y - 0.5, x1, y + 0.5])
    for i, l in enumerate(lines):
        if i in taken or not any(c in BIG_OPS for c in l["text"]):
            continue
        sz = l["bbox"][3] - l["bbox"][1]
        near = [k for k, o in enumerate(lines) if k != i and k not in taken and len(o["text"]) <= 14 and o["bbox"][2] > l["bbox"][0] - 4 and o["bbox"][0] < l["bbox"][0] + 0.6 * sz + 14
                and ((o["bbox"][3] <= l["bbox"][1] + 0.5 * sz and o["bbox"][1] >= l["bbox"][1] - 1.6 * sz) or (o["bbox"][1] >= l["bbox"][3] - 0.5 * sz and o["bbox"][1] <= l["bbox"][3] + 1.6 * sz))]
        if near:
            emit(row_neighbours([i] + near))
    return groups, [l for i, l in enumerate(lines) if i not in taken]
