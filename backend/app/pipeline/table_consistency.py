"""Semantic table validation: do the totals printed in an extracted table actually add up?

Confidence scoring answers "how sure are we that we READ this table correctly?".
This module answers a different question: "does what we read make arithmetic sense?".

    Revenue
    2023     40
    2024     50
    Total    95      ->  TABLE CONSISTENCY WARNING  (expected total 90, extracted total 95)

What is checked
  * Column totals  - a row labelled Total / Subtotal / Grand total / Sum (English, Hindi, Tamil)
                     is compared with the sum of the numeric rows above it.
  * Row totals     - a column headed Total / Sum is compared with the sum of the other numeric
                     columns in the same row.
  * Subtotals      - a Total row may equal the detail rows OR the sum of the subtotals above it.

What is deliberately NOT checked (to avoid false alarms)
  * Percentage, rate, ratio, price, average, score, year, rank and serial-number columns.
  * Totals with fewer than two numbers to add up (nothing to verify).
  * Cells that are not plain numbers (units such as "12 kg", "1.2M", words).

Design rules (same philosophy as the rest of the pipeline)
  * Never raises: a problem in this check can never fail a parse.
  * Never invents data: only reports a mismatch, never "fixes" a number.
  * Never touches confidence scores. A mismatch marks the table REVIEW_REQUIRED, records a
    structured warning in `block.meta["table_consistency"]`, and adds a `TABLE_CONSISTENCY_WARNING`
    entry (severity "warning") to `document.errors`. Tables with no verifiable totals are left
    byte-for-byte unchanged.
  * Rounding aware: printed totals often differ from printed parts by rounding ("figures may not
    add up due to rounding"). By default a difference is accepted only if rounding can explain it
    AND it is below 0.5% of the total, so 10 + 20 = 31 is flagged but 1,000 + 2,000 + 3,000 = 6,001 is not.

Configuration (environment variables, read at call time)
  PARSE_TABLE_CONSISTENCY            on (default) | off
  PARSE_TABLE_CONSISTENCY_TOLERANCE  rounding (default) | strict   (strict = printed numbers must add up exactly)
"""
from __future__ import annotations

import logging
import os
import re
from decimal import Decimal, InvalidOperation
from typing import Any, NamedTuple, Optional

from app.models.block import BlockType, Status
from app.models.document import Document
from app.pipeline.failsafe import make_error

log = logging.getLogger("parse-anything")

ERROR_CODE = "TABLE_CONSISTENCY_WARNING"
_OFF_VALUES = {"off", "0", "false", "no", "disabled"}


def _enabled() -> bool:
    return os.getenv("PARSE_TABLE_CONSISTENCY", "on").strip().lower() not in _OFF_VALUES


def _strict() -> bool:
    return os.getenv("PARSE_TABLE_CONSISTENCY_TOLERANCE", "rounding").strip().lower() == "strict"


# --------------------------------------------------------------------------------------------
# Number parsing
# --------------------------------------------------------------------------------------------
class Num(NamedTuple):
    value: Decimal
    decimals: int      # digits printed after the decimal point (drives rounding tolerance)
    commas: bool       # original used thousands separators (used only to format messages)
    percent: bool      # printed with a % sign: never summed


_PLACEHOLDERS = {"", "-", "\u2013", "\u2014", "n/a", "na", "nil", "--"}
_NUMBER_RE = re.compile(
    r"^(?P<s1>[+-])?\s*(?:rs\.?|inr|usd|eur|gbp|[$\u20ac\u00a3\u00a5\u20b9])?\s*(?P<s2>[+-])?\s*(?P<body>\d[\d.,\s]*)$",
    re.IGNORECASE,
)
_THOUSANDS_COMMA = r"\d{1,3}(?:,\d{2})*,\d{3}|\d{1,3}(?:,\d{3})+"  # 1,234,567 and Indian 12,34,567


def _normalise_digits(body: str) -> Optional[str]:
    body = body.strip()
    if " " in body:
        if not re.fullmatch(r"\d{1,3}(?: \d{3})+(?:[.,]\d+)?", body):
            return None
        body = body.replace(" ", "")
    has_comma, has_dot = "," in body, "." in body
    if has_comma and has_dot:
        if body.rfind(",") > body.rfind("."):  # European: 1.234,56
            if not re.fullmatch(r"\d{1,3}(?:\.\d{3})+,\d+", body):
                return None
            return body.replace(".", "").replace(",", ".")
        head, _, frac = body.rpartition(".")  # US/Indian: 1,234.56
        if not re.fullmatch(_THOUSANDS_COMMA, head) or not frac.isdigit():
            return None
        return head.replace(",", "") + "." + frac
    if has_comma:
        if re.fullmatch(_THOUSANDS_COMMA, body):
            return body.replace(",", "")
        if re.fullmatch(r"\d+,\d{1,2}", body):  # decimal comma: 12,5
            return body.replace(",", ".")
        return None
    if has_dot:
        if re.fullmatch(r"\d{1,3}(?:\.\d{3}){2,}", body):  # 1.234.567
            return body.replace(".", "")
        return body if re.fullmatch(r"\d+\.\d+", body) else None
    return body


def parse_number(raw: Any) -> Optional[Num]:
    """Parse a table cell into a number, or None if it is not a plain number."""
    if raw is None or isinstance(raw, bool):
        return None
    if isinstance(raw, (int, float, Decimal)):
        try:
            d = Decimal(str(raw))
        except InvalidOperation:
            return None
        if not d.is_finite():
            return None
        return Num(d, max(0, -d.as_tuple().exponent), False, False)
    s = str(raw).replace("\u00a0", " ").strip()
    if s.lower() in _PLACEHOLDERS:
        return None
    negative = False
    if s.startswith("(") and s.endswith(")"):
        negative, s = True, s[1:-1].strip()
    s = s.translate({ord("\u2212"): "-", ord("\u2013"): "-", ord("\u2014"): "-"})
    s = s.rstrip("*\u2020\u2021\u00a7 ")  # footnote markers: 95*
    if s.endswith("-") and s[:-1].strip().replace(",", "").replace(".", "").isdigit():
        negative, s = True, s[:-1].strip()  # trailing minus: 95-
    percent = s.endswith("%")
    if percent:
        s = s[:-1].strip()
    m = _NUMBER_RE.match(s)
    if not m:
        return None
    digits = _normalise_digits(m.group("body"))
    if digits is None:
        return None
    try:
        value = Decimal(digits)
    except InvalidOperation:
        return None
    if "-" in (m.group("s1"), m.group("s2")):
        negative = not negative
    decimals = len(digits.split(".")[1]) if "." in digits else 0
    return Num(-value if negative else value, decimals, "," in m.group("body"), percent)


def _fmt(value: Decimal, decimals: int, commas: bool) -> str:
    q = value.quantize(Decimal(1).scaleb(-decimals)) if decimals else value.quantize(Decimal(1))
    return f"{q:,.{decimals}f}" if commas else f"{q:.{decimals}f}"


# --------------------------------------------------------------------------------------------
# Label recognition
# --------------------------------------------------------------------------------------------
# "(?!\w)" instead of "\b": Devanagari/Tamil words end in combining marks, which are not \w.
_TOTAL_RE = re.compile(
    r"^[\W_]*(?:(?:grand|overall|net|sub|final)[\s\-]*)?(?:totals?|\u0915\u0941\u0932|\u0bae\u0bca\u0ba4\u0bcd\u0ba4\u0bae\u0bcd)(?!\w)",
    re.IGNORECASE,
)
_SUM_RE = re.compile(r"^[\W_]*sum[\W_]*$", re.IGNORECASE)  # exactly "Sum" (not "Sum insured")
_SUB_RE = re.compile(r"sub[\s\-]*total", re.IGNORECASE)
_GRAND_RE = re.compile(r"grand|overall|net|final", re.IGNORECASE)
# Columns whose values are not meant to be added up.
_NON_ADDITIVE_RE = re.compile(
    r"\b(?:avg|average|mean|median|rate|ratio|percent(?:age)?|share|margin|price|score|rank|index|year|fy|age|"
    r"growth|change|yoy|cagr|id|no|sl|sr|sno)\b|%|#|\bper\s",
    re.IGNORECASE,
)


def _is_total_label(label: str) -> bool:
    return bool(label) and bool(_TOTAL_RE.match(label) or _SUM_RE.match(label))


# --------------------------------------------------------------------------------------------
# Sum candidates and verification
# --------------------------------------------------------------------------------------------
class _Item(NamedTuple):
    is_total: bool
    num: Optional[Num]  # None => blank / not numeric / not additive


def _candidates(items: list[_Item], allow_drop_first: bool = False) -> list[tuple[str, Decimal, int, int]]:
    """Plausible things a total could be the sum of: (name, sum, number_of_terms, max_decimals)."""
    last_total = max((k for k, it in enumerate(items) if it.is_total), default=-1)
    details_all = [it.num for it in items if not it.is_total and it.num is not None]
    details_tail = [it.num for k, it in enumerate(items) if k > last_total and not it.is_total and it.num is not None]
    earlier_totals = [it.num for it in items if it.is_total and it.num is not None]
    out: list[tuple[str, Decimal, int, int]] = []

    def add(name: str, terms: list[Num]) -> None:
        if len(terms) >= 2:
            out.append((name, sum((t.value for t in terms), Decimal(0)), len(terms), max(t.decimals for t in terms)))

    add("section", details_tail)  # rows since the previous total (== all rows if none)
    if last_total >= 0:
        add("all_items", details_all)
        add("subtotals", earlier_totals + details_tail)
    if allow_drop_first:  # an unlabelled leading numeric column (index, year) may have slipped in
        add("drop_first", details_tail[1:])
    return out


def _tolerance(decimals: int, n_terms: int, total: Decimal) -> Decimal:
    if _strict():
        return Decimal(0)
    unit = Decimal(1).scaleb(-decimals)
    # n printed parts and the printed total can each be off by half a unit of the last digit ...
    bound = Decimal("0.5") * unit * (n_terms + 1)
    # ... but only forgive that when it is plausible: never more than 0.5% of the total itself
    # (so 10 + 20 = 31 is flagged, while 1,000 + 2,000 + 3,000 = 6,001 is not).
    cap = max(Decimal("0.5") * unit, Decimal("0.005") * abs(total))
    return min(bound, cap)


def _verify(total: Num, label: str, items: list[_Item], allow_drop_first: bool = False) -> Optional[dict[str, Any]]:
    """None => nothing verifiable. {"ok": True} or {"ok": False, expected/extracted strings}."""
    cands = _candidates(items, allow_drop_first)
    if not cands:
        return None
    for _, total_sum, n, dec in cands:
        if abs(total.value - total_sum) <= _tolerance(max(dec, total.decimals), n, total.value):
            return {"ok": True}
    by_name = {c[0]: c for c in cands}
    if _SUB_RE.search(label or ""):
        order = ["section", "all_items", "subtotals"]
    elif _GRAND_RE.search(label or "") and "subtotals" in by_name:
        order = ["subtotals", "section", "all_items"]
    else:
        order = ["section", "all_items", "subtotals"]
    _, exp_sum, _, dec = by_name[next(n for n in order if n in by_name)]
    d = max(dec, total.decimals)
    commas = total.commas
    expected, extracted = _fmt(exp_sum, d, commas), _fmt(total.value, d, commas)
    return {"ok": False, "expected": expected, "extracted": extracted,
            "difference": ("+" if total.value >= exp_sum else "-") + _fmt(abs(total.value - exp_sum), d, commas)}


# --------------------------------------------------------------------------------------------
# Table layout
# --------------------------------------------------------------------------------------------
def _text(cell: Any) -> str:
    return "" if cell is None else str(cell).strip()


def _layout(content: dict) -> tuple[list[str], int, list[list[Any]]]:
    """-> (column labels, header_row_count, body rows). Falls back to a text-only first row as header."""
    headers = [list(r) for r in (content.get("headers") or [])]
    body = [list(r) for r in (content.get("rows") or [])]
    n_cols = max([int(content.get("n_cols") or 0)] + [len(r) for r in headers + body])
    header_rows = len(headers)
    if not headers and len(body) > 1:
        first = body[0]
        if any(_text(c) for c in first) and all(parse_number(c) is None for c in first):
            headers, body, header_rows = [first], body[1:], 1
    labels = []
    for j in range(n_cols):
        parts: list[str] = []
        for hr in headers:
            t = _text(hr[j]) if j < len(hr) else ""
            if t and (not parts or parts[-1] != t):
                parts.append(t)
        labels.append(" / ".join(parts))
    return labels, header_rows, body


def _column_is_additive(label: str, details: list[Optional[Num]]) -> bool:
    if _NON_ADDITIVE_RE.search(label or ""):
        return False
    nums = [n for n in details if n is not None]
    if any(n.percent for n in nums):
        return False
    if len(nums) >= 2:
        ints = [n.value for n in nums if n.decimals == 0 and not n.commas]
        if len(ints) == len(nums):
            if all(Decimal(1900) <= v <= Decimal(2100) for v in ints):
                return False  # a column of years
            if [int(v) for v in ints] == list(range(int(ints[0]), int(ints[0]) + len(ints))) and int(ints[0]) in (0, 1):
                return False  # 1, 2, 3 ... serial numbers
    return True


# --------------------------------------------------------------------------------------------
# Public: one table
# --------------------------------------------------------------------------------------------
def check_table(content: dict) -> dict[str, Any]:
    """Validate one canonical table (`TableData` as a dict). Returns counts and structured warnings."""
    labels, header_rows, body = _layout(content)
    n_cols = len(labels)
    cell = lambda i, j: body[i][j] if j < len(body[i]) else None  # noqa: E731
    parsed = [[parse_number(cell(i, j)) for j in range(n_cols)] for i in range(len(body))]
    texts = [[_text(cell(i, j)) for j in range(n_cols)] for i in range(len(body))]

    def row_label(i: int) -> str:
        for j in range(min(2, n_cols)):
            if texts[i][j] and parsed[i][j] is None:
                return texts[i][j]
        return ""

    rlabels = [row_label(i) for i in range(len(body))]
    is_total_row = [_is_total_label(l) for l in rlabels]
    col_total = [_is_total_label(l.split(" / ")[-1]) or _is_total_label(l) for l in labels]
    additive = [_column_is_additive(labels[j], [parsed[i][j] for i in range(len(body)) if not is_total_row[i]])
                for j in range(n_cols)]
    col_name = lambda j: labels[j] or f"Column {j + 1}"  # noqa: E731
    result: dict[str, Any] = {"checks_run": 0, "checks_passed": 0, "warnings": []}

    def record(outcome: Optional[dict], warning: dict[str, Any]) -> None:
        if outcome is None:
            return
        result["checks_run"] += 1
        if outcome["ok"]:
            result["checks_passed"] += 1
        else:
            warning.update(expected=outcome["expected"], extracted=outcome["extracted"], difference=outcome["difference"])
            result["warnings"].append(warning)

    # 1) Column totals: a Total row vs the numbers above it.
    for i in (k for k, t in enumerate(is_total_row) if t):
        for j in range(n_cols):
            num = parsed[i][j]
            if num is None or num.percent or not additive[j]:
                continue
            items = [_Item(is_total_row[k], parsed[k][j]) for k in range(i)]
            outcome = _verify(num, rlabels[i], items)
            msg = None
            if outcome and not outcome["ok"]:
                msg = (f"Table total mismatch in column '{col_name(j)}' (row '{rlabels[i]}'): "
                       f"expected total {outcome['expected']}, extracted total {outcome['extracted']}")
            record(outcome, {"kind": "column_total", "label": rlabels[i], "column": col_name(j),
                             "row": header_rows + i + 1, "message": msg})

    # 2) Row totals: a Total column vs the other numbers in the same row.
    for tc in (j for j, t in enumerate(col_total) if t):
        for i in range(len(body)):
            num = parsed[i][tc]
            if is_total_row[i] or num is None or num.percent:
                continue
            items = []
            for k in range(tc):
                cell_num = parsed[i][k]
                usable = cell_num is not None and not cell_num.percent and (additive[k] or col_total[k])
                items.append(_Item(col_total[k], cell_num if usable else None))
            outcome = _verify(num, labels[tc], items, allow_drop_first=True)
            msg = None
            who = rlabels[i] or f"row {header_rows + i + 1}"
            if outcome and not outcome["ok"]:
                msg = (f"Table total mismatch in row '{who}', column '{col_name(tc)}': "
                       f"expected total {outcome['expected']}, extracted total {outcome['extracted']}")
            record(outcome, {"kind": "row_total", "label": who, "column": col_name(tc),
                             "row": header_rows + i + 1, "message": msg})
    return result


def format_warning(w: dict[str, Any]) -> str:
    """Human-readable block for logs / CLIs / UIs."""
    return (f"\u26a0\ufe0f TABLE CONSISTENCY WARNING\n"
            f"Expected total: {w['expected']}\n"
            f"Extracted total: {w['extracted']}\n"
            f"Where: {w['column']} / {w['label']} (table row {w['row']})")


# --------------------------------------------------------------------------------------------
# Public: whole document (pipeline stage)
# --------------------------------------------------------------------------------------------
def add_table_consistency(document: Document) -> Document:
    """Validate every table block. Safe to call on any document; never raises."""
    if not _enabled():
        return document
    for b in document.blocks:
        if b.type != BlockType.table or b.status == Status.failed or not isinstance(b.content, dict):
            continue
        try:
            res = check_table(b.content)
        except Exception:  # a validation problem must never fail a parse
            log.warning("table consistency check skipped for block %s", b.id, exc_info=True)
            continue
        if not res["checks_run"]:
            continue  # nothing verifiable: leave the block exactly as it was
        warnings = res["warnings"]
        b.meta["table_consistency"] = {
            "status": "WARNING" if warnings else "PASS",
            "checks_run": res["checks_run"], "checks_passed": res["checks_passed"], "warnings": warnings,
        }
        if not warnings:
            continue
        reason = "TABLE CONSISTENCY WARNING: " + "; ".join(w["message"] for w in warnings[:3])
        if len(warnings) > 3:
            reason += f" (+{len(warnings) - 3} more)"
        previous = b.meta.get("review_reason")
        b.meta["review_reason"] = f"{previous}; {reason}" if previous else reason
        b.status = Status.review
        for w in warnings:
            document.errors.append(make_error(ERROR_CODE, w["message"], page=b.page, block_id=b.id, severity="warning"))
    return document
