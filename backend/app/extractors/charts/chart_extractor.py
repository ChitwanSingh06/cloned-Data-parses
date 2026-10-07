"""Chart understanding for VECTOR charts (text layer + drawing primitives).

candidate region -> group axis/tick/title/legend text -> chart type -> axis calibration -> values -> ONE chart dict.
Values are only ever derived from (a) printed data labels or (b) a regression of printed axis ticks against
their on-page position. No tick calibration => no numbers; the chart is preserved and flagged for review.
"""
import math
import re
from collections import Counter, defaultdict
from typing import Any, Optional

import numpy as np

from app.extractors.text.pdf_text import CAPTION_RE

NUM = re.compile(r"^\s*([$€£₹]?)\s*(-?[\d,]*\.?\d+)\s*([%kKmMbB]?)\s*$")
SUFFIX = {"k": 1e3, "K": 1e3, "m": 1e6, "M": 1e6, "b": 1e9, "B": 1e9}


def parse_number(text: str) -> Optional[tuple[float, str]]:
    """'$1,200' -> (1200.0, '$'); '45%' -> (45.0, '%'); '2k' -> (2000.0, 'k')."""
    m = NUM.match(text.replace("−", "-").replace("–", "-"))
    if not m:
        return None
    try:
        v = float(m.group(2).replace(",", ""))
    except ValueError:
        return None
    unit = m.group(1) or m.group(3)
    if m.group(3) in SUFFIX:
        v *= SUFFIX[m.group(3)]
    return v, unit


def _hex(c) -> Optional[str]:
    if not c:
        return None
    c = list(c) + [c[0]] * (3 - len(c)) if len(c) < 3 else list(c)[:3]
    return "#%02x%02x%02x" % tuple(int(round(v * 255)) for v in c)


def _cx(b): return (b[0] + b[2]) / 2
def _cy(b): return (b[1] + b[3]) / 2


def _inside(b, box, tol=1.0):
    return b[0] >= box[0] - tol and b[1] >= box[1] - tol and b[2] <= box[2] + tol and b[3] <= box[3] + tol


def _union(boxes):
    return [min(b[0] for b in boxes), min(b[1] for b in boxes), max(b[2] for b in boxes), max(b[3] for b in boxes)]


def _elements(page, bbox) -> dict[str, list]:
    rects, hlines, vlines, slants, markers, wedges = [], [], [], [], [], []
    for d in page.get_drawings():
        r = d["rect"]
        rb = [r.x0, r.y0, r.x1, r.y1]
        if not _inside(rb, bbox, 2.0):
            continue
        fill, stroke = d.get("fill"), d.get("color")
        items = d["items"]
        kinds = [it[0] for it in items]
        white = fill is not None and all(v >= 0.97 for v in fill[:3]) if fill else False
        if kinds.count("c") >= 1 and fill and not white:
            w, h = rb[2] - rb[0], rb[3] - rb[1]
            if w <= 12 and h <= 12:
                markers.append({"bbox": rb, "fill": _hex(fill)})
            else:
                wedges.append({"bbox": rb, "fill": _hex(fill), "items": items})
            continue
        for it in items:
            if it[0] in ("re", "qu") and fill and not white:
                q = it[1].rect if it[0] == "qu" else it[1]
                rects.append({"bbox": [q.x0, q.y0, q.x1, q.y1], "fill": _hex(fill)})
            elif it[0] == "l":
                p, q = it[1], it[2]
                seg = {"p": (p.x, p.y), "q": (q.x, q.y), "color": _hex(stroke), "width": d.get("width") or 1.0}
                if abs(p.y - q.y) < 0.6:
                    hlines.append(seg)
                elif abs(p.x - q.x) < 0.6:
                    vlines.append(seg)
                elif not fill:
                    slants.append(seg)
        if fill and not white and kinds == ["l"] * len(kinds) and len(kinds) >= 3:
            wedges.append({"bbox": rb, "fill": _hex(fill), "items": items})
    return {"rects": rects, "hlines": hlines, "vlines": vlines, "slants": slants, "markers": markers, "wedges": wedges}


def _group_text(lines: list[dict], bbox: list[float], around: bool = False) -> tuple[list[dict], list[dict]]:
    """Return (absorbed chart text lines, all candidates) near the drawing region."""
    ext = [bbox[0] - 70, bbox[1] - 36, bbox[2] + 30, bbox[3] + 50]
    if around:  # pie labels sit anywhere around the circle
        ext = [bbox[0] - 70, bbox[1] - 40, bbox[2] + 70, bbox[3] + 40]
    out = []
    for ln in lines:
        b = ln["bbox"]
        if not _inside(b, ext, 0.5) or CAPTION_RE.match(ln["text"]) or len(ln["text"]) > 60 or len(ln["text"].split()) > 7:
            continue
        inside = _inside(b, bbox, 2.0)
        num = parse_number(ln["text"]) is not None
        rotated = abs(ln["dir"][1]) > 0.5
        cx = _cx(b)
        below = b[1] >= bbox[3] - 6 and bbox[0] - 15 <= cx <= bbox[2] + 15
        left = b[2] <= bbox[0] + 6 and bbox[1] - 8 <= _cy(b) <= bbox[3] + 8
        above = b[3] <= bbox[1] + 2 and abs(cx - _cx(bbox)) <= 0.3 * (bbox[2] - bbox[0]) + 20
        touches = not (b[2] < bbox[0] or b[0] > bbox[2] or b[3] < bbox[1] or b[1] > bbox[3])
        if inside or touches or (around and not num and not rotated) or ((below or left or above) and (num or rotated or below or above)):
            out.append(ln)
    return out, out


def _fit(pos: list[float], vals: list[float]) -> Optional[dict]:
    if len(pos) < 2 or len(set(round(p, 1) for p in pos)) < 2:
        return None
    a, b = np.polyfit(pos, vals, 1)
    pred = np.polyval([a, b], pos)
    ss_res = float(np.sum((np.array(vals) - pred) ** 2))
    ss_tot = float(np.sum((np.array(vals) - np.mean(vals)) ** 2)) or 1.0
    r2 = 1 - ss_res / ss_tot
    steps = np.diff(sorted(vals))
    step = float(np.min(np.abs(steps))) if len(steps) else 1.0
    return {"a": float(a), "b": float(b), "r2": r2, "n": len(pos), "step": step if step > 0 else 1.0}


def _round_to_step(v: float, step: float) -> float:
    dec = max(0, int(-math.floor(math.log10(step))) + 1) if step < 10 else 0
    return round(v, dec)


def _snap(pos: float, lines: list[dict], axis: str, tol=3.0) -> float:
    best = None
    for l in lines:
        c = l["p"][1] if axis == "y" else l["p"][0]
        if abs(c - pos) <= tol and (best is None or abs(c - pos) < abs(best - pos)):
            best = c
    return best if best is not None else pos


def _y_axis(cand: list[dict], bbox, hlines) -> tuple[Optional[dict], list[dict]]:
    nums = [(l, parse_number(l["text"])) for l in cand if abs(l["dir"][1]) < 0.5 and parse_number(l["text"]) and l["bbox"][2] <= bbox[0] + 6]
    clusters: dict[int, list] = defaultdict(list)
    for l, n in nums:
        clusters[round(l["bbox"][2] / 4)].append((l, n))
    if not clusters:
        return None, []
    col = max(clusters.values(), key=len)
    if len(col) < 2:
        return None, []
    ys = [_snap(_cy(l["bbox"]), hlines, "y") for l, _ in col]
    fit = _fit(ys, [n[0] for _, n in col])
    if fit is None or fit["a"] >= 0 and False:
        return None, []
    fit["ticks"] = sorted(n[0] for _, n in col)
    fit["unit"] = col[0][1][1]
    fit["lines"] = [l for l, _ in col]
    return fit, [l for l, _ in col]


def _x_labels(cand: list[dict], bbox, used: set) -> list[dict]:
    rows: dict[int, list] = defaultdict(list)
    for l in cand:
        if id(l) in used or abs(l["dir"][1]) > 0.5 or l["bbox"][1] < bbox[3] - 6:
            continue
        rows[round(_cy(l["bbox"]) / 3)].append(l)
    if not rows:
        return []
    row = min(rows.values(), key=lambda r: _cy(r[0]["bbox"]) - 1000 * len(r))  # most members, then nearest
    row = max(rows.values(), key=len) if len(row) < 2 else row
    return sorted(row, key=lambda l: _cx(l["bbox"]))


def _nearest_label(cx: float, labels: list[dict], tol: float) -> Optional[dict]:
    best = min(labels, key=lambda l: abs(_cx(l["bbox"]) - cx), default=None)
    return best if best is not None and abs(_cx(best["bbox"]) - cx) <= tol else None


def _legend(rects, cand, used, bbox) -> tuple[dict[str, str], list[dict]]:
    names, swatches = {}, []
    for r in rects:
        w, h = r["bbox"][2] - r["bbox"][0], r["bbox"][3] - r["bbox"][1]
        if w > 14 or h > 14:
            continue
        for l in cand:
            if id(l) in used or abs(_cy(l["bbox"]) - _cy(r["bbox"])) < 6 and 0 <= l["bbox"][0] - r["bbox"][2] < 14:
                if abs(_cy(l["bbox"]) - _cy(r["bbox"])) < 6 and 0 <= l["bbox"][0] - r["bbox"][2] < 14:
                    names[r["fill"]] = l["text"]
                    used.add(id(l))
                    swatches.append(r)
                    break
    return names, swatches


def _unit_from(text: str) -> Optional[str]:
    m = re.search(r"\(([^)]+)\)", text) or re.search(r"\b(in|IN)\s+([$€£₹%A-Za-z ]{1,12})$", text)
    return (m.group(1) if m and m.lastindex == 1 else m.group(2)).strip() if m else None


def analyze_vector_chart(page, bbox: list[float], lines: list[dict]) -> Optional[dict]:
    """Return {'chart': {...}, 'bbox': expanded bbox, 'absorbed': [line dicts], 'signals': {...}} or None."""
    el = _elements(page, bbox)
    cand, _ = _group_text(lines, bbox, around=len(el["wedges"]) >= 2)
    used: set[int] = set()
    chart_type, series, notes = None, [], []

    # ---- pie -------------------------------------------------------------------------------------------
    if len(el["wedges"]) >= 2:
        res = _pie(el["wedges"], cand, used)
        if res:
            chart_type, series = "pie", res

    bars: list[dict] = []
    if not chart_type:
        legend_names, swatches = _legend(el["rects"], cand, used, bbox)
        sw_ids = {id(s) for s in swatches}
        big = bbox_area = (bbox[2] - bbox[0]) * (bbox[3] - bbox[1])
        rects = [r for r in el["rects"] if id(r) not in sw_ids and (r["bbox"][2] - r["bbox"][0]) * (r["bbox"][3] - r["bbox"][1]) < 0.6 * big
                 and r["bbox"][2] - r["bbox"][0] >= 3 and r["bbox"][3] - r["bbox"][1] >= 0.5]
        if len(el["markers"]) >= 5 and len(rects) < 2:
            chart_type = "scatter"
        elif len(rects) >= 2:
            bottoms = Counter(round(r["bbox"][3]) for r in rects)
            lefts = Counter(round(r["bbox"][0]) for r in rects)
            if bottoms.most_common(1)[0][1] >= 2 or lefts.most_common(1)[0][1] >= 3:
                chart_type, bars = "bar", rects
        if not chart_type and len(el["slants"]) >= 2:
            chart_type = "line"
    if not chart_type:
        return None

    y_fit, y_lines = _y_axis(cand, bbox, el["hlines"])
    used.update(id(l) for l in y_lines)
    xl = _x_labels(cand, bbox, used)
    used.update(id(l) for l in xl)
    x_numeric = len(xl) >= 2 and all(parse_number(l["text"]) for l in xl)
    notes_review: list[str] = []
    confs: dict[str, float] = {"chart_detection": 0.9 if chart_type != "scatter" else 0.8}
    ytype_unit = (y_fit or {}).get("unit")

    def yval(y: float) -> Optional[float]:
        return None if not y_fit else _round_to_step(y_fit["a"] * y + y_fit["b"], y_fit["step"])

    if y_fit:
        confs["axis_calibration"] = (0.97 if y_fit["n"] >= 3 and y_fit["r2"] >= 0.9999 else 0.8 if y_fit["r2"] >= 0.999 else 0.4) * (1.0 if y_fit["n"] >= 3 else 0.75)
    else:
        confs["axis_calibration"] = 0.15
        notes_review.append("Y-axis tick values could not be read; values were not extracted.")

    if chart_type == "bar":
        series, ctype = _bars(bars, xl, yval, legend_names, cand, used, confs, notes_review, y_fit, x_numeric, el["hlines"])
        chart_type = ctype
    elif chart_type == "line":
        series = _lines(el["slants"], xl, yval, confs, notes_review)
    elif chart_type == "scatter":
        series = _scatter(el["markers"], xl, yval, confs, notes_review, cand, bbox, used)
    elif chart_type == "pie":
        confs["axis_calibration"] = 0.9
        notes_review = []
    if not any(s["points"] for s in series):
        return None

    # ---- titles / axis labels from remaining text ------------------------------------------------------
    rest = [l for l in cand if id(l) not in used]
    title = next((l for l in sorted(rest, key=lambda l: l["bbox"][1]) if l["bbox"][3] <= bbox[1] + 4 or (l["bbox"][1] <= bbox[1] + 2)), None)
    if title:
        used.add(id(title))
    ytitle = next((l for l in rest if id(l) not in used and (abs(l["dir"][1]) > 0.5 or l["bbox"][2] <= bbox[0] - 2) and parse_number(l["text"]) is None), None)
    if ytitle:
        used.add(id(ytitle))
    xtitle = next((l for l in sorted(rest, key=lambda l: l["bbox"][1]) if id(l) not in used and l["bbox"][1] >= bbox[3] - 6 and abs(l["dir"][1]) < 0.5), None)
    if xtitle:
        used.add(id(xtitle))
    unit = (_unit_from(ytitle["text"]) if ytitle else None) or ytype_unit or None
    if chart_type == "pie":
        unit = "%"
    absorbed = [l for l in cand if id(l) in used]
    # unexplained leftover chart text (e.g. data labels already merged) is still part of the chart
    absorbed += [l for l in cand if id(l) not in used and _inside(l["bbox"], bbox, 2.0)]
    boxes = [bbox] + [l["bbox"] for l in absorbed]
    cats = [p.get("category") for p in series[0]["points"]] if series else []
    chart = {
        "chart_type": chart_type, "title": title["text"] if title else None,
        "x_axis": {"label": xtitle["text"] if xtitle else None, "categories": [c for c in cats if c is not None] if not x_numeric else None,
                   "ticks": [parse_number(l["text"])[0] for l in xl] if x_numeric else None},
        "y_axis": {"label": ytitle["text"] if ytitle else None, "unit": unit, "ticks": (y_fit or {}).get("ticks"),
                   "min": min((y_fit or {}).get("ticks", [None]) or [None]) if y_fit else None,
                   "max": max((y_fit or {}).get("ticks", [None]) or [None]) if y_fit else None},
        "series": series, "data_extracted": not notes_review and confs.get("axis_calibration", 0) >= 0.5 or chart_type == "pie",
    }
    chart["y_axis"] = {k: (None if v == [None] else v) for k, v in chart["y_axis"].items()}
    if notes_review:
        chart["data_extracted"] = False
        chart["review_reason"] = " ".join(notes_review)
    sig = {k: round(v, 3) for k, v in confs.items()}
    return {"chart": chart, "bbox": [round(v, 2) for v in _union(boxes)], "absorbed": absorbed, "signals": sig}


def _bars(bars, xl, yval, legend_names, cand, used, confs, notes, y_fit, x_numeric, hlines):
    vertical = Counter(round(r["bbox"][3]) for r in bars).most_common(1)[0][1] >= 2
    if not vertical:
        notes.append("Horizontal bar charts are not supported; values not extracted.")
        return [{"name": None, "color": None, "points": [{"category": None, "value": None, "bbox": r["bbox"]} for r in bars]}], "bar"
    base = Counter(round(r["bbox"][3]) for r in bars).most_common(1)[0][0]
    bars = sorted([r for r in bars if abs(r["bbox"][3] - base) <= 1.5], key=lambda r: r["bbox"][0])
    widths = [r["bbox"][2] - r["bbox"][0] for r in bars]
    gaps = [bars[i + 1]["bbox"][0] - bars[i]["bbox"][2] for i in range(len(bars) - 1)]
    contiguous = bool(gaps) and len({r["fill"] for r in bars}) == 1 and max(abs(g) for g in gaps) <= 0.15 * float(np.median(widths))
    spacing = float(np.median(np.diff([_cx(l["bbox"]) for l in xl]))) if len(xl) >= 2 else None
    labels_by_bar, matched = [], 0
    for r in bars:
        lab = _nearest_label(_cx(r["bbox"]), xl, 0.6 * (spacing or 1e9) if spacing else 1e9) if xl else None
        labels_by_bar.append(lab)
        matched += lab is not None
    confs["structure"] = matched / len(bars) if xl else 0.5
    if not xl:
        notes.append("Category labels not found.")
    fills = sorted({r["fill"] for r in bars}, key=lambda f: min(r["bbox"][0] for r in bars if r["fill"] == f))
    series_pts: dict[str, list] = {f: [] for f in fills}
    agree = []
    for r, lab in zip(bars, labels_by_bar):
        b = r["bbox"]
        v = yval(b[1])
        printed = [l for l in cand if parse_number(l["text"]) and abs(_cx(l["bbox"]) - _cx(b)) <= max(6, (b[2] - b[0]) * 0.7)
                   and b[1] - 24 <= _cy(l["bbox"]) <= b[3] and l["bbox"][2] > b[0] - 5 and id(l) not in used and l["bbox"][2] > 0
                   and (l["bbox"][3] <= b[1] + 3 or _inside(l["bbox"], b, 1))]
        lv = None
        if printed:
            pl = min(printed, key=lambda l: abs(_cy(l["bbox"]) - b[1]))
            lv = parse_number(pl["text"])[0]
            used.add(id(pl))
            if v is not None:
                agree.append(abs(lv - v) <= max(0.02 * abs(lv), (y_fit or {"step": 1})["step"] * 0.15))
        pt = {"category": lab["text"] if lab else None, "value": lv if lv is not None else v, "label_value": lv, "bbox": [round(x, 2) for x in b]}
        series_pts[r["fill"]].append(pt)
    if agree:
        confs["label_agreement"] = sum(agree) / len(agree)
        if not all(agree):
            notes.append("Printed data labels disagree with values read from the axis.")
    names = [legend_names.get(f) for f in fills]
    if len(fills) > 1 and not any(names):
        notes.append("Multiple series without a legend; series names unknown.")
    series = [{"name": legend_names.get(f) or (f"Series {i + 1}" if len(fills) > 1 else None), "color": f, "points": series_pts[f]} for i, f in enumerate(fills)]
    ctype = "histogram" if contiguous else "bar"
    if contiguous:
        for s in series:
            for p, r in zip(s["points"], bars):
                p["bin_start_x"], p["bin_end_x"] = round(r["bbox"][0], 2), round(r["bbox"][2], 2)
        if x_numeric:  # numeric ticks sit on bin EDGES -> calibrate and report edges
            fit = _fit([_cx(l["bbox"]) for l in xl], [parse_number(l["text"])[0] for l in xl])
            if fit and fit["r2"] > 0.999:
                for s in series:
                    for p in s["points"]:
                        p["bin_start"] = round(fit["a"] * p["bin_start_x"] + fit["b"], 3)
                        p["bin_end"] = round(fit["a"] * p["bin_end_x"] + fit["b"], 3)
    return series, ctype


def _lines(slants, xl, yval, confs, notes):
    by_color: dict[str, list] = defaultdict(list)
    for s in slants:
        by_color[s["color"]].append(s)
    series = []
    for color, segs in by_color.items():
        verts: dict[int, tuple] = {}
        for s in segs:
            for p in (s["p"], s["q"]):
                verts.setdefault(round(p[0]), p)
        pts = []
        for x, y in sorted(verts.values()):
            lab = _nearest_label(x, xl, 0.6 * float(np.median(np.diff([_cx(l["bbox"]) for l in xl]))) if len(xl) >= 2 else 1e9) if xl else None
            pts.append({"category": lab["text"] if lab else None, "x_pos": round(x, 2), "value": yval(y)})
        series.append({"name": None, "color": color, "points": pts})
    confs["structure"] = sum(p["category"] is not None for s in series for p in s["points"]) / max(1, sum(len(s["points"]) for s in series))
    confs["chart_detection"] = 0.8
    if len(series) > 1:
        notes.append("Multiple line series without a legend; series names unknown.")
    return series


def _scatter(markers, xl, yval, confs, notes, cand, bbox, used):
    x_fit = _fit([_cx(l["bbox"]) for l in xl], [parse_number(l["text"])[0] for l in xl]) if len(xl) >= 2 and all(parse_number(l["text"]) for l in xl) else None
    if not x_fit:
        notes.append("X-axis ticks not numeric/readable; scatter x-values not extracted.")
    pts = []
    for m in markers:
        cx, cy = _cx(m["bbox"]), _cy(m["bbox"])
        pts.append({"x": round(x_fit["a"] * cx + x_fit["b"], 3) if x_fit else None, "value": yval(cy), "bbox": [round(v, 2) for v in m["bbox"]]})
    confs["structure"] = 0.9 if x_fit else 0.3
    return [{"name": None, "color": markers[0]["fill"], "points": sorted(pts, key=lambda p: p["bbox"][0])}]


def _pie(wedges, cand, used):
    # centre = the point shared by the radial lines of most wedges
    pts = Counter()
    for w in wedges:
        for it in w["items"]:
            if it[0] == "l":
                for p in (it[1], it[2]):
                    pts[(round(p.x, 0), round(p.y, 0))] += 1
    if not pts:
        return None
    (cx, cy), n = pts.most_common(1)[0]
    if n < 2 * len(wedges) - 1:
        return None
    sweeps = []
    for w in wedges:
        total = 0.0
        for it in w["items"]:
            if it[0] == "c":
                a0 = math.atan2(it[1].y - cy, it[1].x - cx)
                a1 = math.atan2(it[4].y - cy, it[4].x - cx)
                d = (a1 - a0 + math.pi) % (2 * math.pi) - math.pi
                total += abs(d)
        sweeps.append(total)
    tot = sum(sweeps)
    if tot < 0.8 * 2 * math.pi or tot > 1.2 * 2 * math.pi:
        return None
    pts_out = []
    for w, sw in zip(wedges, sweeps):
        b = w["bbox"]
        mid_x, mid_y = _cx(b), _cy(b)
        mid_ang = math.atan2(mid_y - cy, mid_x - cx)
        best, bd = None, 1e9
        for l in cand:
            if id(l) in used or parse_number(l["text"]) and "%" in l["text"] and False:
                continue
            a = math.atan2(_cy(l["bbox"]) - cy, _cx(l["bbox"]) - cx)
            d = abs((a - mid_ang + math.pi) % (2 * math.pi) - math.pi)
            if d < bd and d < 0.5 and not parse_number(l["text"]):
                best, bd = l, d
        pct = [l for l in cand if parse_number(l["text"]) and "%" in l["text"] and id(l) not in used
               and abs((math.atan2(_cy(l["bbox"]) - cy, _cx(l["bbox"]) - cx) - mid_ang + math.pi) % (2 * math.pi) - math.pi) < 0.5]
        if best:
            used.add(id(best))
        label_value = None
        if pct:
            used.add(id(pct[0]))
            label_value = parse_number(pct[0]["text"])[0]
        pts_out.append({"category": best["text"] if best else None, "value": round(100 * sw / tot, 1), "label_value": label_value,
                        "color": w["fill"], "bbox": [round(v, 2) for v in b]})
    return [{"name": None, "color": None, "points": pts_out}]


def extract_chart(region: dict) -> dict:
    """Figure that merely LOOKS like a chart (raster image, or vector without readable structure):
    preserved as an image; only printed text is reported; values are not read."""
    return {"signals": {"chart_detection": float(region.get("confidence", 0.55)), "chart_understanding": 0.3},
            "meta": {"data": None, "data_extracted": False, "visible_labels": region.get("embedded_text", []),
                     "review_reason": "Chart values not extracted; refer to the preserved image."}}
